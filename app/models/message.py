"""訊息資料模型"""

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


class RawMessage(BaseModel):
    """從 LINE 收到的原始訊息"""
    message_id: str
    group_id: str
    user_id: str
    user_name: str = ""
    message_type: MessageType
    text: str = ""
    url_contents: list[dict] = Field(default_factory=list)  # [{"url": ..., "title": ..., "content": ...}]
    media_url: str | None = None
    media_content: bytes | None = None
    media_mime_type: str | None = None
    timestamp: datetime
    reply_token: str = ""

    model_config = {"arbitrary_types_allowed": True}

    @property
    def has_media(self) -> bool:
        return self.media_content is not None and len(self.media_content) > 0

    @classmethod
    def from_line_event(cls, event: dict) -> RawMessage | None:
        """從 LINE Webhook 事件轉換"""
        source = event.get("source", {})
        message = event.get("message", {})
        msg_type = message.get("type", "")

        if msg_type not in [e.value for e in MessageType]:
            return None

        return cls(
            message_id=message.get("id", ""),
            group_id=source.get("groupId", ""),
            user_id=source.get("userId", ""),
            message_type=MessageType(msg_type),
            text=message.get("text", ""),
            timestamp=datetime.fromtimestamp(event.get("timestamp", 0) / 1000),
            reply_token=event.get("replyToken", ""),
        )


class ClassifiedMessage(BaseModel):
    """AI 分類後的訊息"""
    category: str
    importance: Importance
    title: str = ""
    summary: str  # 完整知識點內容
    media_descriptions: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    action_items: list[str] = Field(default_factory=list)
    original_messages: list[RawMessage]
    group_name: str = ""
    urls_found: list[str] = Field(default_factory=list)
