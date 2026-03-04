"""LINE Webhook 處理 — 快速接收，非同步處理"""

import logging
import hashlib
import hmac
import base64
from fastapi import APIRouter, Request, HTTPException

from app.config import get_settings
from app.models.message import RawMessage
from app.pipeline.parser import MessageParser

logger = logging.getLogger(__name__)
router = APIRouter()
parser = MessageParser()


def verify_signature(body: bytes, signature: str) -> bool:
    """驗證 LINE Webhook 簽名，確保請求來自 LINE Platform"""
    settings = get_settings()
    channel_secret = settings.line_channel_secret.encode("utf-8")
    hash_value = hmac.new(channel_secret, body, hashlib.sha256).digest()
    expected = base64.b64encode(hash_value).decode("utf-8")
    return hmac.compare_digest(expected, signature)


@router.post("/webhook")
async def handle_webhook(request: Request):
    """
    接收 LINE Webhook 事件
    設計原則：驗證後立刻回 200，耗時操作全部非同步
    """
    body = await request.body()

    # 1. 驗證簽名
    signature = request.headers.get("X-Line-Signature", "")
    if not verify_signature(body, signature):
        raise HTTPException(status_code=400, detail="Invalid signature")

    # 2. 解析並分派事件（非同步，不阻塞回應）
    import asyncio
    import json

    try:
        payload = json.loads(body)
        events = payload.get("events", [])

        for event in events:
            # 只處理群組的訊息事件
            source = event.get("source", {})
            if source.get("type") != "group":
                continue

            if event.get("type") == "message":
                # 非同步處理，不等待完成
                asyncio.create_task(_process_message_event(event))

    except Exception as e:
        logger.error(f"解析 Webhook 事件失敗: {e}")

    # 3. 立刻回傳 200（LINE 要求快速回應）
    return {"status": "ok"}


async def _process_message_event(event: dict):
    """非同步處理單一訊息事件"""
    try:
        raw_msg = RawMessage.from_line_event(event)
        if raw_msg:
            await parser.process(raw_msg)
    except Exception as e:
        logger.error(f"處理訊息事件失敗: {e}", exc_info=True)
