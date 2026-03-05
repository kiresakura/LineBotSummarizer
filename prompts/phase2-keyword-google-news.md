# Phase 2: Keyword Google News Monitor — Claude Code Prompt

請在繆思資料庫 (LineBotSummarizer) 專案中，實作「關鍵字 Google News 監控」。這是主動情報收集系統的第二階段，建立在 Phase 1 的排程器和去重基礎上。

## 前置條件

Phase 1 已完成，專案中已存在：
- `app/scheduler/intel_scheduler.py` — APScheduler 排程器
- `app/collectors/base.py` — BaseCollector 抽象類別
- `app/collectors/rss_collector.py` — RSS 收集器
- `app/collectors/dedup.py` — SQLite 去重模組
- `app/models/intel.py` — IntelItem / IntelSource 資料模型
- `app/pipeline/intel_writer.py` — Notion 情報寫入器
- `app/config.py` — 已有 `intel_*` 設定

## 需要實作的檔案

### 1. `app/config.py` — 追加關鍵字監控設定

在 `Settings` class 追加：

```python
# === 關鍵字監控 (Phase 2) ===
intel_keywords: str = ""                     # 逗號分隔的監控關鍵字
intel_keywords_lang: str = "zh-TW"           # Google News 語言
intel_keywords_geo: str = "TW"               # Google News 地區
intel_keywords_max_results: int = 10         # 每個關鍵字最多抓幾筆
intel_keywords_schedule_hours: int = 4       # 關鍵字監控頻率（可獨立於 RSS）
```

### 2. `app/collectors/keyword_monitor.py` — Google News 關鍵字監控

核心原理：Google News 提供 RSS feed，URL 格式為：
```
https://news.google.com/rss/search?q={keyword}&hl={lang}&gl={geo}&ceid={geo}:{lang}
```

實作要點：
- 繼承 `BaseCollector`
- 從 `intel_keywords` 讀取關鍵字清單（逗號分隔）
- 對每個關鍵字：
  1. 組合 Google News RSS URL（記得 URL encode 關鍵字）
  2. 用 `httpx.AsyncClient` 抓取 RSS
  3. 用 `feedparser` 解析（同步，用 `asyncio.to_thread`）
  4. 取前 N 筆結果
  5. 產生 `IntelItem`，`source` = `IntelSource.GOOGLE_NEWS`，`source_name` = f"Google News: {keyword}"
- Google News RSS 的特殊處理：
  - `entry.link` 通常是 Google 的重定向 URL（`https://news.google.com/rss/articles/...`），需要解析出真實 URL
  - 真實 URL 在 `entry.source.href` 或需要 follow redirect
  - 備用方案：直接存 Google News URL，Phase 4 的 AI 分析時再擷取內容
- 產生 `dedup_hash`：用 `hashlib.sha256((真實url + title).encode()).hexdigest()`
- 支援多關鍵字組合搜尋：`"AI agent"` 精確搜尋、`AI OR LLM` 聯集搜尋
- 錯誤處理：單一關鍵字失敗不影響其他，記 warning log

### 3. `app/collectors/google_news_url_resolver.py` — Google News URL 解析器

Google News RSS 回傳的 URL 是包裝過的重定向 URL，需要解出原始文章 URL：

```python
import httpx
import re
from urllib.parse import unquote

async def resolve_google_news_url(google_url: str) -> str:
    """
    解析 Google News 的重定向 URL，取得原始文章 URL。

    策略：
    1. 嘗試從 URL 參數直接提取（部分格式包含原始 URL）
    2. 嘗試 HEAD request follow redirect
    3. 失敗則回傳原始 Google News URL
    """
    ...
```

注意事項：
- Google 可能會擋太頻繁的請求，加上 rate limit（每次 resolve 間隔 0.5 秒）
- 設 timeout（5 秒），超時就保留 Google News URL
- 加 User-Agent header 避免被擋

### 4. 修改 `app/scheduler/intel_scheduler.py` — 註冊新收集器

在排程器中註冊 `KeywordMonitor`：

```python
from app.collectors.keyword_monitor import KeywordMonitor

# 在 collector 註冊邏輯中加入：
if settings.intel_keywords:
    collectors.append(KeywordMonitor())
```

- 如果 `intel_keywords_schedule_hours` 與 `intel_schedule_hours` 不同，可以新增一個獨立的排程 job
- 或者統一用同一個排程，但每次都跑所有已啟用的 collectors

### 5. `.env.example` — 追加環境變數

```
# === Keyword Monitor (Phase 2) ===
INTEL_KEYWORDS=AI agent,LLM應用,RAG,向量資料庫,Claude,GPT
INTEL_KEYWORDS_LANG=zh-TW
INTEL_KEYWORDS_GEO=TW
INTEL_KEYWORDS_MAX_RESULTS=10
INTEL_KEYWORDS_SCHEDULE_HOURS=4
```

## Google News RSS 範例

搜尋「AI agent」的 RSS URL：
```
https://news.google.com/rss/search?q=AI+agent&hl=zh-TW&gl=TW&ceid=TW:zh-Hant
```

回傳的 entry 結構（feedparser）：
```python
entry.title      # 文章標題
entry.link       # Google News 重定向 URL
entry.published  # 發布時間
entry.summary    # 簡短摘要（HTML）
entry.source     # {'href': '原始來源URL', 'title': '來源名稱'}
```

## 注意事項

1. **Google News 有頻率限制**，不要太頻繁請求（建議每 4 小時以上）
2. **關鍵字支援中文**，URL encode 時要注意
3. **去重要用 Phase 1 建立的 `dedup.py`**，共用同一個 SQLite 資料庫
4. **`content_preview` 欄位**：從 RSS 的 `summary` 提取純文字（去 HTML），截取前 500 字
5. **不要修改 Phase 1 已有的 RSS 收集器邏輯**
6. **寫完後確認 import 鏈正常**：`python -c "from app.collectors.keyword_monitor import KeywordMonitor"`
