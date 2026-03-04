"""Stage 3: AI 分類 & 摘要引擎"""

import json
import logging
from app.config import get_settings
from app.models.message import RawMessage, ClassifiedMessage, Importance
from app.services.ai_service import AIService

logger = logging.getLogger(__name__)


CLASSIFICATION_PROMPT = """你是一個 LINE 群組訊息分類助手。請分析以下一批訊息並回傳 JSON。

## 分類規則

1. **category**：從以下選擇最適合的一個
   → 技術分享, 新聞資訊, 工具推薦, 問題討論, 學習資源, 專案更新, 靈感想法, 其他

2. **importance**：判斷這批訊息的價值
   - high：重要決策、關鍵資訊、需要行動的事項
   - medium：有參考價值的討論或分享
   - low：一般閒聊但有些內容
   - noise：純粹打招呼、貼圖、無實質內容（這類不會被保存）

3. **summary**：用 1-3 句繁體中文摘要整批訊息的重點

4. **tags**：提取 3-5 個關鍵詞標籤（繁體中文）

5. **action_items**：如果有待辦事項或需要跟進的事，列出來

## 訊息內容

群組 ID：{group_id}
時間範圍：{time_range}

{formatted_messages}

## 回傳格式（嚴格 JSON）

```json
{{
  "category": "技術分享",
  "importance": "medium",
  "summary": "摘要內容...",
  "tags": ["標籤1", "標籤2"],
  "action_items": []
}}
```

只回傳 JSON，不要其他文字。"""


class MessageClassifier:
    """使用 AI 對聚合後的訊息進行分類與摘要"""

    def __init__(self):
        self.ai = AIService()

    async def classify(
        self, group_id: str, messages: list[RawMessage]
    ) -> ClassifiedMessage | None:
        """對一批訊息進行 AI 分類"""
        settings = get_settings()

        # 格式化訊息
        formatted = self._format_messages(messages)
        time_range = self._get_time_range(messages)

        prompt = CLASSIFICATION_PROMPT.format(
            group_id=group_id,
            time_range=time_range,
            formatted_messages=formatted,
        )

        # 呼叫 AI
        try:
            response = await self.ai.complete(prompt, model=settings.ai_model)
            result = self._parse_response(response)

            if result is None:
                return None

            # 提取訊息中的 URL
            urls = []
            import re
            url_pattern = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+')
            for msg in messages:
                urls.extend(url_pattern.findall(msg.text))

            return ClassifiedMessage(
                category=result.get("category", "其他"),
                importance=Importance(result.get("importance", "low")),
                summary=result.get("summary", ""),
                tags=result.get("tags", []),
                action_items=result.get("action_items", []),
                original_messages=messages,
                group_name=group_id,  # 後續可用 LINE API 取得群組名稱
                urls_found=urls,
            )

        except Exception as e:
            logger.error(f"AI 分類失敗: {e}", exc_info=True)
            return None

    def _format_messages(self, messages: list[RawMessage]) -> str:
        """將訊息格式化為 AI 可讀的文字"""
        lines = []
        for msg in messages:
            time_str = msg.timestamp.strftime("%H:%M")
            sender = msg.user_name or msg.user_id[:8]
            content = msg.text or f"[{msg.message_type.value}]"
            lines.append(f"[{time_str}] {sender}: {content}")
        return "\n".join(lines)

    def _get_time_range(self, messages: list[RawMessage]) -> str:
        """取得訊息的時間範圍"""
        if not messages:
            return "N/A"
        start = min(m.timestamp for m in messages)
        end = max(m.timestamp for m in messages)
        return f"{start.strftime('%Y-%m-%d %H:%M')} ~ {end.strftime('%H:%M')}"

    def _parse_response(self, response: str) -> dict | None:
        """解析 AI 回傳的 JSON"""
        try:
            # 嘗試直接解析
            return json.loads(response)
        except json.JSONDecodeError:
            # 嘗試從 markdown code block 中提取
            import re
            match = re.search(r'```(?:json)?\s*(.*?)\s*```', response, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    pass
            logger.error(f"無法解析 AI 回應: {response[:200]}")
            return None
