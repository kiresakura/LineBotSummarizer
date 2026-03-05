"""情報收集排程器 — 定時執行所有收集器並寫入 Notion"""

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.config import get_settings
from app.collectors.base import BaseCollector
from app.collectors.rss_collector import RSSCollector
from app.collectors.dedup import DedupStore
from app.pipeline.intel_writer import IntelWriter
from app.models.intel import IntelItem

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None
_dedup: DedupStore | None = None

# 已註冊的收集器
COLLECTORS: list[BaseCollector] = [
    RSSCollector(),
]


async def start_scheduler():
    """啟動排程器"""
    global _scheduler, _dedup
    settings = get_settings()

    # 初始化去重資料庫
    _dedup = DedupStore()
    await _dedup.init()

    # 建立排程器
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        run_collection,
        "interval",
        hours=settings.intel_schedule_hours,
        id="intel_collection",
        next_run_time=datetime.now(),  # 啟動時立刻執行一次
    )
    _scheduler.start()
    logger.info(
        f"情報收集排程器已啟動 — 每 {settings.intel_schedule_hours} 小時執行一次，"
        f"已註冊 {len(COLLECTORS)} 個收集器"
    )


async def stop_scheduler():
    """關閉排程器"""
    global _scheduler, _dedup
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("情報收集排程器已關閉")
    if _dedup:
        await _dedup.close()
        _dedup = None


async def run_collection():
    """執行一輪情報收集"""
    from app.services.line_notify import notify_admin

    settings = get_settings()
    logger.info("=== 開始情報收集 ===")
    start_time = datetime.now()

    total_collected = 0
    total_new = 0
    total_written = 0
    errors: list[str] = []

    try:
        # 1. 清理過期去重記錄
        if _dedup:
            await _dedup.cleanup(settings.intel_dedup_days)

        # 2. 遍歷所有收集器
        all_new_items: list[IntelItem] = []

        for collector in COLLECTORS:
            try:
                items = await collector.collect()
                total_collected += len(items)

                # 3. 去重過濾
                for item in items:
                    if not item.dedup_hash:
                        item.compute_hash()
                    if _dedup and await _dedup.is_duplicate(item.dedup_hash):
                        continue
                    all_new_items.append(item)
                    if _dedup:
                        await _dedup.mark_seen(item.dedup_hash)

                logger.info(
                    f"收集器 [{collector.name}]: "
                    f"收集 {len(items)} 筆，新增 {len(all_new_items) - total_new} 筆"
                )
                total_new = len(all_new_items)

            except Exception as e:
                msg = f"收集器 [{collector.name}] 失敗: {e}"
                logger.error(msg, exc_info=True)
                errors.append(msg)

        # 4. 寫入 Notion
        if all_new_items and settings.intel_notion_database_id:
            writer = IntelWriter()
            total_written = await writer.write_batch(all_new_items)
        elif all_new_items:
            logger.warning("未設定 INTEL_NOTION_DATABASE_ID，跳過寫入")

        # 5. 發送收集摘要
        elapsed = (datetime.now() - start_time).total_seconds()
        summary = (
            f"📡 情報收集完成\n"
            f"耗時：{elapsed:.1f}s\n"
            f"收集：{total_collected} 筆\n"
            f"新增：{total_new} 筆（去重後）\n"
            f"寫入 Notion：{total_written} 筆"
        )
        if errors:
            summary += f"\n⚠️ 錯誤：{len(errors)} 個"
            for err in errors[:3]:
                summary += f"\n  - {err[:100]}"

        logger.info(summary)
        if total_written > 0 or errors:
            await notify_admin(summary)

    except Exception as e:
        logger.error(f"情報收集排程異常: {e}", exc_info=True)
        try:
            await notify_admin(f"情報收集排程異常\n{str(e)[:200]}")
        except Exception:
            pass
