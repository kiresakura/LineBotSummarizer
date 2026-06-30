"""Debounce / batching behaviour of the aggregator."""

import asyncio
from datetime import datetime

from lorekeeper.models import InboundMessage, MessageType
from lorekeeper.pipeline.aggregator import MessageAggregator


def _msg(i: int, conversation: str = "c1") -> InboundMessage:
    return InboundMessage(
        id=str(i),
        conversation_id=conversation,
        sender_id="u",
        type=MessageType.TEXT,
        text=f"m{i}",
        timestamp=datetime(2026, 1, 1, 0, 0, min(i, 59)),
    )


async def test_flush_immediately_on_max_batch():
    batches = []

    async def on_batch(conversation, batch):
        batches.append((conversation, batch))

    agg = MessageAggregator(on_batch, cooldown_seconds=10, max_batch_size=3)
    for i in range(3):
        await agg.add("c1", _msg(i))
    await asyncio.sleep(0.05)  # let the spawned task run

    assert len(batches) == 1
    assert len(batches[0][1]) == 3


async def test_flush_after_cooldown():
    batches = []

    async def on_batch(conversation, batch):
        batches.append(batch)

    agg = MessageAggregator(on_batch, cooldown_seconds=0.05, max_batch_size=99)
    await agg.add("c1", _msg(0))
    await agg.add("c1", _msg(1))
    assert batches == []  # still within the cooldown window

    await asyncio.sleep(0.12)
    assert len(batches) == 1
    assert len(batches[0]) == 2


async def test_conversations_are_isolated():
    batches = []

    async def on_batch(conversation, batch):
        batches.append((conversation, len(batch)))

    agg = MessageAggregator(on_batch, cooldown_seconds=0.05, max_batch_size=99)
    await agg.add("a", _msg(0, "a"))
    await agg.add("b", _msg(0, "b"))
    await asyncio.sleep(0.12)

    assert {c for c, _ in batches} == {"a", "b"}


async def test_flush_all_drains_pending():
    batches = []

    async def on_batch(conversation, batch):
        batches.append(batch)

    agg = MessageAggregator(on_batch, cooldown_seconds=100, max_batch_size=99)
    await agg.add("c1", _msg(0))
    await agg.flush_all()
    await asyncio.sleep(0.02)

    assert len(batches) == 1
