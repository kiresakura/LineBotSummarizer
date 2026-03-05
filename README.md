# LINE Bot Summarizer

LINE 群組訊息自動知識庫系統 — 將群組對話即時分類、完整整理知識點，寫入 Notion 知識庫。

支援文字、圖片、音訊多模態訊息分析，自動爬取 URL 內容（YouTube / BiliBili 字幕 + 一般網頁）。

## 架構概覽

```
LINE Group → Webhook → 即時聚合 → AI 知識點整理 → Notion Database
                         ↓
                    URL 爬取 / 媒體下載
```

```
┌──────────┐     ┌──────────┐     ┌───────────┐     ┌──────────┐     ┌────────┐
│  LINE    │────▶│ Webhook  │────▶│Aggregator │────▶│Classifier│────▶│ Notion │
│  Groups  │     │ (FastAPI)│     │ (3s 防抖) │     │(OpenRouter)│   │ Writer │
└──────────┘     └──────────┘     └───────────┘     └──────────┘     └────────┘
                                       │                                  │
                                  ┌────┴────┐                        ┌────┴────┐
                                  │ Parser  │                        │  LINE   │
                                  │URL爬取  │                        │ 通知回覆│
                                  │媒體下載 │                        └─────────┘
                                  └─────────┘
```

## 功能特色

- **即時處理** — 3 秒防抖機制，連發訊息自動合併後立即處理
- **完整知識點整理** — 不做摘要，完整提取所有知識點歸納到知識庫
- **URL 內容爬取** — 自動爬取連結內容：
  - YouTube：影片標題 + 描述 + 字幕逐字稿
  - BiliBili：影片資訊 + 字幕 + 標籤
  - 一般網頁：標題 + Meta 描述 + 正文內容
- **多模態 AI 分析** — 支援文字、圖片辨識、音訊辨識
- **智慧模型路由** — 依內容類型自動選擇最高 CP 值模型
- **Notion 知識庫** — 結構化寫入，含分類標籤、待辦事項、原始訊息
- **群組即時回覆** — 處理完成後自動回覆群組確認通知
- **管理員通知** — 錯誤發生時私訊管理員
- **噪音過濾** — 自動跳過貼圖、打招呼等低價值訊息

## AI 模型路由

透過 [OpenRouter](https://openrouter.ai/) 統一 API，依內容類型自動選擇模型：

| 內容類型 | 預設模型 | 輸入價格/百萬token |
|---------|---------|-------------------|
| 純文字 | DeepSeek V3.2 | $0.25 |
| 圖片 | Gemini 3.1 Flash Lite | $0.25 |
| 音訊 | Gemini 3.1 Flash Lite | $0.075 |
| 混合/複雜 | Gemini 3.1 Pro | $2.00 |

## 技術棧

| 層級 | 技術 |
|------|------|
| Web 框架 | FastAPI + Uvicorn |
| AI 引擎 | OpenRouter API（OpenAI SDK 相容） |
| 多模態 | 圖片辨識 + 音訊辨識（Gemini） |
| LINE 整合 | LINE Messaging API v3 |
| 資料寫入 | Notion API |
| 資料驗證 | Pydantic v2 |
| 網頁爬取 | httpx + BeautifulSoup |
| 部署 | Railway |
| 語言 | Python 3.11+ |

## 專案結構

```
├── app/
│   ├── main.py              # FastAPI 應用程式入口
│   ├── config.py            # 環境變數與模型路由設定
│   ├── webhook/handler.py   # LINE Webhook 驗證與路由
│   ├── models/message.py    # 資料模型（含媒體內容）
│   ├── pipeline/
│   │   ├── parser.py        # 訊息解析、URL 爬取、媒體下載
│   │   ├── aggregator.py    # 即時聚合（3 秒防抖）
│   │   ├── classifier.py    # AI 多模態分類與知識點整理
│   │   └── writer.py        # Notion 寫入（含速率限制）
│   └── services/
│       ├── ai_service.py    # OpenRouter API 封裝（文字+多模態）
│       ├── url_fetcher.py   # URL 內容爬取（YouTube/BiliBili/網頁）
│       └── line_notify.py   # LINE 推播通知（群組回覆+管理員通知）
├── Dockerfile
├── pyproject.toml
└── architecture.md          # 詳細技術架構文件
```

## 快速開始

### 1. 安裝

```bash
git clone https://github.com/kiresakura/LineBotSummarizer.git
cd LineBotSummarizer
pip install .
```

### 2. 設定環境變數

```bash
cp .env.example .env
# 編輯 .env 填入各項 API Key
```

### 3. 啟動

```bash
# 本機開發
uvicorn app.main:app --reload --port 8000

# Docker
docker build -t linebot-summarizer .
docker run -p 8000:8000 --env-file .env linebot-summarizer
```

### 4. 設定 LINE Webhook

將 `https://your-domain.com/webhook` 填入 LINE Developers Console 的 Webhook URL。

## 處理流程

1. **接收** — LINE 群組訊息觸發 Webhook，HMAC-SHA256 驗簽
2. **解析** — 提取文字內容、爬取 URL（YouTube 字幕 / BiliBili / 一般網頁）、下載圖片/音訊
3. **聚合** — 3 秒防抖機制，連發訊息自動合併為一批
4. **路由** — 偵測批次中的媒體類型，自動選擇最適合的 AI 模型
5. **整理** — AI 完整提取所有知識點，含分類、重要性、標籤、待辦事項
6. **寫入** — Token Bucket 速率限制下寫入 Notion，含重試與退避機制
7. **通知** — 回覆群組確認已寫入，錯誤時私訊管理員

## AI 分類維度

| 維度 | 選項 |
|------|------|
| **分類** | 技術分享、新聞資訊、工具推薦、問題討論、學習資源、專案更新、靈感想法、其他 |
| **重要性** | 🔴 高（關鍵決策）、🟡 中（有討論價值）、🟢 低（一般閒聊）、噪音（過濾） |

## 環境變數

| 變數 | 說明 |
|------|------|
| `LINE_CHANNEL_SECRET` | LINE Channel Secret |
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Channel Access Token |
| `NOTION_API_KEY` | Notion Integration Token |
| `NOTION_DATABASE_ID` | 主資料庫 ID |
| `NOTION_DIGEST_DATABASE_ID` | 每日摘要資料庫 ID |
| `OPENROUTER_API_KEY` | OpenRouter API Key |
| `ADMIN_LINE_USER_ID` | 管理員 LINE User ID（錯誤通知用） |
| `AI_MODEL_TEXT` | 純文字模型（預設: deepseek/deepseek-v3.2） |
| `AI_MODEL_VISION` | 圖片模型（預設: gemini-3.1-flash-lite） |
| `AI_MODEL_AUDIO` | 音訊模型（預設: gemini-3.1-flash-lite） |
| `AI_MODEL_COMPLEX` | 複雜/混合模型（預設: gemini-3-pro） |

## 預估成本

| 項目 | 月費 |
|------|------|
| OpenRouter API | ~NT$15-50 |
| 部署主機 (Railway) | NT$0-150 |
| Notion / LINE API | 免費 |
| **合計** | **< NT$200/月** |
