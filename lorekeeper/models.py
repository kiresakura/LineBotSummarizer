"""Domain models — provider-neutral representations shared across the pipeline.

Nothing here knows about LINE, Notion, or any specific provider. Source adapters
produce `InboundMessage`; the pipeline emits `KnowledgeEntry`; sinks persist it.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class MessageType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    FILE = "file"
    STICKER = "sticker"
    LOCATION = "location"


class Importance(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NOISE = "noise"


class MediaPayload(BaseModel):
    """Binary media already downloaded by a source adapter."""

    data: bytes
    mime_type: str

    model_config = {"arbitrary_types_allowed": True}

    @property
    def is_image(self) -> bool:
        return self.mime_type.startswith("image")

    @property
    def is_audio(self) -> bool:
        return self.mime_type.startswith("audio")


class UrlContent(BaseModel):
    """Content crawled from a URL found in a message."""

    url: str
    title: str
    content: str


class InboundMessage(BaseModel):
    """A single normalized message emitted by any source adapter."""

    id: str
    conversation_id: str  # LINE group id, Telegram chat id, …
    sender_id: str
    sender_name: str = ""
    type: MessageType
    text: str = ""
    timestamp: datetime
    url_contents: list[UrlContent] = Field(default_factory=list)
    media: MediaPayload | None = None

    @property
    def has_media(self) -> bool:
        return self.media is not None and len(self.media.data) > 0


class KnowledgeEntry(BaseModel):
    """Structured knowledge extracted from a batch of messages — sink-neutral.

    `knowledge` holds the *full* extracted knowledge points, not a summary.
    """

    category: str
    importance: Importance
    title: str = ""
    knowledge: str = ""
    media_descriptions: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    action_items: list[str] = Field(default_factory=list)
    source_messages: list[InboundMessage] = Field(default_factory=list)
    conversation_label: str = ""
    urls: list[str] = Field(default_factory=list)
