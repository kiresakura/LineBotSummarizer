"""情報寫入 Notion — 將收集到的情報項目寫入情報資料庫"""

import logging

from app.config import get_settings
from app.models.intel import IntelItem
from app.pipeline.writer import TokenBucketRateLimiter

logger = logging.getLogger(__name__)


class IntelWriter:
    """將情報項目寫入 Notion 情報資料庫"""

    _limiter: TokenBucketRateLimiter | None = None

    def __init__(self):
        settings = get_settings()
        if IntelWriter._limiter is None:
            IntelWriter._limiter = TokenBucketRateLimiter(
                rate=settings.notion_rate_limit
            )
        self.limiter = IntelWriter._limiter

    async def write_batch(self, items: list[IntelItem]) -> int:
        """批次寫入情報項目，回傳成功筆數"""
        written = 0
        for item in items:
            try:
                await self._write_one(item)
                written += 1
            except Exception as e:
                logger.error(f"情報寫入失敗 [{item.title[:40]}]: {e}")
        return written

    async def _write_one(self, item: IntelItem, max_retries: int = 3):
        """寫入單筆情報到 Notion"""
        import asyncio
        settings = get_settings()

        properties = self._build_properties(item)
        children = self._build_content_blocks(item)

        for attempt in range(max_retries):
            await self.limiter.acquire()
            try:
                from notion_client import AsyncClient
                notion = AsyncClient(auth=settings.notion_api_key)

                page = await notion.pages.create(
                    parent={"database_id": settings.intel_notion_database_id},
                    properties=properties,
                    children=children,
                )
                logger.debug(f"情報寫入成功: {page['id']} — {item.title[:40]}")
                return page

            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "rate_limited" in error_str:
                    wait = 2 ** attempt
                    logger.warning(f"Notion 限流，等待 {wait}s 後重試...")
                    await asyncio.sleep(wait)
                else:
                    logger.error(f"情報寫入失敗 (attempt {attempt + 1}): {e}")
                    if attempt == max_retries - 1:
                        raise

    def _build_properties(self, item: IntelItem) -> dict:
        """構建 Notion Page Properties"""
        properties: dict = {
            "Title": {"title": [{"text": {"content": item.title[:100]}}]},
            "URL": {"url": item.url},
            "Source": {"select": {"name": item.source_name or item.source.value}},
            "Tags": {
                "multi_select": [{"name": t} for t in item.tags[:5]]
            },
            "Collected": {
                "date": {"start": item.collected_at.isoformat()}
            },
        }

        if item.published_at:
            properties["Published"] = {
                "date": {"start": item.published_at.isoformat()}
            }

        if item.content_preview:
            properties["Preview"] = {
                "rich_text": [{"text": {"content": item.content_preview[:2000]}}]
            }

        return properties

    def _build_content_blocks(self, item: IntelItem) -> list:
        """構建 Notion Page 內容區塊"""
        blocks: list[dict] = []

        # 書籤連結
        blocks.append({
            "object": "block",
            "type": "bookmark",
            "bookmark": {"url": item.url},
        })

        # 內容預覽
        if item.content_preview:
            blocks.append({
                "object": "block",
                "type": "heading_3",
                "heading_3": {
                    "rich_text": [{"text": {"content": "內容預覽"}}]
                },
            })
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"text": {"content": item.content_preview}}]
                },
            })

        # 元資料
        meta_parts = [f"來源：{item.source_name or item.source.value}"]
        if item.published_at:
            meta_parts.append(f"發布時間：{item.published_at.strftime('%Y-%m-%d %H:%M')}")
        meta_parts.append(f"收集時間：{item.collected_at.strftime('%Y-%m-%d %H:%M')}")

        blocks.append({
            "object": "block",
            "type": "callout",
            "callout": {
                "rich_text": [{"text": {"content": " | ".join(meta_parts)}}],
                "icon": {"emoji": "📡"},
            },
        })

        return blocks
