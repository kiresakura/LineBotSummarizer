"""Google News 關鍵字監控 — 定時搜尋指定關鍵字的最新新聞"""

import asyncio
import logging
import re
from datetime import datetime
from time import mktime
from urllib.parse import quote

import feedparser
import httpx

from app.config import get_settings
from app.collectors.base import BaseCollector
from app.collectors.google_news_url_resolver import resolve_google_news_url
from app.models.intel import IntelItem, IntelSource

logger = logging.getLogger(__name__)


class KeywordMonitor(BaseCollector):
    """從 Google News RSS 搜尋關鍵字收集情報"""

    name = "keyword_monitor"

    async def collect(self) -> list[IntelItem]:
        """遍歷所有設定的關鍵字，從 Google News 收集最新結果"""
        settings = get_settings()
        keywords_str = settings.intel_keywords.strip()
        if not keywords_str:
            logger.warning("未設定監控關鍵字 (INTEL_KEYWORDS)")
            return []

        keywords = [k.strip() for k in keywords_str.split(",") if k.strip()]
        all_items: list[IntelItem] = []

        for keyword in keywords:
            try:
                items = await self._search_keyword(
                    keyword=keyword,
                    lang=settings.intel_keywords_lang,
                    geo=settings.intel_keywords_geo,
                    max_results=settings.intel_keywords_max_results,
                )
                all_items.extend(items)
                logger.info(f"關鍵字監控 [{keyword}]: 收集 {len(items)} 筆")
            except Exception as e:
                logger.warning(f"關鍵字監控 [{keyword}] 失敗: {e}")

        return all_items

    async def _search_keyword(
        self,
        keyword: str,
        lang: str,
        geo: str,
        max_results: int,
    ) -> list[IntelItem]:
        """搜尋單一關鍵字的 Google News RSS"""
        # 組合 Google News RSS URL
        encoded_keyword = quote(keyword)
        # ceid 格式: TW:zh-Hant（地區:語言主標籤）
        lang_main = lang.split("-")[0]
        ceid_lang = "zh-Hant" if lang.startswith("zh") else lang_main
        rss_url = (
            f"https://news.google.com/rss/search"
            f"?q={encoded_keyword}&hl={lang}&gl={geo}&ceid={geo}:{ceid_lang}"
        )

        # 抓取 RSS
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            resp = await client.get(
                rss_url,
                headers={"User-Agent": "LineBotSummarizer/1.0 News Monitor"},
            )
            resp.raise_for_status()
            raw_content = resp.text

        # feedparser 解析
        feed = await asyncio.to_thread(feedparser.parse, raw_content)

        if feed.bozo and not feed.entries:
            logger.warning(f"Google News RSS 解析異常 [{keyword}]: {feed.bozo_exception}")
            return []

        items: list[IntelItem] = []

        for entry in feed.entries[:max_results]:
            title = entry.get("title", "").strip()
            google_link = entry.get("link", "").strip()
            if not title or not google_link:
                continue

            # 解析真實 URL
            # 優先從 entry.source 取得來源資訊
            source_name = ""
            source_href = ""
            if hasattr(entry, "source") and entry.source:
                source_name = entry.source.get("title", "")
                source_href = entry.source.get("href", "")

            # 嘗試解出真實文章 URL
            real_url = source_href or await resolve_google_news_url(google_link)
            if not real_url:
                real_url = google_link

            # 發布時間
            published_at = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    published_at = datetime.fromtimestamp(mktime(entry.published_parsed))
                except (ValueError, OverflowError):
                    pass

            # 內容預覽（Google News RSS summary 是 HTML）
            content_preview = ""
            if entry.get("summary"):
                content_preview = _strip_html(entry.summary)[:500]

            item = IntelItem(
                title=title,
                url=real_url,
                source=IntelSource.GOOGLE_NEWS,
                source_name=source_name or f"Google News: {keyword}",
                published_at=published_at,
                collected_at=datetime.now(),
                content_preview=content_preview,
                tags=[keyword],
            )
            item.compute_hash()
            items.append(item)

        return items


def _strip_html(html: str) -> str:
    """簡易移除 HTML 標籤"""
    text = re.sub(r"<[^>]+>", "", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text
