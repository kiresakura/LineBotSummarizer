"""Google News URL 解析器 — 解出重定向 URL 背後的原始文章 URL"""

import asyncio
import logging
import re
from urllib.parse import unquote, urlparse, parse_qs

import httpx

logger = logging.getLogger(__name__)

# 全域限速：每次 resolve 間隔 0.5 秒
_resolve_lock = asyncio.Lock()


async def resolve_google_news_url(google_url: str) -> str:
    """
    解析 Google News 的重定向 URL，取得原始文章 URL。

    策略：
    1. 嘗試從 URL 參數直接提取
    2. 嘗試 HEAD request follow redirect
    3. 失敗則回傳原始 Google News URL
    """
    if not google_url or "news.google.com" not in google_url:
        return google_url

    # 策略 1: 嘗試從 URL 參數提取
    parsed = urlparse(google_url)
    query_params = parse_qs(parsed.query)
    if "url" in query_params:
        return unquote(query_params["url"][0])

    # 嘗試從路徑中提取編碼的 URL
    url_match = re.search(r'(https?://[^\s&]+)', unquote(google_url))
    if url_match and "news.google.com" not in url_match.group(1):
        return url_match.group(1)

    # 策略 2: HEAD request follow redirect
    async with _resolve_lock:
        await asyncio.sleep(0.5)  # 限速
        try:
            async with httpx.AsyncClient(
                timeout=5.0,
                follow_redirects=True,
                max_redirects=5,
            ) as client:
                resp = await client.head(
                    google_url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    },
                )
                final_url = str(resp.url)
                if "news.google.com" not in final_url:
                    return final_url
        except Exception as e:
            logger.debug(f"Google News URL resolve 失敗: {e}")

    # 策略 3: 回傳原始 URL
    return google_url
