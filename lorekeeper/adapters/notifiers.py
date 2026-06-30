"""Notifier adapters."""

import logging

logger = logging.getLogger(__name__)


class NullNotifier:
    """No-op notifier — for runs with no chat to reply to (e.g. local Markdown)."""

    async def send(self, conversation_id: str, text: str) -> None:
        logger.debug(f"[notify {conversation_id}] {text}")

    async def show_progress(self, conversation_id: str) -> None:
        return None

    async def alert(self, text: str) -> None:
        logger.warning(f"[alert] {text}")
