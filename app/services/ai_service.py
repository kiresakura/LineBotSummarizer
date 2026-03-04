"""AI 服務封裝 — 統一 OpenRouter API 呼叫介面（OpenAI 相容）"""

import asyncio
import base64
import logging
from enum import Enum

from openai import AsyncOpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)


class ContentType(str, Enum):
    """內容模態，用於模型路由"""
    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    COMPLEX = "complex"


class AIService:
    """封裝 OpenRouter API（透過 OpenAI SDK）"""

    def _get_client(self) -> AsyncOpenAI:
        settings = get_settings()
        return AsyncOpenAI(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
        )

    def _get_model(self, content_type: ContentType) -> str:
        """根據內容類型選擇最適合的模型"""
        settings = get_settings()
        return {
            ContentType.TEXT: settings.ai_model_text,
            ContentType.IMAGE: settings.ai_model_vision,
            ContentType.AUDIO: settings.ai_model_audio,
            ContentType.COMPLEX: settings.ai_model_complex,
        }.get(content_type, settings.ai_model_complex)

    async def complete(
        self,
        prompt: str,
        model: str | None = None,
        max_tokens: int = 1024,
        content_type: ContentType = ContentType.TEXT,
    ) -> str:
        """呼叫 OpenRouter API（純文字模式）"""
        model = model or self._get_model(content_type)
        client = self._get_client()

        try:
            response = await client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            result = response.choices[0].message.content
            logger.debug(f"AI 回應 (model={model}, usage={response.usage})")
            return result

        except Exception as e:
            if "rate_limit" in str(e).lower() or "429" in str(e):
                logger.warning("OpenRouter API 限流，等待後重試...")
                await asyncio.sleep(5)
                return await self.complete(prompt, model, max_tokens, content_type)
            logger.error(f"OpenRouter API 呼叫失敗: {e}")
            raise

    async def complete_multimodal(
        self,
        text_prompt: str,
        media_items: list[dict],
        model: str | None = None,
        max_tokens: int = 1024,
        content_type: ContentType = ContentType.IMAGE,
    ) -> str:
        """
        呼叫 OpenRouter API（多模態模式）

        media_items: [{"type": "image"|"audio", "data": bytes, "mime_type": str}]
        """
        model = model or self._get_model(content_type)
        client = self._get_client()

        content_parts: list[dict] = [{"type": "text", "text": text_prompt}]

        for item in media_items:
            b64_data = base64.b64encode(item["data"]).decode("utf-8")
            mime_type = item["mime_type"]

            if item["type"] == "image":
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{b64_data}"},
                })
            elif item["type"] == "audio":
                content_parts.append({
                    "type": "input_audio",
                    "input_audio": {
                        "data": b64_data,
                        "format": mime_type.split("/")[-1],
                    },
                })

        try:
            response = await client.chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": content_parts}],
            )
            result = response.choices[0].message.content
            logger.debug(
                f"AI 多模態回應 (model={model}, "
                f"media_count={len(media_items)}, usage={response.usage})"
            )
            return result

        except Exception as e:
            if "rate_limit" in str(e).lower() or "429" in str(e):
                logger.warning("OpenRouter API 限流，等待後重試...")
                await asyncio.sleep(5)
                return await self.complete_multimodal(
                    text_prompt, media_items, model, max_tokens, content_type
                )
            logger.error(f"OpenRouter 多模態 API 呼叫失敗: {e}")
            raise
