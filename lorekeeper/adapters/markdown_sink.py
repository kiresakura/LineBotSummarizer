"""Markdown sink — writes each `KnowledgeEntry` as a standalone Markdown file.

Needs no external service or credentials, so it's the path that lets anyone run
the project end-to-end locally. Output uses YAML front-matter, making it
drop-in compatible with Obsidian / any Markdown knowledge base.
"""

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path

from lorekeeper.models import KnowledgeEntry

logger = logging.getLogger(__name__)


class MarkdownSink:
    name = "markdown"

    def __init__(self, output_dir: str = "./knowledge"):
        self.output_dir = Path(output_dir)

    async def write(self, entry: KnowledgeEntry) -> None:
        path = self._path_for(entry)
        # file I/O off the event loop
        await asyncio.to_thread(self._write_file, path, self.render(entry))
        logger.info(f"已寫入 {path}")

    def _write_file(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _path_for(self, entry: KnowledgeEntry) -> Path:
        ts = (
            entry.source_messages[0].timestamp
            if entry.source_messages
            else datetime.now()
        )
        slug = re.sub(r"[^\w\-]+", "-", entry.title or "entry").strip("-")[:50]
        return self.output_dir / f"{ts:%Y%m%d-%H%M%S}-{slug or 'entry'}.md"

    @staticmethod
    def render(entry: KnowledgeEntry) -> str:
        title = (entry.title or "未命名").replace('"', "'")
        out: list[str] = ["---"]
        out.append(f'title: "{title}"')
        out.append(f"category: {entry.category}")
        out.append(f"importance: {entry.importance.value}")
        out.append(f"tags: [{', '.join(entry.tags)}]")
        if entry.source_messages:
            out.append(f"date: {entry.source_messages[0].timestamp.isoformat()}")
        out.append(f'source: "{entry.conversation_label}"')
        out.append("---\n")

        out.append(f"# {title}\n")
        out.append("## 📚 知識點整理\n")
        out.append(entry.knowledge.strip() + "\n")

        if entry.media_descriptions:
            out.append("## 🖼 媒體內容提取\n")
            for idx, desc in enumerate(entry.media_descriptions, 1):
                out.append(f"### 媒體 {idx}\n\n{desc.strip()}\n")

        if entry.action_items:
            out.append("## ✅ 待辦事項\n")
            out.extend(f"- [ ] {item}" for item in entry.action_items)
            out.append("")

        if entry.urls:
            out.append("## 🔗 相關連結\n")
            out.extend(f"- {url}" for url in entry.urls)
            out.append("")

        if entry.source_messages:
            out.append("## 💬 原始訊息\n")
            for msg in entry.source_messages:
                time_str = msg.timestamp.strftime("%H:%M")
                sender = msg.sender_name or msg.sender_id[:8]
                body = msg.text or f"[{msg.type.value}]"
                out.append(f"> [{time_str}] {sender}: {body}")

        return "\n".join(out) + "\n"
