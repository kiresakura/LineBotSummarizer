"""Stage 1: 訊息解析器 — 提取文字、URL、下載圖片/音訊"""

import re
import logging
import httpx
from app.config import get_settings
from app.models.message import RawMessage, MessageType

logger = logging.getLogger(__name__)

URL_PATTERN = re.compile(
    r'https?://[^\s<>"{}|\\^`\[\]]+',
    re.IGNORECASE
)


class MessageParser:
    """解析原始訊息，提取結構化內容後送入聚合器"""

    async def process(self, msg: RawMessage):
        """解析訊息並送入聚合器"""
        from app.main import aggregator

        if msg.message_type == MessageType.TEXT:
            urls = URL_PATTERN.findall(msg.text)
            if urls:
                logger.info(f"發現 {len(urls)} 個 URL: {urls}")
            await aggregator.add_message(msg.group_id, msg)

        elif msg.message_type == MessageType.IMAGE:
            logger.info(f"收到圖片訊息: {msg.message_id}, 開始下載...")
            await self._download_line_content(msg)
            await aggregator.add_message(msg.group_id, msg)

        elif msg.message_type == MessageType.AUDIO:
            logger.info(f"收到音訊訊息: {msg.message_id}, 開始下載...")
            await self._download_line_content(msg)
            await aggregator.add_message(msg.group_id, msg)

        elif msg.message_type == MessageType.STICKER:
            msg.text = "[貼圖]"
            await aggregator.add_message(msg.group_id, msg)

        elif msg.message_type == MessageType.FILE:
            logger.info(f"收到檔案訊息: {msg.message_id}")
            await aggregator.add_message(msg.group_id, msg)

        else:
            logger.debug(f"跳過不支援的訊息類型: {msg.message_type}")

    async def _download_line_content(self, msg: RawMessage):
        """從 LINE Content API 下載媒體內容"""
        settings = get_settings()
        url = f"https://api-data.line.me/v2/bot/message/{msg.message_id}/content"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {settings.line_channel_access_token}"},
                )
                response.raise_for_status()

                msg.media_content = response.content
                msg.media_mime_type = response.headers.get("content-type", "application/octet-stream")

                logger.info(
                    f"下載完成: {msg.message_id}, "
                    f"大小={len(msg.media_content)} bytes, "
                    f"type={msg.media_mime_type}"
                )
        except httpx.HTTPStatusError as e:
            logger.error(f"LINE 內容下載 HTTP 錯誤: {e.response.status_code} for {msg.message_id}")
        except Exception as e:
            logger.error(f"LINE 內容下載失敗: {e} for {msg.message_id}")
