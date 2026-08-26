"""Pipeline stage 3 — AI classification & full knowledge extraction (multimodal).

Extracts *complete* knowledge points (not a summary) from a batch, routing to an
appropriate model via the injected `LLMProvider`. Provider-neutral: it never
imports an SDK, only `lorekeeper.ports`.
"""

import json
import logging
import re

from lorekeeper.models import (
    Importance,
    InboundMessage,
    KnowledgeEntry,
    MediaPayload,
    MessageType,
)
from lorekeeper.ports import ContentType, LLMProvider

logger = logging.getLogger(__name__)

URL_PATTERN = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+', re.IGNORECASE)

CLASSIFICATION_PROMPT = """你是一個群組知識庫整理助手。請分析以下一批訊息，完整提取所有知識點並回傳 JSON。

## 分類規則

1. **category**：從以下選擇最適合的一個
   → 技術分享, 新聞資訊, 工具推薦, 問題討論, 學習資源, 專案更新, 靈感想法, 其他

2. **importance**：判斷這批訊息的價值
   - high：重要決策、關鍵資訊、需要行動的事項
   - medium：有參考價值的討論或分享
   - low：一般閒聊但有些內容
   - noise：純粹打招呼、貼圖、無實質內容

3. **knowledge_points**：用繁體中文**完整整理**訊息中的所有知識點。這不是摘要，而是完整的知識歸納。
   - 列出每一個知識點，不要省略任何有價值的資訊
   - 如果包含連結內容，請深入整理該內容的**所有**核心知識點、技術細節、步驟、結論
   - 使用清晰的結構化格式（標題、子項目、條列式）
   - 保留具體的數據、名詞、技術術語、版本號等細節
   - 如有程式碼片段，完整保留
   - 長度不限，寧可冗餘也不要遺漏
   - 目標：讓讀者不需要回去看原始訊息，就能獲得完整的知識

4. **media_descriptions**：如果有圖片或音訊，為每個媒體提供詳盡的文字描述：
   - 圖片：完整描述畫面內容。若含文字（截圖、文件、程式碼），**逐字提取所有可見文字**
   - 音訊：**完整逐句轉錄**語音內容，不要摘要
   - 沒有媒體則回傳空陣列

5. **title**：為這批知識點取一個簡潔明確的標題（繁體中文，30字以內）

6. **tags**：提取 3-5 個關鍵詞標籤（繁體中文）

7. **action_items**：如果有待辦事項或需要跟進的事，列出來

## 訊息內容

對話 ID：{conversation_id}
時間範圍：{time_range}

{formatted_messages}

## 回傳格式（嚴格 JSON）

```json
{{
  "category": "技術分享",
  "importance": "medium",
  "title": "知識點標題",
  "knowledge_points": "完整知識點內容...",
  "media_descriptions": ["圖片1的完整文字描述...", "音訊1的完整轉錄..."],
  "tags": ["標籤1", "標籤2"],
  "action_items": []
}}
```

只回傳 JSON，不要其他文字。"""

MULTIMODAL_ADDENDUM = """

## 附加媒體內容

本批訊息包含 {media_count} 個媒體檔案（{media_types}）。
請一併分析附加的圖片/音訊內容，將其納入分類與知識點整理中。

**重要：最大化提取媒體中的資訊**
- 若圖片包含文字（螢幕截圖、文件、程式碼、對話紀錄等），請**逐字提取所有可見文字**，不要省略
- 若圖片是圖表、架構圖等，請詳細描述所有元素與關係
- 若音訊包含語音，請**完整逐句轉錄**，不要摘要
- 將所有提取的內容放入 media_descriptions 陣列中，每個媒體一個字串"""


class MessageClassifier:
    def __init__(self, llm: LLMProvider):
        self.llm = llm

    async def classify(
        self, conversation_id: str, messages: list[InboundMessage]
    ) -> KnowledgeEntry | None:
        formatted = self._format_messages(messages)
        time_range = self._time_range(messages)
        media = [m.media for m in messages if m.has_media and m.media is not None]
        content_type = self._content_type(media)

        prompt = CLASSIFICATION_PROMPT.format(
            conversation_id=conversation_id,
            time_range=time_range,
            formatted_messages=formatted,
        )

        url_text = self._format_url_contents(messages)
        if url_text:
            prompt += url_text

        if media:
            kinds = {"image" if m.is_image else "audio" for m in media}
            prompt += MULTIMODAL_ADDENDUM.format(
                media_count=len(media),
                media_types="、".join(
                    "圖片" if k == "image" else "音訊" for k in kinds
                ),
            )

        max_tokens = 4096 if media else 2048
        try:
            if media:
                response = await self.llm.complete_multimodal(
                    prompt, media, content_type=content_type, max_tokens=max_tokens
                )
            else:
                response = await self.llm.complete(
                    prompt, content_type=content_type, max_tokens=max_tokens
                )

            result = self._parse_response(response)
            if result is None:
                return None

            urls: list[str] = []
            for msg in messages:
                if msg.text:
                    urls.extend(URL_PATTERN.findall(msg.text))

            return KnowledgeEntry(
                category=result.get("category", "其他"),
                importance=self._parse_importance(result.get("importance")),
                title=result.get("title", ""),
                knowledge=result.get("knowledge_points", ""),
                media_descriptions=result.get("media_descriptions", []),
                tags=result.get("tags", []),
                action_items=result.get("action_items", []),
                source_messages=messages,
                conversation_label=conversation_id,
                urls=urls,
            )
        except Exception:
            logger.exception("AI 分類失敗")
            return None

    # --- helpers ---

    @staticmethod
    def _parse_importance(value: str | None) -> Importance:
        try:
            return Importance(value)
        except (ValueError, TypeError):
            return Importance.LOW

    def _format_url_contents(self, messages: list[InboundMessage]) -> str:
        contents = [uc for msg in messages for uc in msg.url_contents]
        if not contents:
            return ""
        parts = ["\n\n## 連結內容（已爬取）\n"]
        for i, uc in enumerate(contents, 1):
            parts.append(f"### 連結 {i}: {uc.title}")
            parts.append(f"URL: {uc.url}")
            parts.append(uc.content)
            parts.append("")
        parts.append(
            "請根據以上連結內容進行深入統整，完整提取所有知識點，不要省略任何細節。"
        )
        return "\n".join(parts)

    @staticmethod
    def _content_type(media: list[MediaPayload]) -> ContentType:
        if not media:
            return ContentType.TEXT
        kinds = {"image" if m.is_image else "audio" for m in media}
        if kinds == {"image"}:
            return ContentType.IMAGE
        if kinds == {"audio"}:
            return ContentType.AUDIO
        return ContentType.COMPLEX

    @staticmethod
    def _format_messages(messages: list[InboundMessage]) -> str:
        lines = []
        for msg in messages:
            time_str = msg.timestamp.strftime("%H:%M")
            sender = msg.sender_name or msg.sender_id[:8]
            if msg.text:
                content = msg.text
            elif msg.type == MessageType.IMAGE:
                content = "[圖片" + ("，已附加供分析" if msg.has_media else "") + "]"
            elif msg.type == MessageType.AUDIO:
                content = "[音訊" + ("，已附加供分析" if msg.has_media else "") + "]"
            else:
                content = f"[{msg.type.value}]"
            lines.append(f"[{time_str}] {sender}: {content}")
        return "\n".join(lines)

    @staticmethod
    def _time_range(messages: list[InboundMessage]) -> str:
        if not messages:
            return "N/A"
        start = min(m.timestamp for m in messages)
        end = max(m.timestamp for m in messages)
        return f"{start.strftime('%Y-%m-%d %H:%M')} ~ {end.strftime('%H:%M')}"

    @staticmethod
    def _parse_response(response: str) -> dict | None:
        try:
            return json.loads(response)
        except (json.JSONDecodeError, TypeError):
            match = re.search(r"```(?:json)?\s*(.*?)\s*```", response or "", re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except json.JSONDecodeError:
                    pass
            logger.error(f"無法解析 AI 回應: {str(response)[:200]}")
            return None
