"""Stage 4: Notion 寫入器 — 含限流 & 重試機制"""

import asyncio
import logging
import time
from app.config import get_settings
from app.models.message import ClassifiedMessage

logger = logging.getLogger(__name__)

# Notion rich_text 單個區塊上限 2000 字元
NOTION_TEXT_LIMIT = 2000


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


def _split_rich_text(text: str) -> list[dict]:
    """將長文字拆成多個 rich_text 區塊（每個最多 2000 字元）"""
    if not text:
        return [{"text": {"content": ""}}]
    parts = []
    for i in range(0, len(text), NOTION_TEXT_LIMIT):
        parts.append({"text": {"content": text[i:i + NOTION_TEXT_LIMIT]}})
    return parts


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
                    wait = 2 ** attempt
                    logger.warning(f"Notion 限流，等待 {wait}s 後重試...")
                    await asyncio.sleep(wait)
                else:
                    logger.error(f"Notion 寫入失敗 (attempt {attempt+1}): {e}")
                    if attempt == max_retries - 1:
                        raise

    def _build_properties(self, classified: ClassifiedMessage) -> dict:
        """構建 Notion Page Properties"""
        title = classified.title or classified.summary[:100] or "未命名訊息"

        properties = {
            "Title": {"title": [{"text": {"content": title[:100]}}]},
            "Category": {"select": {"name": classified.category}},
            "Importance": {
                "select": {
                    "name": {
                        "high": "🔴 高",
                        "medium": "🟡 中",
                        "low": "🟢 低",
                        "noise": "⚪ 噪音",
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
                "rich_text": _split_rich_text(classified.summary)
            },
            "Has Action Items": {
                "checkbox": len(classified.action_items) > 0
            },
        }

        if classified.urls_found:
            properties["URLs"] = {"url": classified.urls_found[0]}

        return properties

    def _split_text_blocks(self, text: str, block_type: str = "paragraph") -> list:
        """將長文字拆分為多個 Notion block（每個 block 上限 2000 字元，按段落保持語意完整）"""
        blocks = []
        paragraphs = text.split("\n")
        current_chunk = ""

        for para in paragraphs:
            if len(current_chunk) + len(para) + 1 > 1900:
                if current_chunk:
                    blocks.append({
                        "object": "block",
                        "type": block_type,
                        block_type: {
                            "rich_text": [{"text": {"content": current_chunk}}]
                        }
                    })
                current_chunk = para
            else:
                current_chunk = current_chunk + "\n" + para if current_chunk else para

        if current_chunk:
            blocks.append({
                "object": "block",
                "type": block_type,
                block_type: {
                    "rich_text": [{"text": {"content": current_chunk}}]
                }
            })

        return blocks

    def _build_content_blocks(self, classified: ClassifiedMessage) -> list:
        """構建 Notion Page 內容區塊 — 最大化保留所有資訊"""
        blocks = []

        # === 知識點整理區 ===
        blocks.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"text": {"content": "📚 知識點整理"}}]
            }
        })
        blocks.extend(self._split_text_blocks(classified.summary))

        # === 媒體內容提取區 ===
        if classified.media_descriptions:
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"text": {"content": "🖼 媒體內容提取"}}]
                }
            })
            for idx, desc in enumerate(classified.media_descriptions, 1):
                blocks.append({
                    "object": "block",
                    "type": "heading_3",
                    "heading_3": {
                        "rich_text": [{"text": {"content": f"媒體 {idx}"}}]
                    }
                })
                blocks.extend(self._split_text_blocks(desc))

        # === 待辦事項 ===
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
                        "rich_text": _split_rich_text(item),
                        "checked": False,
                    }
                })

        # === 相關連結 ===
        if classified.urls_found:
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"text": {"content": "🔗 相關連結"}}]
                }
            })
            for url in classified.urls_found:
                blocks.append({
                    "object": "block",
                    "type": "bookmark",
                    "bookmark": {"url": url}
                })

        # === 原始訊息（完整保留，不設上限）===
        blocks.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"text": {"content": "💬 原始訊息"}}]
            }
        })

        for msg in classified.original_messages:
            time_str = msg.timestamp.strftime("%H:%M")
            sender = msg.user_name or msg.user_id[:8]
            if msg.text:
                content = f"[{time_str}] {sender}: {msg.text}"
            elif msg.message_type.value == "image":
                content = f"[{time_str}] {sender}: [圖片]"
            elif msg.message_type.value == "audio":
                content = f"[{time_str}] {sender}: [音訊]"
            else:
                content = f"[{time_str}] {sender}: [{msg.message_type.value}]"

            blocks.append({
                "object": "block",
                "type": "quote",
                "quote": {
                    "rich_text": _split_rich_text(content)
                }
            })

        # Notion 單次建立頁面最多 100 個子區塊
        if len(blocks) > 100:
            logger.warning(
                f"內容區塊 {len(blocks)} 個超過 Notion 上限 100，截斷尾部"
            )
            blocks = blocks[:100]

        return blocks
