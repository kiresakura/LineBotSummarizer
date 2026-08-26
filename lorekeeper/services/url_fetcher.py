"""URL 內容爬取 — yt-dlp 影片提取 + BeautifulSoup 一般網頁。

對外請求一律走 `safe_http.safe_get`（SSRF 防護 + 大小限制）。yt-dlp 路徑則以
VIDEO_SITE_PATTERN 域名白名單作為控制（只對已知影片站點啟用）。
"""

import asyncio
import json
import logging
import re

from bs4 import BeautifulSoup

from lorekeeper.models import UrlContent
from lorekeeper.services.safe_http import UnsafeURLError, safe_get

logger = logging.getLogger(__name__)

MAX_WEBPAGE_BYTES = 5 * 1024 * 1024  # 一般網頁上限 5 MB
MAX_SUBTITLE_BYTES = 5 * 1024 * 1024  # 字幕上限 5 MB

# yt-dlp 支援的影片網站
VIDEO_SITE_PATTERN = re.compile(
    r"(?:youtube\.com|youtu\.be|bilibili\.com/video|"
    r"twitter\.com/\S+/status|x\.com/\S+/status|"
    r"tiktok\.com|vimeo\.com|dailymotion\.com|"
    r"twitch\.tv/videos|nicovideo\.jp)",
    re.IGNORECASE,
)

SUBTITLE_LANG_PRIORITY = ["zh-TW", "zh-Hant", "zh", "zh-Hans", "en"]


async def fetch_url_content(url: str) -> UrlContent | None:
    """爬取 URL 內容，回傳 UrlContent。"""
    try:
        if VIDEO_SITE_PATTERN.search(url):
            result = await _fetch_video(url)
            if result:
                return result
            logger.info(f"yt-dlp 未能處理，退回網頁爬取: {url}")

        return await _fetch_webpage(url)
    except Exception:
        logger.exception(f"URL 爬取失敗 {url}")
        return None


# === 影片提取（yt-dlp） ===


async def _fetch_video(url: str) -> UrlContent | None:
    """使用 yt-dlp 提取影片資訊 + 字幕。"""
    import yt_dlp

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "ignoreerrors": True,
        "socket_timeout": 15,
        "extractor_retries": 2,
    }

    def extract():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)

    try:
        loop = asyncio.get_event_loop()
        info = await loop.run_in_executor(None, extract)
    except Exception as e:
        logger.warning(f"yt-dlp 提取失敗 {url}: {e}", exc_info=True)
        return None

    if not info:
        return None

    title = info.get("title", "")
    description = info.get("description", "")
    uploader = info.get("uploader", "") or info.get("channel", "")
    duration = info.get("duration_string", "")
    tags = info.get("tags") or []

    transcript = await _extract_subtitles(info)

    parts = []
    if title:
        parts.append(f"影片標題：{title}")
    if uploader:
        parts.append(f"頻道/上傳者：{uploader}")
    if duration:
        parts.append(f"影片長度：{duration}")
    if description:
        parts.append(f"影片描述：{description[:1000]}")
    if transcript:
        parts.append(f"影片逐字稿：\n{transcript[:8000]}")
    else:
        parts.append("（無法取得字幕，僅根據標題和描述分析）")
    if tags:
        parts.append(f"影片標籤：{', '.join(str(t) for t in tags[:10])}")

    if not any([title, description, transcript]):
        return None

    return UrlContent(url=url, title=title or url, content="\n\n".join(parts))


async def _extract_subtitles(info: dict) -> str:
    """從 yt-dlp 影片資訊中提取最適合的字幕。"""
    for sub_key in ["subtitles", "automatic_captions"]:
        subs = info.get(sub_key, {})
        if not subs:
            continue
        sub_url = _find_best_subtitle_url(subs)
        if sub_url:
            text = await _download_subtitle(sub_url)
            if text:
                return text
    return ""


def _find_best_subtitle_url(subs: dict) -> str | None:
    """按語言優先級 + 格式優先級找到最佳字幕 URL。"""
    candidates = list(SUBTITLE_LANG_PRIORITY)
    for lang_key in subs:
        if lang_key not in candidates:
            candidates.append(lang_key)

    for lang in candidates:
        if lang not in subs:
            continue
        formats = subs[lang]
        if not formats:
            continue
        for fmt_pref in ["json3", "vtt", "srv1"]:
            for fmt in formats:
                if fmt.get("ext") == fmt_pref and fmt.get("url"):
                    return fmt["url"]
        for fmt in formats:
            if fmt.get("url"):
                return fmt["url"]
    return None


async def _download_subtitle(url: str) -> str:
    """下載並解析字幕內容（支援 JSON3 / VTT / SRT）。"""
    try:
        resp = await safe_get(url, max_bytes=MAX_SUBTITLE_BYTES, timeout=15.0)
        content = resp.text

        try:
            data = json.loads(content)
            if "events" in data:
                texts = []
                for event in data["events"]:
                    for seg in event.get("segs", []):
                        text = seg.get("utf8", "").strip()
                        if text and text != "\n":
                            texts.append(text)
                return " ".join(texts)
        except (json.JSONDecodeError, KeyError):
            pass

        lines = content.split("\n")
        text_lines = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith(("WEBVTT", "NOTE")):
                continue
            if "-->" in line:
                continue
            if re.match(r"^\d+$", line):
                continue
            line = re.sub(r"<[^>]+>", "", line)
            if line:
                text_lines.append(line)
        return " ".join(text_lines)

    except UnsafeURLError as e:
        logger.warning(f"字幕 URL 被安全檢查拒絕: {e}")
        return ""
    except Exception as e:
        logger.debug(f"字幕下載失敗: {e}", exc_info=True)
        return ""


# === 一般網頁 ===


async def _fetch_webpage(url: str) -> UrlContent | None:
    """爬取一般網頁內容（適用所有網站）。"""
    try:
        response = await safe_get(
            url,
            max_bytes=MAX_WEBPAGE_BYTES,
            timeout=15.0,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
            },
        )
    except UnsafeURLError as e:
        logger.warning(f"拒絕不安全的 URL {url}: {e}")
        return None

    soup = BeautifulSoup(response.content, "html.parser")

    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    title = soup.title.string.strip() if soup.title and soup.title.string else ""

    meta_desc = ""
    meta_tag = soup.find("meta", attrs={"name": "description"}) or soup.find(
        "meta", attrs={"property": "og:description"}
    )
    if meta_tag:
        meta_desc = meta_tag.get("content", "")

    article = soup.find("article") or soup.find("main") or soup.body
    if not article:
        return None

    text = article.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)[:5000]

    if len(text) < 30 and not meta_desc:
        return None

    parts = []
    if title:
        parts.append(f"網頁標題：{title}")
    if meta_desc:
        parts.append(f"網頁描述：{meta_desc}")
    if text:
        parts.append(f"網頁內容：\n{text}")

    return UrlContent(url=url, title=title or url, content="\n\n".join(parts))
