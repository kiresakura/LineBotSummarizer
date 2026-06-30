"""JSONL sink — append each `KnowledgeEntry` as one machine-readable JSON line.

Useful for piping the structured output into data tooling / analysis. Like the
Markdown sink it needs no external service. `source_messages` is excluded because
it may carry binary media bytes (not JSON-serializable as text).
"""

import asyncio
from pathlib import Path

from lorekeeper.models import KnowledgeEntry


class JsonlSink:
    name = "jsonl"

    def __init__(self, path: str = "./knowledge.jsonl"):
        self.path = Path(path)

    async def write(self, entry: KnowledgeEntry) -> None:
        line = entry.model_dump_json(exclude={"source_messages"})
        await asyncio.to_thread(self._append, line)

    def _append(self, line: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
