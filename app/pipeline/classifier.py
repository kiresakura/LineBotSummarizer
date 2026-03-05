"""Stage 3: AI 分類 & 摘要引擎（支援多模態）"""

import json
import re
import logging
from app.models.message import RawMessage, ClassifiedMessage, Importance, MessageType
from app.services.ai_service import AIService, ContentType

logger = logging.getLogger(__name__)

URL_PATTERN = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+', re.IGNORECASE)

CLASSIFICATION_PROMPT = """你是一個 LINE 群組知識庫整理助手。請分析以下一批訊息，完整提取所有知識點並回傳 JSON。

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
   - 如有步驟說明，完整保留每一步
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

群組 ID：{group_id}
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

        # 收集 URL 爬取內容
        url_content_text = self._format_url_contents(messages)

        # 組合 prompt
        prompt = CLASSIFICATION_PROMPT.format(
            group_id=group_id,
            time_range=time_range,
            formatted_messages=formatted,
        )

        if url_content_text:
            prompt += url_content_text

        if media_items:
            media_type_names = set(item["type"] for item in media_items)
            prompt += MULTIMODAL_ADDENDUM.format(
                media_count=len(media_items),
                media_types="、".join("圖片" if t == "image" else "音訊" for t in media_type_names),
            )

        # 呼叫 AI（增大 token 上限以保留完整內容）
        max_tokens = 4096 if media_items else 2048
        try:
            if media_items:
                response = await self.ai.complete_multimodal(
                    text_prompt=prompt,
                    media_items=media_items,
                    content_type=content_type,
                    max_tokens=max_tokens,
                )
            else:
                response = await self.ai.complete(
                    prompt, content_type=content_type, max_tokens=max_tokens,
                )

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
                title=result.get("title", ""),
                summary=result.get("knowledge_points", ""),
                media_descriptions=result.get("media_descriptions", []),
                tags=result.get("tags", []),
                action_items=result.get("action_items", []),
                original_messages=messages,
                group_name=group_id,
                urls_found=urls,
            )

        except Exception as e:
            logger.error(f"AI 分類失敗: {e}", exc_info=True)
            return None

    def _format_url_contents(self, messages: list[RawMessage]) -> str:
        """將爬取的 URL 內容格式化為 AI 可讀文字"""
        all_contents = []
        for msg in messages:
            for uc in msg.url_contents:
                all_contents.append(uc)

        if not all_contents:
            return ""

        parts = ["\n\n## 連結內容（已爬取）\n"]
        for i, uc in enumerate(all_contents, 1):
            parts.append(f"### 連結 {i}: {uc['title']}")
            parts.append(f"URL: {uc['url']}")
            parts.append(uc["content"])
            parts.append("")

        parts.append("請根據以上連結內容進行深入統整，完整提取所有知識點，不要省略任何細節。")
        return "\n".join(parts)

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
