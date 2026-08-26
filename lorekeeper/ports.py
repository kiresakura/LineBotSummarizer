"""Ports — the interfaces the core pipeline depends on (hexagonal architecture).

These Protocols are deliberately framework-free (no FastAPI, no httpx, no vendor
SDKs). Concrete adapters in `lorekeeper.adapters` implement them; the pipeline
imports *only* this module, never a concrete adapter. That inversion is what
makes sources/sinks/LLMs swappable from config.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Protocol, runtime_checkable

from lorekeeper.models import InboundMessage, KnowledgeEntry, MediaPayload


class ContentType(str, Enum):
    """Modality of a batch — used by the LLM provider for model routing."""

    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    COMPLEX = "complex"


# A source adapter pushes each normalized message into one of these.
MessageHandler = Callable[[InboundMessage], Awaitable[None]]


@runtime_checkable
class LLMProvider(Protocol):
    """Routes prompts to an LLM. Implementations pick the model per ContentType."""

    async def complete(
        self,
        prompt: str,
        *,
        content_type: ContentType = ContentType.TEXT,
        max_tokens: int = 4096,
    ) -> str: ...

    async def complete_multimodal(
        self,
        text_prompt: str,
        media: list[MediaPayload],
        *,
        content_type: ContentType = ContentType.IMAGE,
        max_tokens: int = 4096,
    ) -> str: ...


@runtime_checkable
class KnowledgeSink(Protocol):
    """Persists an extracted knowledge entry (Notion, Markdown, DB, …)."""

    name: str

    async def write(self, entry: KnowledgeEntry) -> None: ...


@runtime_checkable
class Notifier(Protocol):
    """Sends feedback back to a conversation (optional; may be a no-op)."""

    async def send(self, conversation_id: str, text: str) -> None: ...

    async def show_progress(self, conversation_id: str) -> None: ...

    async def alert(self, text: str) -> None: ...
