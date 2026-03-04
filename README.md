# LINE Bot Summarizer

LINE 群組訊息自動摘要系統 — 將群組對話即時分類、摘要，寫入 Notion 知識庫。

## 架構概覽

```
LINE Group → Webhook → 聚合 → AI 分類/摘要 → Notion Database
```

```
┌──────────┐     ┌──────────┐     ┌───────────┐     ┌──────────┐     ┌────────┐
│  LINE    │────▶│ Webhook  │────▶│Aggregator │────▶│Classifier│────▶│ Notion │
│  Groups  │     │ (FastAPI)│     │(5min/20msg)│    │ (Claude) │     │ Writer │
└──────────┘     └──────────┘     └───────────┘     └──────────┘     └────────┘
```

## 功能特色

- **即時訊息擷取** — LINE Webhook 自動接收群組訊息
- **智慧聚合** — 滑動視窗（5 分鐘 / 最多 20 則）避免碎片化分析
- **AI 分類與摘要** — Claude AI 自動分類、評估重要性、產生摘要
- **Notion 知識庫** — 結構化寫入，含分類標籤、待辦事項、原始訊息
- **噪音過濾** — 自動跳過貼圖、打招呼等低價值訊息
- **成本優化** — 預設使用 Haiku 模型，複雜內容才切換 Sonnet

## 技術棧

| 層級 | 技術 |
|------|------|
| Web 框架 | FastAPI + Uvicorn |
| AI 引擎 | Anthropic Claude API |
| LINE 整合 | LINE Messaging API v3 |
| 資料寫入 | Notion API |
| 資料驗證 | Pydantic v2 |
| 容器化 | Docker |
| 語言 | Python 3.11+ |

## 專案結構

```
├── app/
│   ├── main.py              # FastAPI 應用程式入口
│   ├── config.py            # 環境變數設定
│   ├── webhook/handler.py   # LINE Webhook 驗證與路由
│   ├── models/message.py    # 資料模型
│   ├── pipeline/
│   │   ├── parser.py        # 訊息解析、URL 擷取
│   │   ├── aggregator.py    # 滑動視窗聚合
│   │   ├── classifier.py    # AI 分類與摘要
│   │   └── writer.py        # Notion 寫入（含速率限制）
│   └── services/
│       └── ai_service.py    # Claude API 封裝
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

1. **接收** — LINE 群組訊息觸發 Webhook，HMAC-SHA256 驗簽後佇列化
2. **聚合** — 同群組訊息在 5 分鐘視窗內累積（最少 3 則、最多 20 則）
3. **分類** — Claude AI 分析後回傳分類、重要性、摘要、標籤、待辦事項
4. **寫入** — Token Bucket 速率限制下寫入 Notion，含重試與退避機制

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
| `ANTHROPIC_API_KEY` | Anthropic API Key |
| `AI_MODEL` | 預設 AI 模型（default: claude-haiku-4-5-20251001） |
| `AI_MODEL_ADVANCED` | 進階 AI 模型（default: claude-sonnet-4-5-20250929） |

## 預估成本

| 項目 | 月費 |
|------|------|
| Claude API (Haiku) | ~NT$100-150 |
| 部署主機 (Railway) | NT$0-150 |
| Notion / LINE API | 免費 |
| **合計** | **< NT$300/月** |
