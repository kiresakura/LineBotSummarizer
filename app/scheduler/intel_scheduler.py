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


def _build_collectors() -> list[BaseCollector]:
    """根據設定動態建立收集器清單"""
    settings = get_settings()
    collectors: list[BaseCollector] = []

    if settings.intel_rss_feeds:
        collectors.append(RSSCollector())

    if settings.intel_keywords:
        from app.collectors.keyword_monitor import KeywordMonitor
        collectors.append(KeywordMonitor())

    return collectors


async def start_scheduler():
    """啟動排程器"""
    global _scheduler, _dedup
    settings = get_settings()

    # 初始化去重資料庫
    _dedup = DedupStore()
    await _dedup.init()

    # 建立排程器
    _scheduler = AsyncIOScheduler()

    # RSS 收集排程
    if settings.intel_rss_feeds:
        _scheduler.add_job(
            _run_collectors,
            "interval",
            hours=settings.intel_schedule_hours,
            id="intel_rss",
            args=([RSSCollector()],),
            next_run_time=datetime.now(),
        )
        logger.info(f"   RSS 收集: 每 {settings.intel_schedule_hours} 小時")

    # 關鍵字監控排程（獨立頻率）
    if settings.intel_keywords:
        from app.collectors.keyword_monitor import KeywordMonitor
        _scheduler.add_job(
            _run_collectors,
            "interval",
            hours=settings.intel_keywords_schedule_hours,
            id="intel_keywords",
            args=([KeywordMonitor()],),
            next_run_time=datetime.now(),
        )
        keywords_count = len([k for k in settings.intel_keywords.split(",") if k.strip()])
        logger.info(
            f"   關鍵字監控: 每 {settings.intel_keywords_schedule_hours} 小時，"
            f"{keywords_count} 個關鍵字"
        )

    _scheduler.start()
    logger.info("情報收集排程器已啟動")


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


async def _run_collectors(collectors: list[BaseCollector]):
    """執行指定的收集器群組"""
    from app.services.line_notify import notify_admin

    settings = get_settings()
    start_time = datetime.now()

    total_collected = 0
    total_new = 0
    total_written = 0
    errors: list[str] = []
    collector_names: list[str] = []

    try:
        # 清理過期去重記錄
        if _dedup:
            await _dedup.cleanup(settings.intel_dedup_days)

        all_new_items: list[IntelItem] = []

        for collector in collectors:
            collector_names.append(collector.name)
            try:
                items = await collector.collect()
                total_collected += len(items)

                # 去重過濾
                new_before = len(all_new_items)
                for item in items:
                    if not item.dedup_hash:
                        item.compute_hash()
                    if _dedup and await _dedup.is_duplicate(item.dedup_hash):
                        continue
                    all_new_items.append(item)
                    if _dedup:
                        await _dedup.mark_seen(item.dedup_hash)

                new_count = len(all_new_items) - new_before
                logger.info(f"收集器 [{collector.name}]: 收集 {len(items)} 筆，新增 {new_count} 筆")

            except Exception as e:
                msg = f"收集器 [{collector.name}] 失敗: {e}"
                logger.error(msg, exc_info=True)
                errors.append(msg)

        total_new = len(all_new_items)

        # 寫入 Notion
        if all_new_items and settings.intel_notion_database_id:
            writer = IntelWriter()
            total_written = await writer.write_batch(all_new_items)
        elif all_new_items:
            logger.warning("未設定 INTEL_NOTION_DATABASE_ID，跳過寫入")

        # 發送收集摘要
        elapsed = (datetime.now() - start_time).total_seconds()
        job_name = " + ".join(collector_names)
        summary = (
            f"📡 情報收集完成 [{job_name}]\n"
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


# 保留向後相容
async def run_collection():
    """執行所有收集器（向後相容）"""
    collectors = _build_collectors()
    await _run_collectors(collectors)
