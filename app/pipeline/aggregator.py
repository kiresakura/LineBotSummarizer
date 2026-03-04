"""Stage 2: 訊息聚合器 — 避免逐條處理造成碎片化"""

import asyncio
import logging
import time
from app.config import get_settings
from app.models.message import RawMessage

logger = logging.getLogger(__name__)


class MessageAggregator:
    """
    滑動視窗聚合器：收集同一群組的訊息，
    達到條件後批次送去 AI 分類。

    觸發條件（任一滿足）：
    1. 累積達 max_batch_size 條訊息
    2. 超過 aggregation_window_seconds 時間
    """

    def __init__(self):
        settings = get_settings()
        self.window_size = settings.aggregation_window_seconds
        self.min_batch = settings.min_batch_size
        self.max_batch = settings.max_batch_size

        self.buffers: dict[str, list[RawMessage]] = {}
        self.timers: dict[str, float] = {}
        self._running = False
        self._flush_task: asyncio.Task | None = None

    async def start(self):
        """啟動定時沖洗檢查"""
        self._running = True
        self._flush_task = asyncio.create_task(self._periodic_flush())
        logger.info("訊息聚合器已啟動")

    async def add_message(self, group_id: str, message: RawMessage):
        """加入一條訊息到對應群組的 buffer"""
        if group_id not in self.buffers:
            self.buffers[group_id] = []
            self.timers[group_id] = time.time()

        self.buffers[group_id].append(message)
        logger.debug(
            f"群組 {group_id}: buffer 累積 {len(self.buffers[group_id])} 條"
        )

        # 達到上限，立刻觸發
        if len(self.buffers[group_id]) >= self.max_batch:
            await self._flush_group(group_id)

    async def _periodic_flush(self):
        """每 30 秒檢查一次，超時的 buffer 送出處理"""
        while self._running:
            await asyncio.sleep(30)
            now = time.time()
            expired_groups = [
                gid for gid, start in self.timers.items()
                if now - start > self.window_size
                and len(self.buffers.get(gid, [])) >= self.min_batch
            ]
            for gid in expired_groups:
                await self._flush_group(gid)

    async def _flush_group(self, group_id: str):
        """沖洗某個群組的 buffer，送入分類管線"""
        if group_id not in self.buffers or not self.buffers[group_id]:
            return

        batch = self.buffers.pop(group_id)
        self.timers.pop(group_id, None)

        logger.info(f"群組 {group_id}: 送出 {len(batch)} 條訊息進行分類")

        # 非同步送入分類階段
        asyncio.create_task(self._classify_batch(group_id, batch))

    async def _classify_batch(self, group_id: str, batch: list[RawMessage]):
        """呼叫 AI 分類器處理一批訊息"""
        try:
            from app.pipeline.classifier import MessageClassifier
            classifier = MessageClassifier()
            result = await classifier.classify(group_id, batch)

            if result and result.importance.value != "noise":
                from app.pipeline.writer import NotionWriter
                writer = NotionWriter()
                await writer.write(result)
                logger.info(f"✅ 已寫入 Notion: [{result.category}] {result.summary[:50]}")
            else:
                logger.debug("訊息被判定為噪音，跳過寫入")

        except Exception as e:
            logger.error(f"分類/寫入失敗: {e}", exc_info=True)

    async def flush_all(self):
        """關閉時沖洗所有剩餘訊息"""
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
        for gid in list(self.buffers.keys()):
            await self._flush_group(gid)
