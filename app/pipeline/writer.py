"""Stage 4: Notion 寫入器 — 含限流 & 重試機制"""

import asyncio
import logging
import time
from app.config import get_settings
from app.models.message import ClassifiedMessage

logger = logging.getLogger(__name__)


class TokenBucketRateLimiter:
    """令牌桶限流器 — 控制 Notion API 呼叫速率"""

    def __init__(self, rate: float = 2.5):
        self.rate = rate
        self.tokens = rate
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_refill
            self.tokens = min(self.rate, self.tokens + elapsed * self.rate)
            self.last_refill = now

            if self.tokens < 1:
                wait_time = (1 - self.tokens) / self.rate
                await asyncio.sleep(wait_time)
                self.tokens = 0
            else:
                self.tokens -= 1


class NotionWriter:
    """將分類後的訊息寫入 Notion Database"""

    _limiter = None

    def __init__(self):
        settings = get_settings()
        if NotionWriter._limiter is None:
            NotionWriter._limiter = TokenBucketRateLimiter(
                rate=settings.notion_rate_limit
            )
        self.limiter = NotionWriter._limiter

    async def write(self, classified: ClassifiedMessage, max_retries: int = 3):
        """寫入一筆分類結果到 Notion"""
        settings = get_settings()

        # 構建 Notion Page 資料
        properties = self._build_properties(classified)
        children = self._build_content_blocks(classified)

        for attempt in range(max_retries):
            await self.limiter.acquire()

            try:
                from notion_client import AsyncClient
                notion = AsyncClient(auth=settings.notion_api_key)

                page = await notion.pages.create(
                    parent={"database_id": settings.notion_database_id},
                    properties=properties,
                    children=children,
                )
                logger.info(f"Notion 寫入成功: {page['id']}")
                return page

            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "rate_limited" in error_str:
                    wait = 2 ** attempt  # 指數退避
                    logger.warning(f"Notion 限流，等待 {wait}s 後重試...")
                    await asyncio.sleep(wait)
                else:
                    logger.error(f"Notion 寫入失敗 (attempt {attempt+1}): {e}")
                    if attempt == max_retries - 1:
                        raise

    def _build_properties(self, classified: ClassifiedMessage) -> dict:
        """構建 Notion Page Properties"""
        settings = get_settings()

        # 摘要標題（截取前 100 字）
        title = classified.summary[:100] if classified.summary else "未命名訊息"

        # 原始訊息合併
        original_text = "\n".join(
            f"[{m.timestamp.strftime('%H:%M')}] {m.user_name or m.user_id[:8]}: {m.text}"
            for m in classified.original_messages
            if m.text
        )

        properties = {
            "Title": {"title": [{"text": {"content": title}}]},
            "Category": {"select": {"name": classified.category}},
            "Importance": {
                "select": {
                    "name": {
                        "high": "🔴 高",
                        "medium": "🟡 中",
                        "low": "🟢 低",
                    }.get(classified.importance.value, "🟢 低")
                }
            },
            "Tags": {
                "multi_select": [{"name": tag} for tag in classified.tags[:5]]
            },
            "Source Group": {
                "select": {"name": classified.group_name or "未知群組"}
            },
            "Date": {
                "date": {
                    "start": classified.original_messages[0].timestamp.isoformat()
                    if classified.original_messages else None
                }
            },
            "Summary": {
                "rich_text": [{"text": {"content": classified.summary[:2000]}}]
            },
            "Has Action Items": {
                "checkbox": len(classified.action_items) > 0
            },
        }

        # URL（如果有的話）
        if classified.urls_found:
            properties["URLs"] = {"url": classified.urls_found[0]}

        return properties

    def _build_content_blocks(self, classified: ClassifiedMessage) -> list:
        """構建 Notion Page 內容區塊"""
        blocks = []

        # 摘要區
        blocks.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"text": {"content": "📝 摘要"}}]
            }
        })
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"text": {"content": classified.summary}}]
            }
        })

        # 待辦事項
        if classified.action_items:
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"text": {"content": "✅ 待辦事項"}}]
                }
            })
            for item in classified.action_items:
                blocks.append({
                    "object": "block",
                    "type": "to_do",
                    "to_do": {
                        "rich_text": [{"text": {"content": item}}],
                        "checked": False,
                    }
                })

        # 原始訊息（摺疊）
        blocks.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"text": {"content": "💬 原始訊息"}}]
            }
        })

        for msg in classified.original_messages[:20]:  # 最多 20 條
            if msg.text:
                time_str = msg.timestamp.strftime("%H:%M")
                sender = msg.user_name or msg.user_id[:8]
                blocks.append({
                    "object": "block",
                    "type": "quote",
                    "quote": {
                        "rich_text": [{
                            "text": {
                                "content": f"[{time_str}] {sender}: {msg.text[:2000]}"
                            }
                        }]
                    }
                })

        return blocks
