# 🧭 Lorekeeper

[![ci](https://github.com/kiresakura/lorekeeper/actions/workflows/ci.yml/badge.svg)](https://github.com/kiresakura/lorekeeper/actions/workflows/ci.yml)
[![secret-scan](https://github.com/kiresakura/lorekeeper/actions/workflows/secret-scan.yml/badge.svg)](https://github.com/kiresakura/lorekeeper/actions/workflows/secret-scan.yml)
![python](https://img.shields.io/badge/python-3.11%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)

[English](README.md) | **繁體中文**

把吵雜的群組對話，自動整理成結構化、可搜尋的知識庫。

Lorekeeper 是一條全非同步（async）的 pipeline：從聊天**來源（source）**接收訊息，
用多模態 LLM 萃取*完整的知識點*（不是摘要），再寫入一個或多個知識**輸出（sink）**。
來源、輸出、LLM 都能從設定切換——核心 pipeline 只依賴介面。

```
 source ───▶ enrich ───▶ aggregate ───▶ classify ───▶ sink(s)
 (LINE)      (爬取        (防抖           (多模態        (Notion /
             URL)         連發訊息)       模型路由)      Markdown)
```

> 想 30 秒內、不用任何帳號就看它跑起來？→ [`lorekeeper demo`](#快速開始)。

---

## 為什麼這樣設計

重點不是「一個把訊息寫進 Notion 的 LINE bot」——而是**核心程式碼完全不知道 LINE 或 Notion 的存在**。
Pipeline 只依賴三個 Protocol（`lorekeeper/ports.py`）：

| Port（介面） | 職責 | 已內建的 adapter |
|------|------|------|
| `MessageSource`（透過 `MessageHandler`） | 產生正規化的 `InboundMessage` | LINE、Telegram |
| `LLMProvider` | 分類 + 知識萃取 | OpenRouter、**Mock**（免金鑰） |
| `KnowledgeSink` | 持久化 `KnowledgeEntry` | Notion、**Markdown**（免帳號）、JSONL |

這套 **ports & adapters（六角架構）** 帶來三個實際好處：

1. **從設定切換整合對象** — `SINKS=["markdown"]`、`LLM_PROVIDER=mock`，不用改任何程式碼。
2. **零金鑰即可執行** — Mock LLM + Markdown sink 讓整條流程在本地可跑、可測（CI 就是這樣跑的）。
3. **幾行就能擴充** — 每個 seam 都內建多個 adapter 作為佐證（來源：LINE、Telegram．輸出：Notion、Markdown、JSONL．LLM：OpenRouter、Mock）；再加新的也不會動到 pipeline。

```
            ┌──────────────────────── core (no vendor imports) ───────────────────────┐
 LINE  ─────▶  MessageHandler ─▶ Enricher ─▶ Aggregator ─▶ Orchestrator ─▶ KnowledgeSink ───▶ Notion
 webhook │                                                    │     ▲                     └▶ Markdown
         │                                              Classifier  │
         │                                                    ▼     │
         └──────────────────────────────────────────  LLMProvider (OpenRouter / Mock)
                         adapters ◀────── depend on ──────▶ ports ◀────── implement ────── adapters
```

---

## 快速開始

```bash
git clone https://github.com/kiresakura/lorekeeper.git
cd lorekeeper
pip install -e ".[dev]"
```

**零金鑰直接看它跑**（Mock LLM → Markdown）：

```bash
lorekeeper demo            # 產生一筆知識條目到 ./knowledge/*.md
```

**正式執行**（LINE 來源 → Notion 輸出 → OpenRouter）：

```bash
cp .env.example .env       # 填入 LINE / Notion / OpenRouter 金鑰
lorekeeper serve           # 或：uvicorn lorekeeper.app:app --port 8000
```

接著把 LINE channel 的 Webhook URL 指到 `https://your-host/webhook`。

---

## 功能特色

- **多模態萃取** — 文字、圖片、音訊在同一批處理；依模態做模型路由。
- **成本導向模型路由** — 文字／影像用便宜模型，只有混合／複雜批次才動用較強模型（可設定）。
- **完整知識萃取，不是摘要** — prompt 經過調校，盡量保留每個細節、程式碼區塊與步驟。
- **智慧聚合** — 依對話做防抖（debounce），讓一串連發訊息合併成一筆連貫的條目。
- **SSRF 強化的 URL 爬取** — yt-dlp（1000+ 影片站）+ BeautifulSoup，外層有 fetch 防護：封鎖私有／loopback／雲端 metadata 目標，並限制回應大小。
- **穩健的 Notion 寫入** — 令牌桶限流（2.5 req/s）+ 指數退避重試，遵守 Notion 的 100 區塊／2000 字元上限。
- **多重輸出（fan-out）** — 同一筆條目可同時寫入 Notion *和*本地 Markdown／JSONL。

## 如何擴充

新增一個 sink，就是實作一個方法。以下是實際會 ship 的 `JsonlSink`：

```python
# lorekeeper/adapters/jsonl_sink.py
import asyncio
from pathlib import Path
from lorekeeper.models import KnowledgeEntry

class JsonlSink:
    name = "jsonl"

    def __init__(self, path: str = "./knowledge.jsonl"):
        self.path = Path(path)

    async def write(self, entry: KnowledgeEntry) -> None:
        line = entry.model_dump_json(exclude={"source_messages"})
        await asyncio.to_thread(self._append, line)

    def _append(self, line: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
```

它在 `lorekeeper/app.py:build_sinks` 中註冊；設定 `SINKS=["jsonl"]` 即可啟用。再加 sink 完全不動 pipeline。

---

## 設定

全部透過環境變數（見 [`.env.example`](.env.example)）：

| 變數 | 用途 |
|------|------|
| `SOURCE` | 訊息來源：`line` 或 `telegram` |
| `SINKS` | sink 的 JSON 陣列：`["notion"]`、`["markdown"]`、`["jsonl"]`，可組合 |
| `LLM_PROVIDER` | `openrouter`（真實）或 `mock`（免金鑰，供本地／CI） |
| `LINE_CHANNEL_SECRET` / `LINE_CHANNEL_ACCESS_TOKEN` | LINE Messaging API（`SOURCE=line` 時） |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_WEBHOOK_SECRET` | Telegram Bot API（`SOURCE=telegram` 時） |
| `ADMIN_LINE_USER_ID` | 選填——錯誤通知的收件人 |
| `NOTION_API_KEY` / `NOTION_DATABASE_ID` | Notion sink |
| `MARKDOWN_OUTPUT_DIR` / `JSONL_OUTPUT_PATH` | Markdown／JSONL sink 輸出位置 |
| `OPENROUTER_API_KEY` | OpenRouter 金鑰；`AI_MODEL_*` 可覆寫路由 |
| `COOLDOWN_SECONDS` / `MAX_BATCH_SIZE` | 聚合調校 |
| `NOISE_FILTER_ENABLED` | 丟棄被判為「噪音」的批次 |

**Notion DB 結構**（sink 預期這些屬性）：`Title`(title)、`Category`(select)、
`Importance`(select)、`Tags`(multi-select)、`Source`(select)、`Date`(date)、
`Knowledge`(rich text)、`Has Action Items`(checkbox)、`URLs`(url)。

---

## 專案結構

```
lorekeeper/
├── ports.py            # pipeline 依賴的 3 個 Protocol（與框架無關）
├── models.py           # 與供應商無關的 domain models
├── config.py           # 設定 + adapter 選擇
├── app.py              # 組裝根（composition root）：依設定 wire 各 adapter
├── cli.py              # `lorekeeper demo` / `serve`
├── pipeline/           # enricher → aggregator → classifier → orchestrator
├── adapters/           # LINE、Telegram、Notion、Markdown、JSONL、OpenRouter、Mock —— 唯一的供應商程式碼
└── services/           # safe_http（SSRF 防護）、url_fetcher
tests/                  # 36 個測試：純邏輯、SSRF 防護、debounce、classifier、sinks、DI/webhook
```

## 測試

```bash
pytest            # 36 個測試，免網路、免金鑰
ruff check . && ruff format --check .
```

測試大量倚賴 Mock LLM 與純函式，因此可離線、可重現地執行。CI（GitHub Actions）
每次 push 都會跑 lint 與 [gitleaks](.github/workflows/secret-scan.yml) 金鑰掃描。

## 安全性與隱私

- Webhook 請求以 HMAC-SHA256 驗章，密鑰未設定時**一律拒絕（fail closed）**。
- URL 爬取有 SSRF 防護（`lorekeeper/services/safe_http.py`）。
- 金鑰只走環境變數；`.env` 與 `.git` 透過 `.dockerignore` 排除在 Docker image 之外。
- 本服務會處理第三方聊天內容——運營者須取得成員知情同意，並檢視當地隱私法規。見 [`SECURITY.md`](SECURITY.md)。

## 部署

```bash
docker build -t lorekeeper .
docker run -p 8000:8000 --env-file .env lorekeeper   # 以非 root 使用者執行
```

可乾淨部署到 Railway / Render / 任何容器平台。中度活躍群組的預估成本：
**< NT$200／月**（OpenRouter 用量 + 小型主機；Notion 與 LINE 免費額度）。

## 授權

[MIT](LICENSE) © kiresakura
