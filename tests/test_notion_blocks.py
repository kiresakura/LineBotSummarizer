"""Pure Markdown → Notion block conversion. No I/O, so fully deterministic."""

from lorekeeper.adapters.notion_blocks import (
    NOTION_TEXT_LIMIT,
    markdown_to_blocks,
    parse_inline,
    split_rich_text,
)


def test_parse_inline_bold():
    parts = parse_inline("hello **world**")
    assert parts[0]["text"]["content"] == "hello "
    assert parts[-1]["text"]["content"] == "world"
    assert parts[-1]["annotations"]["bold"] is True


def test_parse_inline_link():
    parts = parse_inline("see [docs](https://example.com)")
    link = parts[-1]
    assert link["text"]["content"] == "docs"
    assert link["text"]["link"]["url"] == "https://example.com"


def test_parse_inline_code_and_italic():
    parts = parse_inline("`code` and *em*")
    annotations = [p.get("annotations", {}) for p in parts]
    assert any(a.get("code") for a in annotations)
    assert any(a.get("italic") for a in annotations)


def test_split_rich_text_respects_2000_char_limit():
    long = "a" * (NOTION_TEXT_LIMIT * 2 + 5)
    parts = split_rich_text(long)
    assert len(parts) == 3
    assert all(len(p["text"]["content"]) <= NOTION_TEXT_LIMIT for p in parts)


def test_headings_and_lists():
    blocks = markdown_to_blocks("# Title\n\n- a\n- b\n\n1. one\n2. two")
    types = [b["type"] for b in blocks]
    assert "heading_2" in types  # '#' is demoted to heading_2
    assert types.count("bulleted_list_item") == 2
    assert types.count("numbered_list_item") == 2


def test_code_fence_keeps_language_and_content():
    blocks = markdown_to_blocks("```python\nprint('hi')\n```")
    assert blocks[0]["type"] == "code"
    assert blocks[0]["code"]["language"] == "python"
    assert "print('hi')" in blocks[0]["code"]["rich_text"][0]["text"]["content"]


def test_divider_and_quote():
    types = [b["type"] for b in markdown_to_blocks("---\n> quoted line")]
    assert "divider" in types
    assert "quote" in types


def test_empty_input():
    assert markdown_to_blocks("") == []
