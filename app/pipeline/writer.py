"""Stage 4: Notion 寫入器 — 含限流 & 重試機制 & Markdown 轉換"""

import asyncio
import logging
import re
import time
from app.config import get_settings
from app.models.message import ClassifiedMessage

logger = logging.getLogger(__name__)

# Notion rich_text 單個區塊上限 2000 字元
NOTION_TEXT_LIMIT = 2000


# ---------------------------------------------------------------------------
# Markdown → Notion rich_text（行內格式）
# ---------------------------------------------------------------------------

def _parse_inline(text: str) -> list[dict]:
    """
    解析行內 Markdown 格式，轉成 Notion rich_text 陣列。
    支援：**粗體**、*斜體*、`行內程式碼`、[連結](url)
    """
    if not text:
        return [{"text": {"content": ""}}]

    parts: list[dict] = []
    # 模式優先級：粗體 > 行內程式碼 > 連結 > 斜體
    pattern = re.compile(
        r'\*\*(.+?)\*\*'        # group 1: bold
        r'|`(.+?)`'             # group 2: inline code
        r'|\[([^\]]+)\]\(([^)]+)\)'  # group 3,4: link text, url
        r'|\*(.+?)\*'           # group 5: italic
    )

    last_end = 0
    for m in pattern.finditer(text):
        # 前面的純文字
        if m.start() > last_end:
            _append_text(parts, text[last_end:m.start()])

        if m.group(1) is not None:  # **bold**
            parts.append({
                "text": {"content": m.group(1)},
                "annotations": {"bold": True},
            })
        elif m.group(2) is not None:  # `code`
            parts.append({
                "text": {"content": m.group(2)},
                "annotations": {"code": True},
            })
        elif m.group(3) is not None:  # [text](url)
            parts.append({
                "text": {"content": m.group(3), "link": {"url": m.group(4)}},
            })
        elif m.group(5) is not None:  # *italic*
            parts.append({
                "text": {"content": m.group(5)},
                "annotations": {"italic": True},
            })

        last_end = m.end()

    # 剩餘純文字
    if last_end < len(text):
        _append_text(parts, text[last_end:])

    return parts if parts else [{"text": {"content": ""}}]


def _append_text(parts: list[dict], text: str):
    """將純文字加入 parts，自動處理 2000 字元拆分"""
    for i in range(0, len(text), NOTION_TEXT_LIMIT):
        parts.append({"text": {"content": text[i:i + NOTION_TEXT_LIMIT]}})


# ---------------------------------------------------------------------------
# Markdown → Notion blocks（區塊級格式）
# ---------------------------------------------------------------------------

def _markdown_to_blocks(text: str) -> list[dict]:
    """
    將 Markdown 文字轉為 Notion block 陣列。
    支援：標題(#)、無序列表(- /*)、有序列表(1.)、引用(>)、
          程式碼區塊(```)、分隔線(---)、一般段落
    """
    if not text:
        return []

    lines = text.split("\n")
    blocks: list[dict] = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # 空行跳過
        if not line.strip():
            i += 1
            continue

        # 程式碼區塊 ```
        if line.strip().startswith("```"):
            lang = line.strip().removeprefix("```").strip()
            code_lines = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # 跳過結尾 ```
            code_text = "\n".join(code_lines)
            if len(code_text) > NOTION_TEXT_LIMIT:
                code_text = code_text[:NOTION_TEXT_LIMIT]
            blocks.append({
                "object": "block",
                "type": "code",
                "code": {
                    "rich_text": [{"text": {"content": code_text}}],
                    "language": lang or "plain text",
                }
            })
            continue

        # 標題 ### / ## / #
        heading_match = re.match(r'^(#{1,3})\s+(.+)$', line)
        if heading_match:
            level = len(heading_match.group(1))
            heading_text = heading_match.group(2).strip()
            # Notion 只支援 heading_1/2/3，AI 產生的內容用 heading_3 避免跟頁面結構衝突
            notion_level = min(level + 1, 3)
            htype = f"heading_{notion_level}"
            blocks.append({
                "object": "block",
                "type": htype,
                htype: {"rich_text": _parse_inline(heading_text)},
            })
            i += 1
            continue

        # 分隔線
        if re.match(r'^-{3,}$', line.strip()) or re.match(r'^\*{3,}$', line.strip()):
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            i += 1
            continue

        # 無序列表 - 或 *（需要空格跟隨）
        ul_match = re.match(r'^(\s*)[-*]\s+(.+)$', line)
        if ul_match:
            items, i = _collect_list_items(lines, i, r'^(\s*)[-*]\s+(.+)$')
            blocks.extend(_build_list_blocks("bulleted_list_item", items))
            continue

        # 有序列表 1. 2. ...
        ol_match = re.match(r'^(\s*)\d+\.\s+(.+)$', line)
        if ol_match:
            items, i = _collect_list_items(lines, i, r'^(\s*)\d+\.\s+(.+)$')
            blocks.extend(_build_list_blocks("numbered_list_item", items))
            continue

        # 引用 >
        if line.startswith(">"):
            quote_lines = []
            while i < len(lines) and lines[i].startswith(">"):
                quote_lines.append(lines[i].lstrip("> "))
                i += 1
            quote_text = "\n".join(quote_lines)
            blocks.append({
                "object": "block",
                "type": "quote",
                "quote": {"rich_text": _parse_inline(quote_text)},
            })
            continue

        # 一般段落
        para_lines = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not _is_block_start(lines[i]):
            para_lines.append(lines[i])
            i += 1
        para_text = "\n".join(para_lines)
        blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": _parse_inline(para_text)},
        })

    return blocks


def _is_block_start(line: str) -> bool:
    """判斷一行是否是新的區塊級元素的開頭"""
    if not line.strip():
        return True
    if re.match(r'^#{1,3}\s+', line):
        return True
    if re.match(r'^[-*]\s+', line):
        return True
    if re.match(r'^\d+\.\s+', line):
        return True
    if line.startswith(">"):
        return True
    if line.strip().startswith("```"):
        return True
    if re.match(r'^-{3,}$', line.strip()):
        return True
    return False


def _collect_list_items(lines: list[str], start: int, pattern: str) -> tuple[list[str], int]:
    """收集連續的列表項目"""
    items = []
    i = start
    while i < len(lines):
        m = re.match(pattern, lines[i])
        if m:
            items.append(m.group(2))
            i += 1
        else:
            break
    return items, i


def _build_list_blocks(block_type: str, items: list[str]) -> list[dict]:
    """將列表項目轉為 Notion block"""
    blocks = []
    for item in items:
        blocks.append({
            "object": "block",
            "type": block_type,
            block_type: {"rich_text": _parse_inline(item)},
        })
    return blocks


# ---------------------------------------------------------------------------
# 簡易 rich_text 拆分（用於不含 Markdown 的純文字）
# ---------------------------------------------------------------------------

def _split_rich_text(text: str) -> list[dict]:
    """將長純文字拆成多個 rich_text 區塊"""
    if not text:
        return [{"text": {"content": ""}}]
    parts = []
    for i in range(0, len(text), NOTION_TEXT_LIMIT):
        parts.append({"text": {"content": text[i:i + NOTION_TEXT_LIMIT]}})
    return parts


# ---------------------------------------------------------------------------
# Rate Limiter
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Notion Writer
# ---------------------------------------------------------------------------

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

        # 清除 properties 中的 markdown 符號
        clean_summary = re.sub(r'[#*`>\-]', '', classified.summary)[:2000].strip()

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
                "rich_text": _split_rich_text(clean_summary)
            },
            "Has Action Items": {
                "checkbox": len(classified.action_items) > 0
            },
        }

        if classified.urls_found:
            properties["URLs"] = {"url": classified.urls_found[0]}

        return properties

    def _build_content_blocks(self, classified: ClassifiedMessage) -> list:
        """構建 Notion Page 內容區塊 — Markdown 轉為原生 Notion 格式"""
        blocks = []

        # === 知識點整理區（Markdown → Notion blocks）===
        blocks.append({
            "object": "block",
            "type": "heading_2",
            "heading_2": {
                "rich_text": [{"text": {"content": "📚 知識點整理"}}]
            }
        })
        blocks.extend(_markdown_to_blocks(classified.summary))

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
                blocks.extend(_markdown_to_blocks(desc))

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
                        "rich_text": _parse_inline(item),
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

        # === 原始訊息（完整保留）===
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
