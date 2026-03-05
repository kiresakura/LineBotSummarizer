"""URL 內容爬取服務 — 支援 YouTube 字幕 + 一般網頁"""

import re
import logging
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

YOUTUBE_PATTERN = re.compile(
    r'(?:youtube\.com/watch\?v=|youtu\.be/)([\w-]+)', re.IGNORECASE
)


async def fetch_url_content(url: str) -> dict | None:
    """爬取 URL 內容，回傳 {"url", "title", "content"}"""
    try:
        yt_match = YOUTUBE_PATTERN.search(url)
        if yt_match:
            video_id = yt_match.group(1)
            return await _fetch_youtube(video_id, url)
        else:
            return await _fetch_webpage(url)
    except Exception as e:
        logger.error(f"URL 爬取失敗 {url}: {e}")
        return None


async def _fetch_youtube(video_id: str, url: str) -> dict | None:
    """抓取 YouTube 影片標題 + 字幕"""
    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1. 抓影片頁面取得標題和描述
        response = await client.get(
            f"https://www.youtube.com/watch?v={video_id}",
            headers={"Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8"},
        )
        response.raise_for_status()
        html = response.text

        # 提取標題
        title = ""
        title_match = re.search(r'<title>(.*?)</title>', html)
        if title_match:
            title = title_match.group(1).replace(" - YouTube", "").strip()

        # 提取描述
        description = ""
        desc_match = re.search(r'"shortDescription":"(.*?)"', html)
        if desc_match:
            description = desc_match.group(1).replace("\\n", "\n")[:2000]

        # 2. 嘗試抓取字幕
        transcript = await _fetch_youtube_transcript(video_id, client)

        content_parts = []
        if title:
            content_parts.append(f"影片標題：{title}")
        if description:
            content_parts.append(f"影片描述：{description[:500]}")
        if transcript:
            content_parts.append(f"影片逐字稿：\n{transcript[:5000]}")
        else:
            content_parts.append("（無法取得字幕，僅根據標題和描述分析）")

        if not content_parts:
            return None

        return {
            "url": url,
            "title": title or f"YouTube 影片 {video_id}",
            "content": "\n\n".join(content_parts),
        }


async def _fetch_youtube_transcript(video_id: str, client: httpx.AsyncClient) -> str:
    """嘗試從 YouTube 抓取字幕"""
    try:
        # 透過 YouTube 內部 API 取得字幕列表
        page = await client.get(f"https://www.youtube.com/watch?v={video_id}")
        html = page.text

        # 找到字幕 URL
        caption_match = re.search(r'"captionTracks":\[(.*?)\]', html)
        if not caption_match:
            return ""

        # 優先找中文字幕，否則找英文
        tracks_str = caption_match.group(1)
        caption_url = ""
        for lang in ["zh-TW", "zh-Hant", "zh", "zh-Hans", "en"]:
            lang_match = re.search(
                r'"baseUrl":"(.*?)".*?"languageCode":"' + lang + '"', tracks_str
            )
            if lang_match:
                caption_url = lang_match.group(1).replace("\\u0026", "&")
                break

        if not caption_url:
            # 用第一個可用的字幕
            first_match = re.search(r'"baseUrl":"(.*?)"', tracks_str)
            if first_match:
                caption_url = first_match.group(1).replace("\\u0026", "&")

        if not caption_url:
            return ""

        # 下載字幕 XML
        resp = await client.get(caption_url)
        resp.raise_for_status()

        # 解析字幕文字
        soup = BeautifulSoup(resp.text, "html.parser")
        texts = [tag.get_text() for tag in soup.find_all("text")]
        return " ".join(texts)

    except Exception as e:
        logger.debug(f"YouTube 字幕抓取失敗 {video_id}: {e}")
        return ""


async def _fetch_webpage(url: str) -> dict | None:
    """爬取一般網頁內容"""
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        response = await client.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
            },
        )
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        # 移除無用元素
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()

        title = soup.title.string.strip() if soup.title and soup.title.string else ""

        # 提取主要內容
        article = soup.find("article") or soup.find("main") or soup.body
        if not article:
            return None

        text = article.get_text(separator="\n", strip=True)
        # 清理多餘空行
        text = re.sub(r'\n{3,}', '\n\n', text)[:5000]

        if len(text) < 50:
            return None

        return {
            "url": url,
            "title": title,
            "content": f"網頁標題：{title}\n\n{text}",
        }
