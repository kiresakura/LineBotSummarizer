# LINE Bot × Notion 知識庫整合系統 — 技術架構規劃

## 1. 專案概述

### 目標
建立一個 LINE Bot，即時收集群組中的混合型訊息（文字、圖片、檔案、連結），透過 AI 自動分類與摘要後，寫入 Notion 作為結構化知識庫。

### 核心價值
- **不遺漏**：群組裡有價值的討論不再被淹沒
- **自動整理**：AI 判斷主題、重要性，省去手動分類
- **可檢索**：Notion 知識庫支援全文搜尋與關聯查詢

---

## 2. 系統架構總覽

```
┌─────────────┐     Webhook (HTTPS)     ┌──────────────────┐
│  LINE Group  │ ──────────────────────▶ │   Web Server     │
│  Messages    │                         │   (FastAPI)      │
└─────────────┘                         └────────┬─────────┘
                                                 │
                                          ┌──────▼──────┐
                                          │  Message     │
                                          │  Queue       │
                                          │  (Redis)     │
                                          └──────┬───────┘
                                                 │
                                    ┌────────────▼────────────┐
                                    │   Processing Pipeline   │
                                    │                         │
                                    │  1. 訊息解析 & 暫存      │
                                    │  2. AI 分類 & 摘要       │
                                    │  3. 去重 & 合併相關訊息   │
                                    │  4. 寫入 Notion          │
                                    └────────────┬────────────┘
                                                 │
                              ┌──────────────────┼──────────────────┐
                              │                  │                  │
                       ┌──────▼──────┐    ┌──────▼──────┐   ┌──────▼──────┐
                       │   Notion    │    │   SQLite    │   │  OpenAI /   │
                       │   知識庫     │    │   本地 DB    │   │  Claude API │
                       └─────────────┘    └─────────────┘   └─────────────┘
```

---

## 3. 技術棧推薦

### 語言 & 框架
| 層級 | 技術選擇 | 理由 |
|------|----------|------|
| **語言** | Python 3.11+ | LINE SDK 官方支援完善、AI 生態系最豐富 |
| **Web 框架** | FastAPI | 非同步原生支援、效能好、自動 API 文件 |
| **任務佇列** | Redis + Celery（或輕量版用 asyncio Queue） | 解耦 Webhook 接收與訊息處理 |
| **資料庫** | SQLite（初期）→ PostgreSQL（擴展時） | 訊息暫存、去重追蹤、處理狀態 |
| **AI 引擎** | Claude API（推薦）或 OpenAI GPT-4o | 分類與摘要的核心 |
| **部署** | Railway / Render / AWS Lambda | 免維護、自動擴展、有免費額度 |

### 關鍵 SDK & 套件
```
line-bot-sdk>=3.0       # LINE Messaging API v3
notion-client>=2.0      # Notion 官方 Python SDK
fastapi>=0.100          # Web 框架
uvicorn                 # ASGI 伺服器
redis / aioredis        # 訊息佇列（進階）
anthropic>=0.30         # Claude AI API
httpx                   # 非同步 HTTP 請求
pydantic>=2.0           # 資料驗證
apscheduler             # 定時任務（每日摘要等）
```

---

## 4. 核心模組設計

### 4.1 Webhook 接收層（即時回應，< 1 秒）

```python
# 設計原則：快速回應 200，將訊息丟入佇列後立刻返回
@app.post("/webhook")
async def handle_webhook(request: Request):
    # 1. 驗證 LINE 簽名
    signature = request.headers.get("X-Line-Signature")
    body = await request.body()
    verify_signature(body, signature)

    # 2. 解析事件，丟入處理佇列
    events = parse_events(body)
    for event in events:
        await message_queue.enqueue(event)

    # 3. 立刻返回 200（LINE 要求快速回應）
    return {"status": "ok"}
```

**重要限制**：
- LINE Webhook 期望在幾秒內收到 2xx 回應，否則可能重送
- 所有耗時操作（AI 分析、Notion 寫入）必須非同步處理

### 4.2 訊息處理管線（Pipeline）

```
接收原始事件
    │
    ▼
[Stage 1] 訊息解析器
    - 提取文字內容
    - 下載圖片 → OCR（如需要）
    - 解析 URL → 擷取網頁標題 & 摘要
    - 提取檔案資訊
    │
    ▼
[Stage 2] 訊息聚合器（Aggregator）
    - 收集同一討論串的相關訊息
    - 5 分鐘視窗內同主題訊息合併
    - 避免每條訊息都觸發一次 AI 分析
    │
    ▼
[Stage 3] AI 分類 & 摘要引擎
    - 判斷主題分類（技術、新聞、討論、閒聊...）
    - 判斷重要程度（高/中/低/噪音）
    - 生成摘要（1-3 句話）
    - 提取關鍵詞 & 標籤
    │
    ▼
[Stage 4] Notion 寫入器
    - 根據分類決定目標 Database
    - 建立或更新 Page
    - 附加原始訊息作為子區塊
    │
    ▼
[Stage 5] 回饋（可選）
    - 在群組回覆確認已記錄
    - 每日/每週自動發送摘要到群組
```

### 4.3 AI 分類與摘要設計

**Prompt 策略（核心競爭力）**

```python
CLASSIFICATION_PROMPT = """
你是一個群組訊息分類助手。請分析以下訊息並回傳 JSON。

規則：
1. category：從以下選擇最適合的 →
   [技術分享, 新聞資訊, 工具推薦, 問題討論, 學習資源, 專案更新, 靈感想法, 其他]
2. importance：high / medium / low / noise
   - noise = 打招呼、貼圖、無實質內容
3. summary：用 1-3 句繁體中文摘要重點
4. tags：提取 3-5 個關鍵詞標籤
5. action_items：如果有待辦事項，列出

---
群組名稱：{group_name}
發送者：{sender_name}
時間：{timestamp}
訊息內容：
{messages}
---

回傳 JSON 格式：
{
  "category": "...",
  "importance": "...",
  "summary": "...",
  "tags": ["...", "..."],
  "action_items": ["..."] // 如果沒有則為空陣列
}
"""
```

**成本控制策略**：
- `noise` 等級的訊息不寫入 Notion（省 API 呼叫）
- 聚合後再分析，減少 AI API 呼叫次數
- 使用較便宜的模型做初篩（如 Claude Haiku），複雜內容再用進階模型

### 4.4 Notion 知識庫結構

#### 主 Database：`📚 知識庫`

| 欄位名稱 | 類型 | 說明 |
|----------|------|------|
| Title | Title | 摘要標題 |
| Category | Select | 主題分類 |
| Importance | Select | 重要程度（🔴高 🟡中 🟢低） |
| Tags | Multi-select | 關鍵詞標籤 |
| Source Group | Select | 來源群組 |
| Sender | Rich Text | 發送者 |
| Date | Date | 訊息時間 |
| Summary | Rich Text | AI 生成摘要 |
| Original Messages | Rich Text | 原始訊息內容 |
| URLs | URL | 相關連結 |
| Has Action Items | Checkbox | 是否含待辦事項 |
| Status | Status | 未讀 / 已讀 / 已處理 |

#### 輔助 Database：`📅 每日摘要`

| 欄位名稱 | 類型 | 說明 |
|----------|------|------|
| Title | Title | 日期標題 (e.g. 2026-03-04 群組日報) |
| Date | Date | 日期 |
| Group | Select | 群組名稱 |
| Total Messages | Number | 當日訊息數 |
| Key Topics | Rich Text | AI 統整的當日重點 |
| Related Items | Relation | 關聯到知識庫 Database |

---

## 5. 關鍵技術挑戰 & 解決方案

### 5.1 Notion API Rate Limit（平均 3 req/s）

**問題**：群組訊息量大時，逐條寫入會觸發 429 錯誤。

**解決方案**：
```python
class NotionRateLimiter:
    """令牌桶限流器"""
    def __init__(self, rate=2.5):  # 留 buffer，不跑滿 3/s
        self.rate = rate
        self.tokens = rate
        self.last_refill = time.monotonic()

    async def acquire(self):
        while self.tokens < 1:
            await asyncio.sleep(0.1)
            self._refill()
        self.tokens -= 1

    async def write_to_notion(self, data):
        await self.acquire()
        try:
            return await notion_client.pages.create(**data)
        except APIResponseError as e:
            if e.status == 429:
                retry_after = int(e.headers.get("Retry-After", 1))
                await asyncio.sleep(retry_after)
                return await self.write_to_notion(data)  # retry
            raise
```

### 5.2 訊息聚合避免碎片化

**問題**：群組聊天是連續流，單條訊息缺少上下文。

**解決方案 — 滑動視窗聚合器**：
```python
class MessageAggregator:
    """將相關訊息合併後再送去 AI 分析"""

    WINDOW_SIZE = 300  # 5 分鐘視窗
    MIN_BATCH = 3      # 至少累積 3 條才處理
    MAX_BATCH = 20     # 最多 20 條一批

    def __init__(self):
        self.buffers: dict[str, list] = {}  # group_id -> messages
        self.timers: dict[str, float] = {}

    async def add_message(self, group_id: str, message: dict):
        if group_id not in self.buffers:
            self.buffers[group_id] = []
            self.timers[group_id] = time.time()

        self.buffers[group_id].append(message)

        # 觸發條件：達到上限 or 超過時間視窗
        if (len(self.buffers[group_id]) >= self.MAX_BATCH or
            time.time() - self.timers[group_id] > self.WINDOW_SIZE):
            batch = self.buffers.pop(group_id)
            self.timers.pop(group_id)
            await self.process_batch(group_id, batch)
```

### 5.3 圖片與檔案處理

```python
async def process_image(event):
    """下載圖片 → 存儲 → 可選 OCR"""
    # 1. 從 LINE 下載圖片
    content = await line_api.get_message_content(event.message.id)

    # 2. 上傳到雲端儲存（S3 / Cloudflare R2）
    url = await upload_to_storage(content, f"{event.message.id}.jpg")

    # 3. 如果需要，做 OCR 提取文字
    if should_ocr(event):
        text = await ocr_service.extract(content)
        return {"type": "image", "url": url, "ocr_text": text}

    return {"type": "image", "url": url}
```

### 5.4 連結內容擷取

```python
async def extract_url_content(url: str) -> dict:
    """擷取 URL 的標題、描述、主要內容"""
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, timeout=10, follow_redirects=True)

        soup = BeautifulSoup(resp.text, "html.parser")

        return {
            "title": soup.title.string if soup.title else "",
            "description": get_meta_description(soup),
            "content": extract_main_content(soup),  # 用 readability 演算法
            "url": str(resp.url),
        }
    except Exception:
        return {"url": url, "title": "", "description": "", "content": ""}
```

---

## 6. 部署架構

### 推薦方案：Railway（初期）

```
┌─────────────────────────────────────────────┐
│                 Railway                      │
│                                              │
│  ┌─────────────┐    ┌──────────────────┐    │
│  │  FastAPI     │    │  Redis           │    │
│  │  Service     │    │  (訊息佇列)       │    │
│  │  (Web)       │◄──►│                  │    │
│  └──────┬───────┘    └──────────────────┘    │
│         │                                    │
│  ┌──────▼───────┐    ┌──────────────────┐    │
│  │  Worker      │    │  SQLite /        │    │
│  │  Service     │    │  PostgreSQL      │    │
│  │  (處理管線)   │◄──►│  (狀態追蹤)       │    │
│  └──────────────┘    └──────────────────┘    │
└─────────────────────────────────────────────┘
          │                        │
          ▼                        ▼
   ┌──────────────┐        ┌──────────────┐
   │  Notion API  │        │  Claude API  │
   └──────────────┘        └──────────────┘
```

**為什麼選 Railway**：
- 支援多服務部署（Web + Worker + Redis + DB）
- 從 GitHub 自動部署
- 免費額度足夠開發與低流量使用
- 需要時可一鍵遷移到 AWS/GCP

### 進階方案（高流量時）

| 元件 | 替代方案 | 時機 |
|------|---------|------|
| Web Server | AWS Lambda + API Gateway | 日訊息 > 10,000 |
| 佇列 | AWS SQS / RabbitMQ | 需要持久化佇列 |
| 資料庫 | PostgreSQL (Supabase) | 多群組管理 |
| 儲存 | Cloudflare R2 | 大量圖片/檔案 |

---

## 7. 專案目錄結構

```
linebot-notion-kb/
├── app/
│   ├── __init__.py
│   ├── main.py               # FastAPI 入口
│   ├── config.py              # 環境變數 & 設定
│   ├── webhook/
│   │   ├── __init__.py
│   │   ├── handler.py         # Webhook 路由
│   │   └── validator.py       # 簽名驗證
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── parser.py          # 訊息解析
│   │   ├── aggregator.py      # 訊息聚合
│   │   ├── classifier.py      # AI 分類 & 摘要
│   │   └── writer.py          # Notion 寫入
│   ├── services/
│   │   ├── __init__.py
│   │   ├── line_service.py    # LINE API 封裝
│   │   ├── notion_service.py  # Notion API 封裝 + 限流
│   │   ├── ai_service.py      # AI API 封裝
│   │   ├── storage_service.py # 檔案儲存
│   │   └── url_extractor.py   # URL 內容擷取
│   ├── models/
│   │   ├── __init__.py
│   │   ├── message.py         # 訊息資料模型
│   │   └── classification.py  # 分類結果模型
│   ├── database/
│   │   ├── __init__.py
│   │   ├── db.py              # 資料庫連線
│   │   └── models.py          # ORM 模型
│   └── scheduler/
│       ├── __init__.py
│       └── daily_digest.py    # 每日摘要排程
├── tests/
│   ├── test_parser.py
│   ├── test_aggregator.py
│   ├── test_classifier.py
│   └── test_writer.py
├── .env.example
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── railway.toml
└── README.md
```

---

## 8. 開發里程碑

### Phase 1：基礎骨架（1-2 週）
- [ ] 建立 FastAPI 專案 + LINE Webhook 驗證
- [ ] 接收文字訊息並 log 到本地
- [ ] 連接 Notion API，手動寫入測試資料
- [ ] 部署到 Railway，確認 Webhook 通路

### Phase 2：核心管線（2-3 週）
- [ ] 實作訊息解析器（文字、URL、圖片）
- [ ] 實作 AI 分類 & 摘要（Claude API）
- [ ] 實作 Notion 寫入器 + 限流機制
- [ ] 端到端測試：群組訊息 → Notion 知識庫

### Phase 3：進階功能（2-3 週）
- [ ] 訊息聚合器（避免碎片化）
- [ ] 圖片 OCR + 檔案處理
- [ ] URL 內容擷取 & 摘要
- [ ] 每日摘要排程 + 群組回饋

### Phase 4：優化 & 穩定（持續）
- [ ] 錯誤處理 & 重試機制完善
- [ ] AI Prompt 迭代優化
- [ ] 監控 & 告警（Sentry / Uptime）
- [ ] 多群組支援 & 管理後台

---

## 9. 成本估算（月）

| 項目 | 預估用量 | 費用 |
|------|---------|------|
| Railway 部署 | 低流量 | 免費 ~ $5/月 |
| Claude API（Haiku） | ~50,000 token/天 | ~$3-5/月 |
| Notion API | 免費 | $0 |
| LINE Messaging API | 免費訊息方案 | $0（500 則推播/月） |
| Cloudflare R2 | 少量圖片 | 免費額度內 |
| **合計** | | **$3-10/月** |

*註：以一個中等活躍群組（每天 ~100 條訊息）估算*

---

## 10. 潛在風險 & 對策

| 風險 | 影響 | 對策 |
|------|------|------|
| LINE Webhook 漏訊 | 遺失訊息 | 啟用 Webhook redelivery + 本地去重 |
| Notion API 變更 | 寫入失敗 | 用官方 SDK + 本地暫存佇列 |
| AI 分類不準 | 知識庫品質差 | Prompt 持續迭代 + 人工回饋修正 |
| 群組訊息量暴增 | 處理延遲 | 訊息聚合 + 限流 + 彈性擴展 |
| 隱私 & 合規 | 法律風險 | 群組成員知情同意、資料加密 |

---

*文件版本：v1.0 | 建立日期：2026-03-04*
