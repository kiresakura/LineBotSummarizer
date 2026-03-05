# Phase 3: Reddit / GitHub Trending — Claude Code Prompt

請在繆思資料庫 (LineBotSummarizer) 專案中，實作「Reddit 和 GitHub Trending 收集器」。這是主動情報收集系統的第三階段。

## 前置條件

Phase 1 & 2 已完成，專案中已存在：
- `app/scheduler/intel_scheduler.py` — APScheduler 排程器（含 collector 註冊機制）
- `app/collectors/base.py` — BaseCollector 抽象類別
- `app/collectors/rss_collector.py` — RSS 收集器
- `app/collectors/keyword_monitor.py` — Google News 關鍵字監控
- `app/collectors/dedup.py` — SQLite 去重模組
- `app/models/intel.py` — IntelItem / IntelSource（已有 REDDIT, GITHUB enum）
- `app/pipeline/intel_writer.py` — Notion 情報寫入器

## 需要實作的檔案

### 1. `app/config.py` — 追加 Reddit/GitHub 設定

在 `Settings` class 追加：

```python
# === Reddit / GitHub Trending (Phase 3) ===
intel_reddit_enabled: bool = False
intel_reddit_subs: str = ""                  # 逗號分隔的 subreddit 名稱
intel_reddit_sort: str = "hot"               # hot / top / new
intel_reddit_time_filter: str = "day"        # hour / day / week（用於 top）
intel_reddit_max_per_sub: int = 10           # 每個 sub 最多抓幾筆
intel_github_enabled: bool = False
intel_github_languages: str = ""             # 逗號分隔：python,typescript,rust
intel_github_since: str = "daily"            # daily / weekly / monthly
intel_github_max_repos: int = 15
```

### 2. `app/collectors/reddit_collector.py` — Reddit 收集器

**核心原理：Reddit 提供免費的 JSON API，不需要 API key。**

URL 格式：`https://www.reddit.com/r/{subreddit}/{sort}.json?t={time_filter}&limit={limit}`

實作要點：
- 繼承 `BaseCollector`
- 從 `intel_reddit_subs` 讀取 subreddit 清單
- 對每個 subreddit：
  1. 用 `httpx.AsyncClient` GET 上述 URL
  2. **必須設定 User-Agent**：`User-Agent: MuseDB-IntelCollector/1.0`（Reddit 會擋沒有 UA 的請求）
  3. 解析 JSON response：`data["data"]["children"]` 是貼文列表
  4. 每個貼文 `child["data"]` 包含：
     - `title` — 標題
     - `url` — 連結（外部連結或 Reddit 內部）
     - `permalink` — Reddit 討論頁 permalink
     - `selftext` — 自發文的內文（如果是 self post）
     - `score` — 分數（upvotes - downvotes）
     - `num_comments` — 留言數
     - `created_utc` — Unix timestamp
     - `subreddit` — subreddit 名稱
  5. 產生 `IntelItem`：
     - `url` 用 `https://reddit.com{permalink}`（討論頁）
     - `content_preview` 截取 `selftext` 前 500 字，或留空
     - `tags` 加入 subreddit 名稱和 score 區間（如 `score>100`）
     - `source_name` = f"r/{subreddit}"
- **Rate limit**：請求間隔至少 2 秒（Reddit API 限制 60 req/min for unauth）
- 錯誤處理：403/429 時跳過並 log warning

### 3. `app/collectors/github_collector.py` — GitHub Trending 收集器

**核心原理：GitHub Trending 沒有官方 API，需要爬取網頁或使用非官方 API。**

推薦方案：使用 GitHub 非官方 trending API 或直接爬取。

**方案 A（推薦）：爬取 GitHub Trending 頁面**

URL：`https://github.com/trending/{language}?since={since}`

```python
import httpx
from selectolax.parser import HTMLParser  # 輕量 HTML parser，比 bs4 快

async def collect(self) -> list[IntelItem]:
    for language in languages:
        url = f"https://github.com/trending/{language}?since={self.since}"
        resp = await client.get(url, headers={"User-Agent": "..."})
        tree = HTMLParser(resp.text)

        for article in tree.css("article.Box-row"):
            # 解析 repo 名稱
            h2 = article.css_first("h2 a")
            repo_path = h2.attributes.get("href", "").strip("/")  # "owner/repo"
            repo_url = f"https://github.com/{repo_path}"

            # 解析描述
            p = article.css_first("p")
            description = p.text(strip=True) if p else ""

            # 解析星星數（today stars）
            spans = article.css("span.d-inline-block.float-sm-right")
            today_stars = spans[0].text(strip=True) if spans else ""

            # 解析程式語言
            lang_span = article.css_first("span[itemprop='programmingLanguage']")
            lang = lang_span.text(strip=True) if lang_span else language

            yield IntelItem(
                title=repo_path,
                url=repo_url,
                source=IntelSource.GITHUB,
                source_name=f"GitHub Trending ({lang})",
                content_preview=description,
                tags=[lang, "trending", today_stars],
                ...
            )
```

**方案 B（備用）：GitHub REST API 搜尋**

如果爬取被擋，改用 GitHub Search API（不需要 token，但有 rate limit 10 req/min）：
```
https://api.github.com/search/repositories?q=created:>2026-03-04&sort=stars&order=desc&per_page=15
```

實作要點：
- 優先用方案 A，失敗時 fallback 到方案 B
- 每個語言之間間隔 2 秒
- `dedup_hash` 用 `sha256(repo_url)`
- GitHub Trending 頁面結構可能改變，要做好 CSS selector 失敗的容錯

### 4. `pyproject.toml` — 新增依賴

```
selectolax = "^0.3"     # 輕量 HTML parser，用於 GitHub Trending 爬取
```

如果選擇方案 B，則不需要 selectolax，改用純 JSON 解析。

### 5. 修改 `app/scheduler/intel_scheduler.py` — 註冊新收集器

```python
from app.collectors.reddit_collector import RedditCollector
from app.collectors.github_collector import GitHubCollector

if settings.intel_reddit_enabled and settings.intel_reddit_subs:
    collectors.append(RedditCollector())

if settings.intel_github_enabled:
    collectors.append(GitHubCollector())
```

### 6. `.env.example` — 追加環境變數

```
# === Reddit (Phase 3) ===
INTEL_REDDIT_ENABLED=false
INTEL_REDDIT_SUBS=artificial,MachineLearning,LocalLLaMA,langchain,singularity
INTEL_REDDIT_SORT=hot
INTEL_REDDIT_TIME_FILTER=day
INTEL_REDDIT_MAX_PER_SUB=10

# === GitHub Trending (Phase 3) ===
INTEL_GITHUB_ENABLED=false
INTEL_GITHUB_LANGUAGES=python,typescript,rust
INTEL_GITHUB_SINCE=daily
INTEL_GITHUB_MAX_REPOS=15
```

## 注意事項

1. **Reddit JSON API 不需要 API key**，但一定要設 User-Agent，否則會被擋（403）
2. **GitHub Trending 沒有官方 API**，HTML 結構可能變動，做好容錯
3. **兩個 collector 都要做 rate limit**：Reddit 2 秒間隔，GitHub 2 秒間隔
4. **去重共用 Phase 1 的 `dedup.py`**
5. **不要安裝 `praw`**（Reddit 官方 SDK），JSON API 更輕量且不需要 credentials
6. **GitHub 可能有反爬機制**，如果連續被 429，自動 backoff 並 log
7. **寫完後確認 import**：
   ```bash
   python -c "from app.collectors.reddit_collector import RedditCollector"
   python -c "from app.collectors.github_collector import GitHubCollector"
   ```
