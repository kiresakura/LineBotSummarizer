# Phase 1: Scheduler + RSS Collector — Claude Code Prompt

請在現有的繆思資料庫 (LineBotSummarizer) 專案中，實作「排程器 + RSS 情報收集器」。這是主動情報收集系統的第一階段。

## 專案背景

目前專案已有被動收集管道（LINE 群組訊息 → AI 分類 → 寫入 Notion），現在要新增**主動收集管道**：定時排程爬取 RSS 來源，經去重後寫入 Notion 情報資料庫。

## 現有架構（勿修改）

```
app/
├── config.py          # pydantic-settings（已有 LINE/Notion/OpenRouter 設定）
├── main.py            # FastAPI 入口
├── services/
│   ├── ai_service.py  # AIService（OpenRouter，支援 complete / complete_multimodal）
│   ├── line_notify.py # LINE 推播
│   └── url_fetcher.py # URL 內容擷取
├── pipeline/
│   └── writer.py      # NotionWriter（含 TokenBucketRateLimiter）
└── models/
    └── message.py     # RawMessage, ClassifiedMessage
```

## 需要實作的檔案

### 1. `app/config.py` — 新增情報收集設定

在現有的 `Settings` class 裡追加以下欄位（不要動到現有欄位）：

```python
# === 情報收集 ===
intel_enabled: bool = False
intel_schedule_hours: int = 6           # 每幾小時執行一次
intel_rss_feeds: str = ""               # 逗號分隔的 RSS URLs
intel_notion_database_id: str = ""      # 情報專用 Notion Database ID
intel_max_items_per_feed: int = 10      # 每個 feed 最多抓幾筆
intel_dedup_days: int = 7               # 去重時間範圍（天）
```

### 2. `app/models/intel.py` — 情報資料模型

```python
from pydantic import BaseModel
from datetime import datetime
from enum import Enum

class IntelSource(str, Enum):
    RSS = "rss"
    GOOGLE_NEWS = "google_news"
    REDDIT = "reddit"
    GITHUB = "github"

class IntelItem(BaseModel):
    title: str
    url: str
    source: IntelSource
    source_name: str        # e.g. "TechCrunch", "Hacker News"
    summary: str = ""       # AI 生成的摘要（Phase 4 才填）
    published_at: datetime | None = None
    collected_at: datetime  # 收集時間
    tags: list[str] = []
    content_preview: str = ""  # 前 500 字
    dedup_hash: str = ""    # SHA256(url + title) 用於去重
```

### 3. `app/collectors/base.py` — 收集器基底類別

```python
from abc import ABC, abstractmethod
from app.models.intel import IntelItem

class BaseCollector(ABC):
    name: str  # 收集器名稱

    @abstractmethod
    async def collect(self) -> list[IntelItem]:
        """收集情報，回傳 IntelItem 列表"""
        ...
```

### 4. `app/collectors/rss_collector.py` — RSS 收集器

核心邏輯：
- 用 `feedparser` 解析 RSS/Atom feeds
- 從 `intel_rss_feeds` 設定讀取 feed URLs（逗號分隔）
- 每個 feed 最多取 `intel_max_items_per_feed` 筆最新的
- 產生 `dedup_hash = hashlib.sha256((url + title).encode()).hexdigest()`
- 用 `httpx.AsyncClient` 抓 feed（feedparser 本身是同步的，用 `asyncio.to_thread` 包裝）
- 處理各種日期格式（feedparser 的 `published_parsed`）
- 錯誤處理：單一 feed 失敗不影響其他 feed

### 5. `app/collectors/dedup.py` — 去重機制

用 SQLite 做本地去重（輕量、不依賴外部服務）：

- 資料庫檔案路徑：`data/intel_dedup.db`
- 表格：`seen_items (hash TEXT PRIMARY KEY, first_seen TIMESTAMP)`
- `is_duplicate(hash: str) -> bool`：檢查是否已存在
- `mark_seen(hash: str)`：標記為已見
- `cleanup(days: int)`：清理超過 N 天的舊記錄
- 使用 `aiosqlite` 做非同步 SQLite 操作

### 6. `app/scheduler/intel_scheduler.py` — APScheduler 排程器

核心邏輯：
- 使用 `apscheduler.schedulers.asyncio.AsyncIOScheduler`
- 在 FastAPI 的 `lifespan` 裡啟動/關閉
- 排程工作：每 `intel_schedule_hours` 小時執行一次 `run_collection()`
- `run_collection()` 流程：
  1. 遍歷所有已註冊的 collectors
  2. 各 collector 的 `collect()` 取得 IntelItems
  3. 透過 dedup 過濾已見項目
  4. 寫入 Notion 情報資料庫（用現有的 NotionWriter 邏輯但寫到 `intel_notion_database_id`）
  5. 用 `line_notify.py` 發送收集摘要給管理員
- 加上 try/except，任何錯誤都 log + 通知管理員，不要讓排程掛掉

### 7. `app/main.py` — 整合排程器

在現有的 FastAPI app 加入 lifespan：

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.intel_enabled:
        from app.scheduler.intel_scheduler import start_scheduler, stop_scheduler
        await start_scheduler()
    yield
    if settings.intel_enabled:
        await stop_scheduler()

app = FastAPI(lifespan=lifespan)
```

### 8. `.env.example` — 追加情報收集相關環境變數

```
# === Intel Collection (Phase 1) ===
INTEL_ENABLED=false
INTEL_SCHEDULE_HOURS=6
INTEL_RSS_FEEDS=https://hnrss.org/frontpage,https://feeds.feedburner.com/TechCrunch,https://www.reddit.com/r/artificial/.rss
INTEL_NOTION_DATABASE_ID=your_intel_database_id_here
INTEL_MAX_ITEMS_PER_FEED=10
INTEL_DEDUP_DAYS=7
```

### 9. `app/pipeline/intel_writer.py` — 情報寫入 Notion

基於現有 `writer.py` 的模式，但寫入情報資料庫：
- Notion Database 欄位：Title (title), URL (url), Source (select), Tags (multi_select), Published (date), Collected (date), Preview (rich_text)
- 複用 `TokenBucketRateLimiter`
- 批次寫入，避免超過 Notion rate limit

### 10. `pyproject.toml` — 新增依賴

追加（不要刪除現有的）：
```
feedparser = "^6.0"
apscheduler = "^3.10"
aiosqlite = "^0.20"
```

## 注意事項

1. **所有新檔案都要有完整的 type hints 和 docstrings**
2. **使用 `logging` 而非 `print`**
3. **全部使用 async/await**
4. **確保 `data/` 目錄存在（SQLite 檔案位置），在 `Dockerfile` 或 init 時建立**
5. **寫完後跑一次 `python -c "from app.scheduler.intel_scheduler import ..."` 確認 import 正常**
6. **不要修改現有的被動收集管道（webhook、pipeline 等）**
