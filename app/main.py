"""FastAPI 應用入口"""

import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI

from app.config import get_settings
from app.webhook.handler import router as webhook_router
from app.pipeline.aggregator import MessageAggregator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# 全域共用的訊息聚合器
aggregator = MessageAggregator()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用生命週期管理"""
    settings = get_settings()
    logger.info("LINE Bot 知識庫助手啟動中...")
    logger.info(f"   AI Models: text={settings.ai_model_text}, vision={settings.ai_model_vision}, audio={settings.ai_model_audio}")
    logger.info(f"   聚合視窗: {settings.aggregation_window_seconds}s")

    # 啟動聚合器的定時沖洗
    await aggregator.start()

    # 啟動情報收集排程器
    if settings.intel_enabled:
        from app.scheduler.intel_scheduler import start_scheduler
        await start_scheduler()
        logger.info("   情報收集: 已啟動")
    else:
        logger.info("   情報收集: 未啟用 (INTEL_ENABLED=false)")

    yield

    # 關閉情報收集排程器
    if settings.intel_enabled:
        from app.scheduler.intel_scheduler import stop_scheduler
        await stop_scheduler()

    # 關閉時沖洗剩餘訊息
    await aggregator.flush_all()
    logger.info("LINE Bot 知識庫助手已關閉")


app = FastAPI(
    title="LINE Bot × Notion 知識庫",
    description="自動收集 LINE 群組訊息，AI 分類後寫入 Notion 知識庫",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(webhook_router)


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "linebot-notion-kb"}
