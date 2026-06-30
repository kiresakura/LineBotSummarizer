"""JSONL sink — append behaviour and serialization."""

import json
from datetime import datetime

from lorekeeper.adapters.jsonl_sink import JsonlSink
from lorekeeper.models import (
    Importance,
    InboundMessage,
    KnowledgeEntry,
    MessageType,
)


def _entry() -> KnowledgeEntry:
    msg = InboundMessage(
        id="1",
        conversation_id="g",
        sender_id="u",
        type=MessageType.TEXT,
        text="hi",
        timestamp=datetime(2026, 1, 1, 9, 0),
    )
    return KnowledgeEntry(
        category="工具推薦",
        importance=Importance.LOW,
        title="Tool",
        knowledge="k",
        tags=["a"],
        source_messages=[msg],
        conversation_label="g",
    )


async def test_appends_one_line_per_entry(tmp_path):
    path = tmp_path / "out.jsonl"
    sink = JsonlSink(str(path))
    await sink.write(_entry())
    await sink.write(_entry())

    lines = path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2


async def test_line_is_valid_json_without_source_messages(tmp_path):
    path = tmp_path / "out.jsonl"
    await JsonlSink(str(path)).write(_entry())

    obj = json.loads(path.read_text(encoding="utf-8").strip())
    assert obj["category"] == "工具推薦"
    assert obj["title"] == "Tool"
    # source_messages is excluded (may carry binary media)
    assert "source_messages" not in obj
