"""Stage 3: AI 分類 & 摘要引擎（支援多模態）"""

import json
import re
import logging
from app.models.message import RawMessage, ClassifiedMessage, Importance, MessageType
from app.services.ai_service import AIService, ContentType

logger = logging.getLogger(__name__)

URL_PATTERN = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+', re.IGNORECASE)

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

MULTIMODAL_ADDENDUM = """

## 附加媒體內容

本批訊息包含 {media_count} 個媒體檔案（{media_types}）。
請一併分析附加的圖片/音訊內容，將其納入分類與摘要中。
若圖片包含文字（螢幕截圖、文件等），請提取關鍵內容。
若音訊包含語音，請摘要其內容。"""


class MessageClassifier:
    """使用 AI 對聚合後的訊息進行分類與摘要（支援圖片/音訊）"""

    def __init__(self):
        self.ai = AIService()

    async def classify(
        self, group_id: str, messages: list[RawMessage]
    ) -> ClassifiedMessage | None:
        """對一批訊息進行 AI 分類"""
        formatted = self._format_messages(messages)
        time_range = self._get_time_range(messages)

        # 偵測媒體內容
        media_items = self._extract_media(messages)
        content_type = self._determine_content_type(media_items)

        # 組合 prompt
        prompt = CLASSIFICATION_PROMPT.format(
            group_id=group_id,
            time_range=time_range,
            formatted_messages=formatted,
        )

        if media_items:
            media_type_names = set(item["type"] for item in media_items)
            prompt += MULTIMODAL_ADDENDUM.format(
                media_count=len(media_items),
                media_types="、".join("圖片" if t == "image" else "音訊" for t in media_type_names),
            )

        # 呼叫 AI
        try:
            if media_items:
                response = await self.ai.complete_multimodal(
                    text_prompt=prompt,
                    media_items=media_items,
                    content_type=content_type,
                )
            else:
                response = await self.ai.complete(prompt, content_type=content_type)

            result = self._parse_response(response)
            if result is None:
                return None

            # 提取 URL
            urls = []
            for msg in messages:
                if msg.text:
                    urls.extend(URL_PATTERN.findall(msg.text))

            return ClassifiedMessage(
                category=result.get("category", "其他"),
                importance=Importance(result.get("importance", "low")),
                summary=result.get("summary", ""),
                tags=result.get("tags", []),
                action_items=result.get("action_items", []),
                original_messages=messages,
                group_name=group_id,
                urls_found=urls,
            )

        except Exception as e:
            logger.error(f"AI 分類失敗: {e}", exc_info=True)
            return None

    def _extract_media(self, messages: list[RawMessage]) -> list[dict]:
        """從批次訊息中提取已下載的媒體"""
        media_items = []
        for msg in messages:
            if not msg.has_media:
                continue
            if msg.message_type == MessageType.IMAGE:
                media_items.append({
                    "type": "image",
                    "data": msg.media_content,
                    "mime_type": msg.media_mime_type or "image/jpeg",
                })
            elif msg.message_type == MessageType.AUDIO:
                media_items.append({
                    "type": "audio",
                    "data": msg.media_content,
                    "mime_type": msg.media_mime_type or "audio/m4a",
                })
        return media_items

    def _determine_content_type(self, media_items: list[dict]) -> ContentType:
        """根據媒體類型決定模型路由"""
        if not media_items:
            return ContentType.TEXT
        types = set(item["type"] for item in media_items)
        if types == {"image"}:
            return ContentType.IMAGE
        elif types == {"audio"}:
            return ContentType.AUDIO
        else:
            return ContentType.COMPLEX

    def _format_messages(self, messages: list[RawMessage]) -> str:
        """將訊息格式化為 AI 可讀的文字"""
        lines = []
        for msg in messages:
            time_str = msg.timestamp.strftime("%H:%M")
            sender = msg.user_name or msg.user_id[:8]
            if msg.text:
                content = msg.text
            elif msg.message_type == MessageType.IMAGE:
                content = "[圖片" + ("，已附加供分析" if msg.has_media else "") + "]"
            elif msg.message_type == MessageType.AUDIO:
                content = "[音訊" + ("，已附加供分析" if msg.has_media else "") + "]"
            else:
                content = f"[{msg.message_type.value}]"
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
            return json.loads(response)
        except json.JSONDecodeError:
            match = re.search(r'```(?:json)?\s*(.*?)\s*```', response, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    pass
            logger.error(f"無法解析 AI 回應: {response[:200]}")
            return None
