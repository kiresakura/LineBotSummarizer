"""RSS/Atom 收集器 — 從設定中的 feeds 抓取最新情報"""

import asyncio
import logging
from datetime import datetime
from time import mktime

import feedparser
import httpx

from app.config import get_settings
from app.collectors.base import BaseCollector
from app.models.intel import IntelItem, IntelSource

logger = logging.getLogger(__name__)


class RSSCollector(BaseCollector):
    """從 RSS/Atom feeds 收集情報"""

    name = "rss"

    async def collect(self) -> list[IntelItem]:
        """遍歷所有設定的 RSS feeds，收集最新項目"""
        settings = get_settings()
        feeds_str = settings.intel_rss_feeds.strip()
        if not feeds_str:
            logger.warning("未設定 RSS feeds (INTEL_RSS_FEEDS)")
            return []

        feed_urls = [u.strip() for u in feeds_str.split(",") if u.strip()]
        all_items: list[IntelItem] = []

        for url in feed_urls:
            try:
                items = await self._fetch_feed(url, settings.intel_max_items_per_feed)
                all_items.extend(items)
                logger.info(f"RSS 收集完成: {url} → {len(items)} 筆")
            except Exception as e:
                logger.error(f"RSS 收集失敗 {url}: {e}")

        return all_items

    async def _fetch_feed(self, url: str, max_items: int) -> list[IntelItem]:
        """抓取並解析單一 RSS feed"""
        # 先用 httpx 抓取（支援更多 headers / redirect）
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={"User-Agent": "LineBotSummarizer/1.0 RSS Reader"},
            )
            resp.raise_for_status()
            raw_content = resp.text

        # feedparser 是同步的，放到執行緒
        feed = await asyncio.to_thread(feedparser.parse, raw_content)

        if feed.bozo and not feed.entries:
            logger.warning(f"RSS 解析異常 {url}: {feed.bozo_exception}")
            return []

        feed_title = feed.feed.get("title", url)
        items: list[IntelItem] = []

        for entry in feed.entries[:max_items]:
            title = entry.get("title", "").strip()
            link = entry.get("link", "").strip()
            if not title or not link:
                continue

            # 發布時間
            published_at = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    published_at = datetime.fromtimestamp(mktime(entry.published_parsed))
                except (ValueError, OverflowError):
                    pass
            if not published_at and hasattr(entry, "updated_parsed") and entry.updated_parsed:
                try:
                    published_at = datetime.fromtimestamp(mktime(entry.updated_parsed))
                except (ValueError, OverflowError):
                    pass

            # 內容預覽
            content_preview = ""
            if entry.get("summary"):
                content_preview = _strip_html(entry.summary)[:500]
            elif entry.get("content"):
                for c in entry.content:
                    if c.get("value"):
                        content_preview = _strip_html(c["value"])[:500]
                        break

            # 標籤
            tags = []
            for tag in entry.get("tags", []):
                term = tag.get("term", "").strip()
                if term:
                    tags.append(term)

            item = IntelItem(
                title=title,
                url=link,
                source=IntelSource.RSS,
                source_name=feed_title,
                published_at=published_at,
                collected_at=datetime.now(),
                content_preview=content_preview,
                tags=tags[:10],
            )
            item.compute_hash()
            items.append(item)

        return items


def _strip_html(html: str) -> str:
    """簡易移除 HTML 標籤"""
    import re
    text = re.sub(r"<[^>]+>", "", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text
