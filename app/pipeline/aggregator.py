"""Stage 2: 訊息聚合器 — 即時處理，短暫合併快速連發"""

import asyncio
import logging
from app.config import get_settings
from app.models.message import RawMessage

logger = logging.getLogger(__name__)

IMPORTANCE_LABEL = {
    "high": "🔴 高",
    "medium": "🟡 中",
    "low": "🟢 低",
}


class MessageAggregator:
    """
    即時聚合器：訊息進來後等待短暫冷卻期（3 秒），
    若無新訊息則立刻送出處理。快速連發的訊息會被合併成一批。
    """

    COOLDOWN = 3  # 秒，等待連發訊息的冷卻期

    def __init__(self):
        settings = get_settings()
        self.max_batch = settings.max_batch_size

        self.buffers: dict[str, list[RawMessage]] = {}
        self._flush_timers: dict[str, asyncio.Task] = {}
        self._running = False

    async def start(self):
        self._running = True
        logger.info("訊息聚合器已啟動（即時模式）")

    async def add_message(self, group_id: str, message: RawMessage):
        """加入訊息，重設冷卻計時器"""
        if group_id not in self.buffers:
            self.buffers[group_id] = []

        self.buffers[group_id].append(message)

        # 達到上限，立刻觸發
        if len(self.buffers[group_id]) >= self.max_batch:
            await self._cancel_timer(group_id)
            await self._flush_group(group_id)
            return

        # 重設冷卻計時器（每來一則訊息就重新倒數 3 秒）
        await self._cancel_timer(group_id)
        self._flush_timers[group_id] = asyncio.create_task(
            self._delayed_flush(group_id)
        )

    async def _delayed_flush(self, group_id: str):
        """等待冷卻期後沖洗"""
        await asyncio.sleep(self.COOLDOWN)
        await self._flush_group(group_id)

    async def _cancel_timer(self, group_id: str):
        """取消該群組的冷卻計時器"""
        if group_id in self._flush_timers:
            self._flush_timers[group_id].cancel()
            del self._flush_timers[group_id]

    async def _flush_group(self, group_id: str):
        """沖洗某個群組的 buffer，送入分類管線"""
        if group_id not in self.buffers or not self.buffers[group_id]:
            return

        batch = self.buffers.pop(group_id)
        await self._cancel_timer(group_id)

        logger.info(f"群組 {group_id}: 送出 {len(batch)} 條訊息進行分類")
        asyncio.create_task(self._classify_batch(group_id, batch))

    async def _classify_batch(self, group_id: str, batch: list[RawMessage]):
        """呼叫 AI 分類器處理一批訊息，完成後回覆群組"""
        from app.services.line_notify import send_to_group, notify_admin

        try:
            from app.pipeline.classifier import MessageClassifier
            classifier = MessageClassifier()
            result = await classifier.classify(group_id, batch)

            if result and result.importance.value != "noise":
                from app.pipeline.writer import NotionWriter
                writer = NotionWriter()
                await writer.write(result)
                logger.info(f"已寫入 Notion: [{result.category}] {result.summary[:50]}")

                # 回覆群組摘要
                importance = IMPORTANCE_LABEL.get(result.importance.value, result.importance.value)
                tags = " ".join(f"#{t}" for t in result.tags[:5])
                reply = (
                    f"📋 訊息摘要\n"
                    f"分類：{result.category}｜重要性：{importance}\n"
                    f"\n{result.summary}\n"
                )
                if result.action_items:
                    reply += "\n待辦事項：\n"
                    for item in result.action_items:
                        reply += f"  - {item}\n"
                if tags:
                    reply += f"\n{tags}"

                await send_to_group(group_id, reply)
            else:
                logger.debug("訊息被判定為噪音，跳過寫入")

        except Exception as e:
            logger.error(f"分類/寫入失敗: {e}", exc_info=True)
            await notify_admin(f"分類/寫入失敗\n群組: {group_id}\n錯誤: {str(e)[:200]}")

    async def flush_all(self):
        """關閉時沖洗所有剩餘訊息"""
        self._running = False
        for gid in list(self._flush_timers.keys()):
            await self._cancel_timer(gid)
        for gid in list(self.buffers.keys()):
            await self._flush_group(gid)
