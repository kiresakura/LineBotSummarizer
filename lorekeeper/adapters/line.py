"""LINE adapter — source (webhook), low-level client, and notifier.

Everything LINE-specific lives here:
- `LineClient`   : signature verification, media download, push, loading animation
- `LineSource`   : FastAPI webhook → normalized `InboundMessage`
- `LineNotifier` : implements the `Notifier` port via push messages
"""

import asyncio
import base64
import hashlib
import hmac
import json
import logging
from datetime import datetime

import httpx
from fastapi import APIRouter, HTTPException, Request

from lorekeeper.models import InboundMessage, MediaPayload, MessageType
from lorekeeper.ports import MessageHandler
from lorekeeper.services.safe_http import safe_get

logger = logging.getLogger(__name__)

PUSH_URL = "https://api.line.me/v2/bot/message/push"
LOADING_URL = "https://api.line.me/v2/bot/chat/loading/start"
CONTENT_URL = "https://api-data.line.me/v2/bot/message/{message_id}/content"
MAX_MEDIA_BYTES = 20 * 1024 * 1024  # 20 MB


class LineClient:
    """Thin async wrapper over the LINE Messaging API."""

    def __init__(self, channel_secret: str, access_token: str):
        self.channel_secret = channel_secret
        self.access_token = access_token

    def verify_signature(self, body: bytes, signature: str) -> bool:
        # fail-closed：密鑰未設定或缺簽名一律拒絕
        if not self.channel_secret:
            logger.error("LINE_CHANNEL_SECRET 未設定，拒絕所有 webhook 請求")
            return False
        if not signature:
            return False
        mac = hmac.new(
            self.channel_secret.encode("utf-8"), body, hashlib.sha256
        ).digest()
        expected = base64.b64encode(mac).decode("utf-8")
        return hmac.compare_digest(expected, signature)

    async def download_content(self, message_id: str) -> MediaPayload | None:
        """Download media from the LINE Content API (size-capped)."""
        url = CONTENT_URL.format(message_id=message_id)
        try:
            resp = await safe_get(
                url,
                max_bytes=MAX_MEDIA_BYTES,
                timeout=30.0,
                headers={"Authorization": f"Bearer {self.access_token}"},
            )
            return MediaPayload(
                data=resp.content,
                mime_type=resp.headers.get("content-type", "application/octet-stream"),
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"LINE 內容下載失敗 {message_id}: {e}")
            return None

    async def push(self, to: str, text: str) -> None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    PUSH_URL,
                    headers={
                        "Authorization": f"Bearer {self.access_token}",
                        "Content-Type": "application/json",
                    },
                    json={"to": to, "messages": [{"type": "text", "text": text}]},
                )
                resp.raise_for_status()
        except Exception as e:  # noqa: BLE001
            logger.error(f"LINE 訊息發送失敗: {e}")

    async def show_loading(self, chat_id: str, seconds: int = 60) -> None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    LOADING_URL,
                    headers={
                        "Authorization": f"Bearer {self.access_token}",
                        "Content-Type": "application/json",
                    },
                    json={"chatId": chat_id, "loadingSeconds": min(seconds, 60)},
                )
                resp.raise_for_status()
        except Exception as e:  # noqa: BLE001 — cosmetic, never block on it
            logger.debug(f"Loading 動畫啟動失敗（不影響功能）: {e}")


class LineSource:
    """Webhook source: verifies signature, normalizes events, downloads media,
    and hands each `InboundMessage` to the injected handler."""

    name = "line"

    def __init__(self, client: LineClient, on_message: MessageHandler):
        self.client = client
        self.on_message = on_message
        self.router = APIRouter()
        self.router.add_api_route("/webhook", self._handle, methods=["POST"])

    async def _handle(self, request: Request) -> dict:
        """驗證後立刻回 200，耗時操作全部非同步（LINE 要求快速回應）。"""
        body = await request.body()
        signature = request.headers.get("X-Line-Signature", "")
        if not self.client.verify_signature(body, signature):
            raise HTTPException(status_code=400, detail="Invalid signature")

        try:
            payload = json.loads(body)
            for event in payload.get("events", []):
                if event.get("source", {}).get("type") != "group":
                    continue  # 只處理群組訊息
                if event.get("type") == "message":
                    asyncio.create_task(self._process(event))
        except Exception as e:  # noqa: BLE001
            logger.error(f"解析 Webhook 事件失敗: {e}")

        return {"status": "ok"}

    async def _process(self, event: dict) -> None:
        try:
            msg = await self._to_inbound(event)
            if msg:
                await self.on_message(msg)
        except Exception as e:  # noqa: BLE001
            logger.error(f"處理訊息事件失敗: {e}", exc_info=True)

    async def _to_inbound(self, event: dict) -> InboundMessage | None:
        source = event.get("source", {})
        message = event.get("message", {})
        msg_type = message.get("type", "")
        if msg_type not in [t.value for t in MessageType]:
            return None

        media = None
        if msg_type in ("image", "audio"):
            logger.info(f"收到{msg_type}訊息: {message.get('id')}, 開始下載...")
            media = await self.client.download_content(message.get("id", ""))

        text = message.get("text", "")
        if msg_type == "sticker":
            text = "[貼圖]"

        return InboundMessage(
            id=message.get("id", ""),
            conversation_id=source.get("groupId", ""),
            sender_id=source.get("userId", ""),
            type=MessageType(msg_type),
            text=text,
            timestamp=datetime.fromtimestamp(event.get("timestamp", 0) / 1000),
            media=media,
        )


class LineNotifier:
    """Implements the `Notifier` port using LINE push messages."""

    def __init__(self, client: LineClient, admin_user_id: str = ""):
        self.client = client
        self.admin_user_id = admin_user_id

    async def send(self, conversation_id: str, text: str) -> None:
        await self.client.push(conversation_id, text)

    async def show_progress(self, conversation_id: str) -> None:
        await self.client.show_loading(conversation_id)

    async def alert(self, text: str) -> None:
        if not self.admin_user_id:
            logger.warning("未設定 ADMIN_LINE_USER_ID，無法發送管理員通知")
            return
        await self.client.push(self.admin_user_id, f"[Bot 通知] {text}")
