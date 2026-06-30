"""Telegram adapter — a second `MessageSource`, proving the source seam.

Mirrors the LINE adapter's shape so the contrast is clear:
- `TelegramClient`   : webhook secret check, media download, sendMessage, typing action
- `TelegramSource`   : FastAPI webhook → normalized `InboundMessage`
- `TelegramNotifier` : implements the `Notifier` port

The pipeline is untouched — only `app.py` learns the new `SOURCE=telegram` value.
"""

import asyncio
import hmac
import logging
from datetime import datetime

import httpx
from fastapi import APIRouter, HTTPException, Request

from lorekeeper.models import InboundMessage, MediaPayload, MessageType
from lorekeeper.ports import MessageHandler
from lorekeeper.services.safe_http import safe_get

logger = logging.getLogger(__name__)

API = "https://api.telegram.org"
MAX_MEDIA_BYTES = 20 * 1024 * 1024  # 20 MB
GROUP_CHAT_TYPES = {"group", "supergroup"}


class TelegramClient:
    """Thin async wrapper over the Telegram Bot API."""

    def __init__(self, bot_token: str, webhook_secret: str = ""):
        self.bot_token = bot_token
        self.webhook_secret = webhook_secret

    def verify(self, secret_header: str) -> bool:
        """Telegram echoes the secret_token set on setWebhook in this header.
        fail-closed if unset or missing."""
        if not self.webhook_secret:
            logger.error("TELEGRAM_WEBHOOK_SECRET 未設定，拒絕所有 webhook 請求")
            return False
        if not secret_header:
            return False
        return hmac.compare_digest(self.webhook_secret, secret_header)

    async def download_file(self, file_id: str) -> MediaPayload | None:
        """getFile → resolve file_path → download (size-capped)."""
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                r = await client.get(
                    f"{API}/bot{self.bot_token}/getFile",
                    params={"file_id": file_id},
                )
                r.raise_for_status()
                file_path = r.json()["result"]["file_path"]

            resp = await safe_get(
                f"{API}/file/bot{self.bot_token}/{file_path}",
                max_bytes=MAX_MEDIA_BYTES,
                timeout=30.0,
            )
            return MediaPayload(
                data=resp.content,
                mime_type=resp.headers.get("content-type", "application/octet-stream"),
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"Telegram 檔案下載失敗 {file_id}: {e}")
            return None

    async def send_message(self, chat_id: str, text: str) -> None:
        await self._post("sendMessage", {"chat_id": chat_id, "text": text})

    async def send_chat_action(self, chat_id: str, action: str = "typing") -> None:
        await self._post("sendChatAction", {"chat_id": chat_id, "action": action})

    async def _post(self, method: str, payload: dict) -> None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{API}/bot{self.bot_token}/{method}", json=payload
                )
                resp.raise_for_status()
        except Exception as e:  # noqa: BLE001
            logger.error(f"Telegram {method} 失敗: {e}")


class TelegramSource:
    """Webhook source: verifies the secret token, normalizes the Update,
    downloads media, and hands each `InboundMessage` to the handler."""

    name = "telegram"

    def __init__(self, client: TelegramClient, on_message: MessageHandler):
        self.client = client
        self.on_message = on_message
        self.router = APIRouter()
        self.router.add_api_route("/telegram/webhook", self._handle, methods=["POST"])

    async def _handle(self, request: Request) -> dict:
        secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        if not self.client.verify(secret):
            raise HTTPException(status_code=403, detail="Invalid secret token")

        try:
            update = await request.json()
            message = update.get("message") or update.get("channel_post")
            if message and message.get("chat", {}).get("type") in GROUP_CHAT_TYPES:
                asyncio.create_task(self._process(message))
        except Exception as e:  # noqa: BLE001
            logger.error(f"解析 Telegram Update 失敗: {e}")

        return {"ok": True}

    async def _process(self, message: dict) -> None:
        try:
            inbound = await self._to_inbound(message)
            if inbound:
                await self.on_message(inbound)
        except Exception as e:  # noqa: BLE001
            logger.error(f"處理 Telegram 訊息失敗: {e}", exc_info=True)

    async def _to_inbound(self, m: dict) -> InboundMessage | None:
        msg_type, text, file_id = self._classify(m)
        if msg_type is None:
            return None

        media = None
        if file_id and msg_type in (MessageType.IMAGE, MessageType.AUDIO):
            media = await self.client.download_file(file_id)

        frm = m.get("from", {})
        sender_name = " ".join(
            filter(None, [frm.get("first_name"), frm.get("last_name")])
        ) or frm.get("username", "")
        return InboundMessage(
            id=str(m.get("message_id", "")),
            conversation_id=str(m.get("chat", {}).get("id", "")),
            sender_id=str(frm.get("id", "")),
            sender_name=sender_name,
            type=msg_type,
            text=text,
            timestamp=datetime.fromtimestamp(m.get("date", 0)),
            media=media,
        )

    @staticmethod
    def _classify(m: dict) -> tuple[MessageType | None, str, str | None]:
        """Map a Telegram message object to (type, text, file_id)."""
        if "text" in m:
            return MessageType.TEXT, m["text"], None
        if m.get("photo"):
            # photo is a list of sizes; the last is the largest
            return (
                MessageType.IMAGE,
                m.get("caption", ""),
                m["photo"][-1].get("file_id"),
            )
        if "voice" in m:
            return MessageType.AUDIO, m.get("caption", ""), m["voice"].get("file_id")
        if "audio" in m:
            return MessageType.AUDIO, m.get("caption", ""), m["audio"].get("file_id")
        if "sticker" in m:
            return MessageType.STICKER, "[貼圖]", None
        if "document" in m:
            return MessageType.FILE, m.get("caption", ""), None
        return None, "", None


class TelegramNotifier:
    """Implements the `Notifier` port using Telegram sendMessage / chat action."""

    def __init__(self, client: TelegramClient, admin_chat_id: str = ""):
        self.client = client
        self.admin_chat_id = admin_chat_id

    async def send(self, conversation_id: str, text: str) -> None:
        await self.client.send_message(conversation_id, text)

    async def show_progress(self, conversation_id: str) -> None:
        await self.client.send_chat_action(conversation_id, "typing")

    async def alert(self, text: str) -> None:
        if not self.admin_chat_id:
            logger.warning("未設定 TELEGRAM_ADMIN_CHAT_ID，無法發送管理員通知")
            return
        await self.client.send_message(self.admin_chat_id, f"[Bot] {text}")
