"""Pipeline stage 2 — aggregate bursty messages per conversation (debounce).

Each conversation has its own buffer. A flush fires when either the buffer has
been quiet for `cooldown_seconds`, or it reaches `max_batch_size`. The handler to
run on a flushed batch is injected, so the aggregator knows nothing about
classification or sinks.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable

from lorekeeper.models import InboundMessage

logger = logging.getLogger(__name__)

BatchHandler = Callable[[str, list[InboundMessage]], Awaitable[None]]


class MessageAggregator:
    def __init__(
        self,
        on_batch: BatchHandler,
        *,
        cooldown_seconds: float = 3.0,
        max_batch_size: int = 20,
    ):
        self._on_batch = on_batch
        self.cooldown = cooldown_seconds
        self.max_batch = max_batch_size
        self._buffers: dict[str, list[InboundMessage]] = {}
        self._timers: dict[str, asyncio.Task] = {}

    async def add(self, conversation_id: str, message: InboundMessage) -> None:
        """Buffer a message and (re)start the conversation's cooldown timer."""
        self._buffers.setdefault(conversation_id, []).append(message)

        if len(self._buffers[conversation_id]) >= self.max_batch:
            self._cancel_timer(conversation_id)
            await self._flush(conversation_id)
            return

        self._cancel_timer(conversation_id)
        self._timers[conversation_id] = asyncio.create_task(
            self._delayed_flush(conversation_id)
        )

    async def _delayed_flush(self, conversation_id: str) -> None:
        try:
            await asyncio.sleep(self.cooldown)
        except asyncio.CancelledError:
            return
        await self._flush(conversation_id)

    def _cancel_timer(self, conversation_id: str) -> None:
        timer = self._timers.pop(conversation_id, None)
        if timer:
            timer.cancel()

    async def _flush(self, conversation_id: str) -> None:
        batch = self._buffers.pop(conversation_id, None)
        self._cancel_timer(conversation_id)
        if not batch:
            return
        logger.info(f"群組 {conversation_id}: 送出 {len(batch)} 條訊息進行分類")
        asyncio.create_task(self._on_batch(conversation_id, batch))

    async def flush_all(self) -> None:
        """Flush every pending buffer (called on shutdown)."""
        for conversation_id in list(self._buffers.keys()):
            await self._flush(conversation_id)
