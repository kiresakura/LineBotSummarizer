"""去重機制 — 使用 SQLite 本地去重，避免重複寫入 Notion"""

import logging
from datetime import datetime, timedelta
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

DB_DIR = Path("data")
DB_PATH = DB_DIR / "intel_dedup.db"


class DedupStore:
    """非同步 SQLite 去重存儲"""

    def __init__(self):
        self._db: aiosqlite.Connection | None = None

    async def init(self):
        """初始化資料庫（建表）"""
        DB_DIR.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(DB_PATH))
        await self._db.execute(
            "CREATE TABLE IF NOT EXISTS seen_items ("
            "  hash TEXT PRIMARY KEY,"
            "  first_seen TIMESTAMP NOT NULL"
            ")"
        )
        await self._db.commit()
        logger.info(f"去重資料庫已初始化: {DB_PATH}")

    async def is_duplicate(self, hash_val: str) -> bool:
        """檢查是否已存在"""
        assert self._db, "DedupStore 尚未初始化，請先呼叫 init()"
        cursor = await self._db.execute(
            "SELECT 1 FROM seen_items WHERE hash = ?", (hash_val,)
        )
        return await cursor.fetchone() is not None

    async def mark_seen(self, hash_val: str):
        """標記為已見"""
        assert self._db, "DedupStore 尚未初始化，請先呼叫 init()"
        await self._db.execute(
            "INSERT OR IGNORE INTO seen_items (hash, first_seen) VALUES (?, ?)",
            (hash_val, datetime.now().isoformat()),
        )
        await self._db.commit()

    async def cleanup(self, days: int):
        """清理超過 N 天的舊記錄"""
        assert self._db, "DedupStore 尚未初始化，請先呼叫 init()"
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        cursor = await self._db.execute(
            "DELETE FROM seen_items WHERE first_seen < ?", (cutoff,)
        )
        await self._db.commit()
        logger.info(f"去重清理: 移除 {cursor.rowcount} 筆超過 {days} 天的記錄")

    async def close(self):
        """關閉資料庫連線"""
        if self._db:
            await self._db.close()
            self._db = None
