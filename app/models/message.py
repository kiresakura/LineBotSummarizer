"""訊息資料模型"""

from __future__ import annotations
from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


class MessageType(str, Enum):
    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
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
    media_url: str | None = None
    timestamp: datetime
    reply_token: str = ""

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
    summary: str
    tags: list[str] = Field(default_factory=list)
    action_items: list[str] = Field(default_factory=list)
    original_messages: list[RawMessage]
    group_name: str = ""
    urls_found: list[str] = Field(default_factory=list)
