"""URL 內容爬取服務 — 支援 YouTube / BiliBili 字幕 + 一般網頁"""

import re
import json
import logging
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

YOUTUBE_PATTERN = re.compile(
    r'(?:youtube\.com/watch\?v=|youtu\.be/)([\w-]+)', re.IGNORECASE
)
BILIBILI_PATTERN = re.compile(
    r'bilibili\.com/video/(BV[\w]+)', re.IGNORECASE
)


async def fetch_url_content(url: str) -> dict | None:
    """爬取 URL 內容，回傳 {"url", "title", "content"}"""
    try:
        yt_match = YOUTUBE_PATTERN.search(url)
        if yt_match:
            return await _fetch_youtube(yt_match.group(1), url)

        bili_match = BILIBILI_PATTERN.search(url)
        if bili_match:
            return await _fetch_bilibili(bili_match.group(1), url)

        return await _fetch_webpage(url)
    except Exception as e:
        logger.error(f"URL 爬取失敗 {url}: {e}")
        return None


# === YouTube ===

async def _fetch_youtube(video_id: str, url: str) -> dict | None:
    """抓取 YouTube 影片標題 + 字幕"""
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(
            f"https://www.youtube.com/watch?v={video_id}",
            headers={"Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8"},
        )
        response.raise_for_status()
        html = response.text

        title = ""
        title_match = re.search(r'<title>(.*?)</title>', html)
        if title_match:
            title = title_match.group(1).replace(" - YouTube", "").strip()

        description = ""
        desc_match = re.search(r'"shortDescription":"(.*?)"', html)
        if desc_match:
            description = desc_match.group(1).replace("\\n", "\n")[:2000]

        transcript = await _fetch_youtube_transcript(html, client)

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


async def _fetch_youtube_transcript(html: str, client: httpx.AsyncClient) -> str:
    """從已抓取的 YouTube 頁面提取字幕"""
    try:
        caption_match = re.search(r'"captionTracks":\[(.*?)\]', html)
        if not caption_match:
            return ""

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
            first_match = re.search(r'"baseUrl":"(.*?)"', tracks_str)
            if first_match:
                caption_url = first_match.group(1).replace("\\u0026", "&")

        if not caption_url:
            return ""

        resp = await client.get(caption_url)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        texts = [tag.get_text() for tag in soup.find_all("text")]
        return " ".join(texts)

    except Exception as e:
        logger.debug(f"YouTube 字幕抓取失敗: {e}")
        return ""


# === BiliBili ===

async def _fetch_bilibili(bvid: str, url: str) -> dict | None:
    """抓取 BiliBili 影片標題、描述 + 字幕"""
    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1. 取得影片資訊
        info_resp = await client.get(
            f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}",
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://www.bilibili.com/",
            },
        )
        info_resp.raise_for_status()
        info = info_resp.json()

        if info.get("code") != 0:
            return await _fetch_webpage(url)

        data = info.get("data", {})
        title = data.get("title", "")
        description = data.get("desc", "")
        cid = data.get("cid", 0)
        aid = data.get("aid", 0)

        # 2. 嘗試抓取字幕
        transcript = ""
        if cid and aid:
            transcript = await _fetch_bilibili_subtitle(aid, cid, client)

        content_parts = []
        if title:
            content_parts.append(f"影片標題：{title}")
        if description:
            content_parts.append(f"影片描述：{description[:500]}")
        if transcript:
            content_parts.append(f"影片逐字稿：\n{transcript[:5000]}")
        else:
            content_parts.append("（無法取得字幕，僅根據標題和描述分析）")

        # 補充標籤
        tags_resp = await client.get(
            f"https://api.bilibili.com/x/tag/archive/tags?bvid={bvid}",
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"},
        )
        if tags_resp.status_code == 200:
            tags_data = tags_resp.json().get("data", [])
            if tags_data:
                tag_names = [t.get("tag_name", "") for t in tags_data[:10]]
                content_parts.append(f"影片標籤：{', '.join(tag_names)}")

        if not content_parts:
            return None

        return {
            "url": url,
            "title": title or f"BiliBili 影片 {bvid}",
            "content": "\n\n".join(content_parts),
        }


async def _fetch_bilibili_subtitle(aid: int, cid: int, client: httpx.AsyncClient) -> str:
    """抓取 BiliBili 字幕"""
    try:
        resp = await client.get(
            f"https://api.bilibili.com/x/player/v2?aid={aid}&cid={cid}",
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"},
        )
        resp.raise_for_status()
        data = resp.json()

        subtitles = data.get("data", {}).get("subtitle", {}).get("subtitles", [])
        if not subtitles:
            return ""

        # 優先中文字幕
        sub_url = ""
        for sub in subtitles:
            lang = sub.get("lan", "")
            if "zh" in lang:
                sub_url = sub.get("subtitle_url", "")
                break
        if not sub_url and subtitles:
            sub_url = subtitles[0].get("subtitle_url", "")

        if not sub_url:
            return ""

        if sub_url.startswith("//"):
            sub_url = "https:" + sub_url

        sub_resp = await client.get(sub_url)
        sub_resp.raise_for_status()
        sub_data = sub_resp.json()

        texts = [item.get("content", "") for item in sub_data.get("body", [])]
        return " ".join(texts)

    except Exception as e:
        logger.debug(f"BiliBili 字幕抓取失敗: {e}")
        return ""


# === 一般網頁 ===

async def _fetch_webpage(url: str) -> dict | None:
    """爬取一般網頁內容（適用所有網站）"""
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

        # 嘗試提取 meta description
        meta_desc = ""
        meta_tag = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
        if meta_tag:
            meta_desc = meta_tag.get("content", "")

        # 提取主要內容
        article = soup.find("article") or soup.find("main") or soup.body
        if not article:
            return None

        text = article.get_text(separator="\n", strip=True)
        text = re.sub(r'\n{3,}', '\n\n', text)[:5000]

        if len(text) < 30 and not meta_desc:
            return None

        content_parts = []
        if title:
            content_parts.append(f"網頁標題：{title}")
        if meta_desc:
            content_parts.append(f"網頁描述：{meta_desc}")
        if text:
            content_parts.append(f"網頁內容：\n{text}")

        return {
            "url": url,
            "title": title or url,
            "content": "\n\n".join(content_parts),
        }
