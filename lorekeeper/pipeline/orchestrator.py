"""Pipeline stage 4 — orchestrate a flushed batch.

Sends immediate feedback, runs classification, fans the result out to every
configured sink, then reports the outcome. Talks to the outside world only
through the `KnowledgeSink` and `Notifier` ports.
"""

import logging

from lorekeeper.models import Importance, InboundMessage
from lorekeeper.pipeline.classifier import MessageClassifier
from lorekeeper.ports import KnowledgeSink, Notifier

logger = logging.getLogger(__name__)

IMPORTANCE_LABEL = {"high": "🔴 高", "medium": "🟡 中", "low": "🟢 低"}


class Orchestrator:
    def __init__(
        self,
        classifier: MessageClassifier,
        sinks: list[KnowledgeSink],
        notifier: Notifier,
        *,
        noise_filter_enabled: bool = True,
    ):
        self.classifier = classifier
        self.sinks = sinks
        self.notifier = notifier
        self.noise_filter_enabled = noise_filter_enabled

    async def process(self, conversation_id: str, batch: list[InboundMessage]) -> None:
        try:
            await self._notify_start(conversation_id, batch)

            entry = await self.classifier.classify(conversation_id, batch)
            if entry is None:
                logger.debug("分類回傳空結果，跳過寫入")
                return
            if entry.importance == Importance.NOISE and self.noise_filter_enabled:
                logger.debug("訊息被判定為噪音，跳過寫入")
                return

            written = await self._fan_out(conversation_id, entry)
            if written:
                await self._notify_done(conversation_id, batch, entry, written)

        except Exception as e:  # noqa: BLE001 — top-level batch guard
            logger.error(f"處理批次失敗: {e}", exc_info=True)
            await self.notifier.alert(
                f"處理失敗\n對話: {conversation_id}\n錯誤: {str(e)[:200]}"
            )

    async def _notify_start(
        self, conversation_id: str, batch: list[InboundMessage]
    ) -> None:
        hint = [f"📋 收到 {len(batch)} 則訊息，開始整理知識點"]
        if any(m.url_contents for m in batch):
            hint.append("🔗 含連結內容")
        if any(m.has_media for m in batch):
            hint.append("🖼 含媒體檔案")
        hint.append("⏳ 請稍候...")
        await self.notifier.send(conversation_id, "｜".join(hint))
        await self.notifier.show_progress(conversation_id)

    async def _fan_out(self, conversation_id, entry) -> list[str]:
        written: list[str] = []
        for sink in self.sinks:
            try:
                await sink.write(entry)
                written.append(sink.name)
                logger.info(
                    f"已寫入 {sink.name}: "
                    f"[{entry.category}] {entry.title or entry.knowledge[:40]}"
                )
            except Exception as e:  # noqa: BLE001 — isolate one sink's failure
                logger.error(f"寫入 {sink.name} 失敗: {e}", exc_info=True)
                await self.notifier.alert(
                    f"寫入 {sink.name} 失敗\n對話: {conversation_id}\n"
                    f"錯誤: {str(e)[:200]}"
                )
        return written

    async def _notify_done(self, conversation_id, batch, entry, written) -> None:
        importance = IMPORTANCE_LABEL.get(
            entry.importance.value, entry.importance.value
        )
        tags = " ".join(f"#{t}" for t in entry.tags[:5])
        reply = (
            f"📥 已統整 {len(batch)} 則訊息寫入 {'、'.join(written)}\n"
            f"分類：{entry.category}｜重要性：{importance}\n{tags}"
        )
        await self.notifier.send(conversation_id, reply)
