"""Stage 1: 訊息解析器 — 提取文字、URL、圖片等內容"""

import re
import logging
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
            # 提取文字中的 URL
            urls = URL_PATTERN.findall(msg.text)
            if urls:
                logger.info(f"發現 {len(urls)} 個 URL: {urls}")
            await aggregator.add_message(msg.group_id, msg)

        elif msg.message_type == MessageType.IMAGE:
            # 圖片：記錄 metadata，實際下載在分類階段按需進行
            logger.info(f"收到圖片訊息: {msg.message_id}")
            await aggregator.add_message(msg.group_id, msg)

        elif msg.message_type == MessageType.STICKER:
            # 貼圖通常是噪音，但還是記錄（聚合器可能會過濾）
            msg.text = "[貼圖]"
            await aggregator.add_message(msg.group_id, msg)

        elif msg.message_type == MessageType.FILE:
            logger.info(f"收到檔案訊息: {msg.message_id}")
            await aggregator.add_message(msg.group_id, msg)

        else:
            logger.debug(f"跳過不支援的訊息類型: {msg.message_type}")
