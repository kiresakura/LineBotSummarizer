# Phase 4: AI Trend Analysis + Daily Intel Digest — Claude Code Prompt

請在繆思資料庫 (LineBotSummarizer) 專案中，實作「AI 趨勢分析 + 每日情報摘要推播」。這是主動情報收集系統的最後階段，將所有收集到的情報經 AI 分析後，產生每日摘要推播到 LINE。

## 前置條件

Phase 1-3 已完成，專案中已存在：
- `app/scheduler/intel_scheduler.py` — APScheduler 排程器
- `app/collectors/` — RSS、Google News、Reddit、GitHub 四個收集器
- `app/collectors/dedup.py` — SQLite 去重
- `app/models/intel.py` — IntelItem / IntelSource
- `app/pipeline/intel_writer.py` — Notion 情報寫入
- `app/services/ai_service.py` — AIService（OpenRouter，支援 `complete()` 方法）
- `app/services/line_notify.py` — LINE 推播

## 需要實作的檔案

### 1. `app/config.py` — 追加 AI 分析 & 摘要設定

在 `Settings` class 追加：

```python
# === AI Analysis & Daily Digest (Phase 4) ===
intel_ai_analysis_enabled: bool = False       # 是否啟用 AI 分析
intel_digest_enabled: bool = False            # 是否啟用每日摘要
intel_digest_schedule_cron: str = "0 9 * * *" # 每天早上 9 點推播摘要
intel_digest_line_group_id: str = ""          # 摘要推播到哪個 LINE 群組（留空則推給 admin）
intel_digest_max_items: int = 20              # 摘要最多包含幾筆情報
intel_digest_lookback_hours: int = 24         # 回溯幾小時的情報
```

### 2. `app/services/intel_analyzer.py` — 情報 AI 分析服務

這是核心分析引擎，用 AI 對收集到的情報做深度分析。

```python
from app.services.ai_service import AIService, ContentType
from app.models.intel import IntelItem

class IntelAnalyzer:
    def __init__(self):
        self.ai = AIService()

    async def analyze_item(self, item: IntelItem) -> IntelItem:
        """
        對單一情報項目做 AI 分析，填充 summary 和 tags。
        """
        prompt = f"""你是一位科技情報分析師。請分析以下情報並提供：
1. 一段 2-3 句的中文摘要（精準、有洞見）
2. 3-5 個分類標籤（中文）

情報標題：{item.title}
來源：{item.source_name}
內容預覽：{item.content_preview[:1000] if item.content_preview else "（無內容預覽）"}
URL：{item.url}

請用以下 JSON 格式回覆：
{{"summary": "摘要內容", "tags": ["標籤1", "標籤2", "標籤3"]}}

只回覆 JSON，不要加其他文字。"""

        try:
            result = await self.ai.complete(prompt, content_type=ContentType.TEXT)
            parsed = json.loads(result)
            item.summary = parsed.get("summary", "")
            item.tags = parsed.get("tags", item.tags)
        except Exception as e:
            logger.warning(f"AI 分析失敗 ({item.title}): {e}")
            item.summary = item.content_preview[:200] if item.content_preview else item.title
        return item

    async def generate_digest(self, items: list[IntelItem]) -> str:
        """
        對一批情報生成每日趨勢摘要。
        """
        items_text = "\n".join([
            f"- [{item.source_name}] {item.title}\n  摘要：{item.summary or item.content_preview[:100]}\n  URL：{item.url}"
            for item in items[:20]
        ])

        prompt = f"""你是繆思資料庫的 AI 情報分析師。請根據以下今日收集的 {len(items)} 筆情報，撰寫一份每日趨勢摘要。

## 今日收集情報

{items_text}

## 輸出要求

請用以下格式撰寫摘要（純文字，適合 LINE 訊息閱讀）：

📊 繆思資料庫｜每日情報摘要
📅 日期

🔥 今日趨勢焦點（1-2 段，150字以內）
→ 概述今天最重要的趨勢和發現

📌 重點情報 TOP 5
1. [標題] — 一句話說明為什麼重要
2. ...

🏷️ 熱門標籤：#標籤1 #標籤2 #標籤3

💡 分析師觀點（2-3 句）
→ 這些趨勢對團隊工作的啟示

---
共收集 {len(items)} 筆情報｜完整內容請見 Notion 情報庫"""

        try:
            digest = await self.ai.complete(prompt, content_type=ContentType.TEXT, max_tokens=2000)
            return digest
        except Exception as e:
            logger.error(f"生成每日摘要失敗: {e}")
            return f"⚠️ 今日情報摘要生成失敗\n共收集 {len(items)} 筆情報，請直接查看 Notion 情報庫。"
```

### 3. `app/services/intel_digest_store.py` — 情報暫存（用於摘要回溯）

因為情報寫入 Notion 後不容易批次回查，需要一個本地暫存供摘要生成用：

```python
import aiosqlite
from app.models.intel import IntelItem

class IntelDigestStore:
    """
    本地 SQLite 暫存最近的情報項目，供每日摘要回溯使用。
    資料庫：data/intel_digest.db
    表格：digest_items (id, title, url, source, source_name, summary, tags_json, published_at, collected_at)
    """

    async def store_items(self, items: list[IntelItem]):
        """批次儲存情報項目"""
        ...

    async def get_recent_items(self, hours: int = 24, limit: int = 50) -> list[IntelItem]:
        """取得最近 N 小時內的情報"""
        ...

    async def cleanup(self, days: int = 7):
        """清理超過 N 天的舊資料"""
        ...
```

### 4. 修改 `app/scheduler/intel_scheduler.py` — 整合 AI 分析 + 摘要排程

在現有排程器中加入：

**A. 收集後的 AI 分析步驟**

在 `run_collection()` 中，寫入 Notion 之前插入 AI 分析：

```python
from app.services.intel_analyzer import IntelAnalyzer
from app.services.intel_digest_store import IntelDigestStore

analyzer = IntelAnalyzer()
digest_store = IntelDigestStore()

async def run_collection():
    # ... 收集 & 去重（已有邏輯）...
    new_items = [...]  # 去重後的新情報

    # Phase 4: AI 分析
    if settings.intel_ai_analysis_enabled:
        analyzed = []
        for item in new_items:
            analyzed_item = await analyzer.analyze_item(item)
            analyzed.append(analyzed_item)
            await asyncio.sleep(1)  # AI API rate limit
        new_items = analyzed

    # 寫入 Notion（已有邏輯）
    await intel_writer.write_batch(new_items)

    # Phase 4: 暫存供摘要用
    if settings.intel_digest_enabled:
        await digest_store.store_items(new_items)
```

**B. 新增每日摘要排程 Job**

```python
from apscheduler.triggers.cron import CronTrigger

async def run_daily_digest():
    """每日情報摘要推播"""
    items = await digest_store.get_recent_items(
        hours=settings.intel_digest_lookback_hours,
        limit=settings.intel_digest_max_items
    )
    if not items:
        logger.info("無新情報，跳過每日摘要")
        return

    digest_text = await analyzer.generate_digest(items)

    # 推播到 LINE
    from app.services.line_notify import push_message
    target_id = settings.intel_digest_line_group_id or settings.admin_line_user_id
    await push_message(target_id, digest_text)

    # 同時寫入 Notion 摘要資料庫
    await write_digest_to_notion(digest_text, len(items))

    logger.info(f"每日摘要已推播，含 {len(items)} 筆情報")

# 在 start_scheduler() 中加入摘要 Job
if settings.intel_digest_enabled:
    # 解析 cron 表達式，例如 "0 9 * * *"
    parts = settings.intel_digest_schedule_cron.split()
    scheduler.add_job(
        run_daily_digest,
        CronTrigger(
            minute=parts[0], hour=parts[1],
            day=parts[2], month=parts[3], day_of_week=parts[4]
        ),
        id="daily_intel_digest",
        replace_existing=True,
    )
```

### 5. `app/pipeline/intel_writer.py` — 追加摘要寫入 Notion

新增一個函式，把每日摘要寫到 `notion_digest_database_id`（與 LINE 群組摘要共用同一個 Database）：

```python
async def write_digest_to_notion(digest_text: str, item_count: int):
    """
    把每日情報摘要寫入 Notion 摘要資料庫。
    欄位：Title = "情報摘要 YYYY-MM-DD", Content = digest_text, Type = "intel_digest", Count = item_count
    """
    ...
```

### 6. `.env.example` — 追加環境變數

```
# === AI Analysis & Daily Digest (Phase 4) ===
INTEL_AI_ANALYSIS_ENABLED=false
INTEL_DIGEST_ENABLED=false
INTEL_DIGEST_SCHEDULE_CRON=0 9 * * *
INTEL_DIGEST_LINE_GROUP_ID=
INTEL_DIGEST_MAX_ITEMS=20
INTEL_DIGEST_LOOKBACK_HOURS=24
```

### 7. 手動觸發端點（除錯用）

在 `app/main.py` 加入除錯端點（只在 DEBUG 模式下啟用）：

```python
@app.post("/debug/intel/collect")
async def debug_collect():
    """手動觸發一次情報收集"""
    if not settings.intel_enabled:
        return {"error": "Intel collection is disabled"}
    from app.scheduler.intel_scheduler import run_collection
    await run_collection()
    return {"status": "ok"}

@app.post("/debug/intel/digest")
async def debug_digest():
    """手動觸發每日摘要"""
    if not settings.intel_digest_enabled:
        return {"error": "Digest is disabled"}
    from app.scheduler.intel_scheduler import run_daily_digest
    await run_daily_digest()
    return {"status": "ok"}
```

## AI 分析的 Token 成本估算

假設每天收集 50 筆情報：
- `analyze_item()` 每筆 ~500 tokens input + ~200 tokens output = ~700 tokens
- `generate_digest()` ~3000 tokens input + ~800 tokens output = ~3800 tokens
- 每日總計：50 × 700 + 3800 ≈ **38,800 tokens/day**
- 使用 DeepSeek V3 (text model) 價格極低，月成本約 $0.5-1

## 注意事項

1. **AI 分析是可選的**（`intel_ai_analysis_enabled`），關閉時直接用原始 content_preview
2. **摘要推播時間可自訂** via cron 表達式，預設每天 9:00
3. **LINE 訊息有 5000 字限制**，摘要要控制長度（prompt 裡已限制）
4. **AI API 呼叫要做 rate limit**，每次分析間隔 1 秒
5. **digest_store 要定期清理**（7 天以上的舊資料），可以在摘要 job 最後順便清理
6. **JSON parsing 要做 fallback**：AI 回傳的 JSON 可能格式不正確，用 try/except 處理
7. **不要修改 Phase 1-3 的收集器邏輯**，只在排程器和寫入器層面整合
8. **寫完後跑完整 import 檢查**：
   ```bash
   python -c "from app.services.intel_analyzer import IntelAnalyzer"
   python -c "from app.services.intel_digest_store import IntelDigestStore"
   python -c "from app.scheduler.intel_scheduler import run_daily_digest"
   ```
