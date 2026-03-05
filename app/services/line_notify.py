"""LINE 訊息發送服務 — 群組回覆 + Loading 動畫 + 管理員通知"""

import logging
import httpx
from app.config import get_settings

logger = logging.getLogger(__name__)

LINE_PUSH_URL = "https://api.line.me/v2/bot/message/push"
LINE_LOADING_URL = "https://api.line.me/v2/bot/chat/loading/start"


async def show_loading(chat_id: str, seconds: int = 60):
    """顯示 LINE Loading 動畫（正在輸入...），最長 60 秒"""
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                LINE_LOADING_URL,
                headers={
                    "Authorization": f"Bearer {settings.line_channel_access_token}",
                    "Content-Type": "application/json",
                },
                json={"chatId": chat_id, "loadingSeconds": min(seconds, 60)},
            )
            response.raise_for_status()
    except Exception as e:
        logger.debug(f"Loading 動畫啟動失敗（不影響功能）: {e}")


async def send_to_group(group_id: str, text: str):
    """發送訊息到 LINE 群組"""
    await _push_message(group_id, text)


async def notify_admin(text: str):
    """私訊通知管理員（錯誤或重要事件）"""
    settings = get_settings()
    if not settings.admin_line_user_id:
        logger.warning("未設定 ADMIN_LINE_USER_ID，無法發送管理員通知")
        return
    await _push_message(settings.admin_line_user_id, f"[Bot 通知] {text}")


async def _push_message(to: str, text: str):
    """透過 LINE Push API 發送訊息"""
    settings = get_settings()
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                LINE_PUSH_URL,
                headers={
                    "Authorization": f"Bearer {settings.line_channel_access_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "to": to,
                    "messages": [{"type": "text", "text": text}],
                },
            )
            response.raise_for_status()
    except Exception as e:
        logger.error(f"LINE 訊息發送失敗: {e}")
