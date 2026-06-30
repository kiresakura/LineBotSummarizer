"""Markdown sink — rendering and file output."""

from datetime import datetime

from lorekeeper.adapters.markdown_sink import MarkdownSink
from lorekeeper.models import (
    Importance,
    InboundMessage,
    KnowledgeEntry,
    MessageType,
)


def _entry() -> KnowledgeEntry:
    msg = InboundMessage(
        id="1",
        conversation_id="grp",
        sender_id="u",
        sender_name="Alice",
        type=MessageType.TEXT,
        text="hi",
        timestamp=datetime(2026, 1, 1, 9, 0),
    )
    return KnowledgeEntry(
        category="技術分享",
        importance=Importance.MEDIUM,
        title="Test Title",
        knowledge="## H\nbody text",
        tags=["a", "b"],
        action_items=["do x"],
        source_messages=[msg],
        conversation_label="grp",
        urls=["https://example.com"],
    )


def test_render_has_frontmatter_and_sections():
    md = MarkdownSink.render(_entry())
    assert md.startswith("---")
    assert 'title: "Test Title"' in md
    assert "category: 技術分享" in md
    assert "## 📚 知識點整理" in md
    assert "- [ ] do x" in md
    assert "https://example.com" in md
    assert "Alice" in md


async def test_write_creates_one_file(tmp_path):
    sink = MarkdownSink(str(tmp_path))
    await sink.write(_entry())
    files = list(tmp_path.glob("*.md"))
    assert len(files) == 1
    assert "Test Title" in files[0].read_text(encoding="utf-8")
