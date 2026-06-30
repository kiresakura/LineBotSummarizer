"""Notion sink — implements `KnowledgeSink`, writing entries as Notion pages.

Honors Notion's limits: ≤100 child blocks/page, ≤2000 chars/rich-text run, and
≤3 req/s (a token-bucket keeps us at 2.5 req/s). Retries with exponential
backoff on 429.

Expected database properties: Title (title), Category (select),
Importance (select), Tags (multi-select), Source (select), Date (date),
Knowledge (rich_text), Has Action Items (checkbox), URLs (url).
"""

import asyncio
import logging
import re
import time

from lorekeeper.adapters.notion_blocks import (
    markdown_to_blocks,
    parse_inline,
    split_rich_text,
)
from lorekeeper.models import KnowledgeEntry

logger = logging.getLogger(__name__)

NOTION_MAX_BLOCKS = 100
IMPORTANCE_LABEL = {
    "high": "🔴 高",
    "medium": "🟡 中",
    "low": "🟢 低",
    "noise": "⚪ 噪音",
}


class TokenBucketRateLimiter:
    """令牌桶限流器 — 控制 Notion API 呼叫速率。"""

    def __init__(self, rate: float = 2.5):
        self.rate = rate
        self.tokens = rate
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            self.tokens = min(
                self.rate, self.tokens + (now - self.last_refill) * self.rate
            )
            self.last_refill = now
            if self.tokens < 1:
                await asyncio.sleep((1 - self.tokens) / self.rate)
                self.tokens = 0
            else:
                self.tokens -= 1


class NotionSink:
    name = "notion"

    def __init__(self, api_key: str, database_id: str, *, rate_limit: float = 2.5):
        self.api_key = api_key
        self.database_id = database_id
        self.limiter = TokenBucketRateLimiter(rate_limit)

    async def write(self, entry: KnowledgeEntry, max_retries: int = 3) -> None:
        from notion_client import AsyncClient

        properties = self._build_properties(entry)
        children = self._build_blocks(entry)
        notion = AsyncClient(auth=self.api_key)

        for attempt in range(max_retries):
            await self.limiter.acquire()
            try:
                page = await notion.pages.create(
                    parent={"database_id": self.database_id},
                    properties=properties,
                    children=children,
                )
                logger.info(f"Notion 寫入成功: {page['id']}")
                return
            except Exception as e:  # noqa: BLE001
                if "429" in str(e) or "rate_limited" in str(e):
                    wait = 2**attempt
                    logger.warning(f"Notion 限流，等待 {wait}s 後重試...")
                    await asyncio.sleep(wait)
                elif attempt == max_retries - 1:
                    raise
                else:
                    logger.error(f"Notion 寫入失敗 (attempt {attempt + 1}): {e}")

    def _build_properties(self, entry: KnowledgeEntry) -> dict:
        title = entry.title or entry.knowledge[:100] or "未命名訊息"
        clean = re.sub(r"[#*`>\-]", "", entry.knowledge)[:2000].strip()

        properties: dict = {
            "Title": {"title": [{"text": {"content": title[:100]}}]},
            "Category": {"select": {"name": entry.category}},
            "Importance": {
                "select": {
                    "name": IMPORTANCE_LABEL.get(entry.importance.value, "🟢 低")
                }
            },
            "Tags": {"multi_select": [{"name": tag} for tag in entry.tags[:5]]},
            "Source": {"select": {"name": entry.conversation_label or "未知來源"}},
            "Date": {
                "date": {
                    "start": entry.source_messages[0].timestamp.isoformat()
                    if entry.source_messages
                    else None
                }
            },
            "Knowledge": {"rich_text": split_rich_text(clean)},
            "Has Action Items": {"checkbox": len(entry.action_items) > 0},
        }
        if entry.urls:
            properties["URLs"] = {"url": entry.urls[0]}
        return properties

    def _build_blocks(self, entry: KnowledgeEntry) -> list[dict]:
        blocks: list[dict] = [_heading("📚 知識點整理")]
        blocks.extend(markdown_to_blocks(entry.knowledge))

        if entry.media_descriptions:
            blocks.append(_heading("🖼 媒體內容提取"))
            for idx, desc in enumerate(entry.media_descriptions, 1):
                blocks.append(_heading(f"媒體 {idx}", level=3))
                blocks.extend(markdown_to_blocks(desc))

        if entry.action_items:
            blocks.append(_heading("✅ 待辦事項"))
            for item in entry.action_items:
                blocks.append(
                    {
                        "object": "block",
                        "type": "to_do",
                        "to_do": {"rich_text": parse_inline(item), "checked": False},
                    }
                )

        if entry.urls:
            blocks.append(_heading("🔗 相關連結"))
            for url in entry.urls:
                blocks.append(
                    {"object": "block", "type": "bookmark", "bookmark": {"url": url}}
                )

        blocks.append(_heading("💬 原始訊息"))
        for msg in entry.source_messages:
            time_str = msg.timestamp.strftime("%H:%M")
            sender = msg.sender_name or msg.sender_id[:8]
            body = msg.text or f"[{msg.type.value}]"
            blocks.append(
                {
                    "object": "block",
                    "type": "quote",
                    "quote": {
                        "rich_text": split_rich_text(f"[{time_str}] {sender}: {body}")
                    },
                }
            )

        if len(blocks) > NOTION_MAX_BLOCKS:
            logger.warning(
                f"內容區塊 {len(blocks)} 超過 Notion 上限 {NOTION_MAX_BLOCKS}，截斷尾部"
            )
            blocks = blocks[:NOTION_MAX_BLOCKS]
        return blocks


def _heading(text: str, level: int = 2) -> dict:
    htype = f"heading_{level}"
    return {
        "object": "block",
        "type": htype,
        htype: {"rich_text": [{"text": {"content": text}}]},
    }
