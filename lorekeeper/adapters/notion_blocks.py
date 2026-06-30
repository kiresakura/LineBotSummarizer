"""Pure Markdown → Notion block conversion.

No I/O and no SDK — just data transforms, which makes this the most heavily
unit-tested module in the project. `NotionSink` consumes these helpers.

Supports inline **bold**, *italic*, `code`, [links](url); and block-level
headings, bullet/numbered lists, quotes, code fences, and dividers. Respects
Notion's 2000-char rich-text limit by splitting long runs.
"""

import re

# Notion rich_text 單個區塊上限 2000 字元
NOTION_TEXT_LIMIT = 2000

_INLINE_PATTERN = re.compile(
    r"\*\*(.+?)\*\*"  # 1: bold
    r"|`(.+?)`"  # 2: inline code
    r"|\[([^\]]+)\]\(([^)]+)\)"  # 3,4: link text, url
    r"|\*(.+?)\*"  # 5: italic
)


def parse_inline(text: str) -> list[dict]:
    """解析行內 Markdown，轉成 Notion rich_text 陣列。"""
    if not text:
        return [{"text": {"content": ""}}]

    parts: list[dict] = []
    last_end = 0
    for m in _INLINE_PATTERN.finditer(text):
        if m.start() > last_end:
            _append_text(parts, text[last_end : m.start()])

        if m.group(1) is not None:
            parts.append(
                {"text": {"content": m.group(1)}, "annotations": {"bold": True}}
            )
        elif m.group(2) is not None:
            parts.append(
                {"text": {"content": m.group(2)}, "annotations": {"code": True}}
            )
        elif m.group(3) is not None:
            parts.append({"text": {"content": m.group(3), "link": {"url": m.group(4)}}})
        elif m.group(5) is not None:
            parts.append(
                {"text": {"content": m.group(5)}, "annotations": {"italic": True}}
            )

        last_end = m.end()

    if last_end < len(text):
        _append_text(parts, text[last_end:])

    return parts if parts else [{"text": {"content": ""}}]


def _append_text(parts: list[dict], text: str) -> None:
    for i in range(0, len(text), NOTION_TEXT_LIMIT):
        parts.append({"text": {"content": text[i : i + NOTION_TEXT_LIMIT]}})


def split_rich_text(text: str) -> list[dict]:
    """將長純文字拆成多個 rich_text 區塊（不含 Markdown 解析）。"""
    if not text:
        return [{"text": {"content": ""}}]
    parts = []
    for i in range(0, len(text), NOTION_TEXT_LIMIT):
        parts.append({"text": {"content": text[i : i + NOTION_TEXT_LIMIT]}})
    return parts


def markdown_to_blocks(text: str) -> list[dict]:
    """將 Markdown 文字轉為 Notion block 陣列。"""
    if not text:
        return []

    lines = text.split("\n")
    blocks: list[dict] = []
    i = 0

    while i < len(lines):
        line = lines[i]

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
            code_text = "\n".join(code_lines)[:NOTION_TEXT_LIMIT]
            blocks.append(
                {
                    "object": "block",
                    "type": "code",
                    "code": {
                        "rich_text": [{"text": {"content": code_text}}],
                        "language": lang or "plain text",
                    },
                }
            )
            continue

        # 標題 # / ## / ###
        heading_match = re.match(r"^(#{1,3})\s+(.+)$", line)
        if heading_match:
            level = len(heading_match.group(1))
            notion_level = min(level + 1, 3)  # 用 heading_2/3 避免跟頁面結構衝突
            htype = f"heading_{notion_level}"
            blocks.append(
                {
                    "object": "block",
                    "type": htype,
                    htype: {"rich_text": parse_inline(heading_match.group(2).strip())},
                }
            )
            i += 1
            continue

        # 分隔線
        if re.match(r"^-{3,}$", line.strip()) or re.match(r"^\*{3,}$", line.strip()):
            blocks.append({"object": "block", "type": "divider", "divider": {}})
            i += 1
            continue

        # 無序列表
        if re.match(r"^(\s*)[-*]\s+(.+)$", line):
            items, i = _collect_list_items(lines, i, r"^(\s*)[-*]\s+(.+)$")
            blocks.extend(_build_list_blocks("bulleted_list_item", items))
            continue

        # 有序列表
        if re.match(r"^(\s*)\d+\.\s+(.+)$", line):
            items, i = _collect_list_items(lines, i, r"^(\s*)\d+\.\s+(.+)$")
            blocks.extend(_build_list_blocks("numbered_list_item", items))
            continue

        # 引用
        if line.startswith(">"):
            quote_lines = []
            while i < len(lines) and lines[i].startswith(">"):
                quote_lines.append(lines[i].lstrip("> "))
                i += 1
            blocks.append(
                {
                    "object": "block",
                    "type": "quote",
                    "quote": {"rich_text": parse_inline("\n".join(quote_lines))},
                }
            )
            continue

        # 一般段落
        para_lines = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not _is_block_start(lines[i]):
            para_lines.append(lines[i])
            i += 1
        blocks.append(
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": parse_inline("\n".join(para_lines))},
            }
        )

    return blocks


def _is_block_start(line: str) -> bool:
    if not line.strip():
        return True
    return bool(
        re.match(r"^#{1,3}\s+", line)
        or re.match(r"^[-*]\s+", line)
        or re.match(r"^\d+\.\s+", line)
        or line.startswith(">")
        or line.strip().startswith("```")
        or re.match(r"^-{3,}$", line.strip())
    )


def _collect_list_items(
    lines: list[str], start: int, pattern: str
) -> tuple[list[str], int]:
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
    return [
        {
            "object": "block",
            "type": block_type,
            block_type: {"rich_text": parse_inline(item)},
        }
        for item in items
    ]
