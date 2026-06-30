"""Deterministic mock LLM — implements `LLMProvider` with no network or API key.

Lets anyone clone the repo and run the whole pipeline end-to-end (with the
Markdown sink) without credentials, and gives the test suite a stable provider.
Set `LLM_PROVIDER=mock` to use it.
"""

import json

from lorekeeper.models import MediaPayload
from lorekeeper.ports import ContentType


class MockLLMProvider:
    def __init__(self, category: str = "技術分享", importance: str = "medium"):
        self.category = category
        self.importance = importance

    async def complete(
        self,
        prompt: str,
        *,
        content_type: ContentType = ContentType.TEXT,
        max_tokens: int = 4096,
    ) -> str:
        return self._fake(media_count=0)

    async def complete_multimodal(
        self,
        text_prompt: str,
        media: list[MediaPayload],
        *,
        content_type: ContentType = ContentType.IMAGE,
        max_tokens: int = 4096,
    ) -> str:
        return self._fake(media_count=len(media))

    def _fake(self, media_count: int) -> str:
        payload = {
            "category": self.category,
            "importance": self.importance,
            "title": "（Mock）知識點整理",
            "knowledge_points": (
                "## 這是 MockLLMProvider 的輸出\n\n"
                "- 用於本地 demo 與單元測試，**無需任何 API 金鑰**。\n"
                "- 想要真實 AI 分類，請設定 `LLM_PROVIDER=openrouter` 並填入金鑰。"
            ),
            "media_descriptions": [
                f"（Mock）媒體 {i} 的文字描述" for i in range(1, media_count + 1)
            ],
            "tags": ["mock", "demo", "lorekeeper"],
            "action_items": [],
        }
        return json.dumps(payload, ensure_ascii=False)
