"""OpenRouter LLM adapter (OpenAI-compatible) implementing the `LLMProvider` port.

Routes each modality to a cost-appropriate model and base64-inlines media for
multimodal calls. Retries once on rate limiting.
"""

import asyncio
import base64
import logging

from openai import AsyncOpenAI

from lorekeeper.models import MediaPayload
from lorekeeper.ports import ContentType

logger = logging.getLogger(__name__)


class OpenRouterProvider:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        *,
        model_text: str,
        model_vision: str,
        model_audio: str,
        model_complex: str,
    ):
        self._api_key = api_key
        self._base_url = base_url
        self._models = {
            ContentType.TEXT: model_text,
            ContentType.IMAGE: model_vision,
            ContentType.AUDIO: model_audio,
            ContentType.COMPLEX: model_complex,
        }

    def _client(self) -> AsyncOpenAI:
        return AsyncOpenAI(api_key=self._api_key, base_url=self._base_url)

    def _model(self, content_type: ContentType) -> str:
        return self._models.get(content_type, self._models[ContentType.COMPLEX])

    async def complete(
        self,
        prompt: str,
        *,
        content_type: ContentType = ContentType.TEXT,
        max_tokens: int = 4096,
    ) -> str:
        model = self._model(content_type)
        try:
            response = await self._client().chat.completions.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.choices[0].message.content
        except Exception as e:
            if self._is_rate_limit(e):
                logger.warning("OpenRouter 限流，等待後重試...")
                await asyncio.sleep(5)
                response = await self._client().chat.completions.create(
                    model=model,
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                )
                return response.choices[0].message.content
            logger.error(f"OpenRouter API 呼叫失敗: {e}")
            raise

    async def complete_multimodal(
        self,
        text_prompt: str,
        media: list[MediaPayload],
        *,
        content_type: ContentType = ContentType.IMAGE,
        max_tokens: int = 4096,
    ) -> str:
        model = self._model(content_type)
        parts: list[dict] = [{"type": "text", "text": text_prompt}]
        for item in media:
            b64 = base64.b64encode(item.data).decode("utf-8")
            if item.is_image:
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{item.mime_type};base64,{b64}"},
                    }
                )
            elif item.is_audio:
                parts.append(
                    {
                        "type": "input_audio",
                        "input_audio": {
                            "data": b64,
                            "format": item.mime_type.split("/")[-1],
                        },
                    }
                )

        messages = [{"role": "user", "content": parts}]
        try:
            response = await self._client().chat.completions.create(
                model=model, max_tokens=max_tokens, messages=messages
            )
            return response.choices[0].message.content
        except Exception as e:
            if self._is_rate_limit(e):
                logger.warning("OpenRouter 限流，等待後重試...")
                await asyncio.sleep(5)
                response = await self._client().chat.completions.create(
                    model=model, max_tokens=max_tokens, messages=messages
                )
                return response.choices[0].message.content
            logger.error(f"OpenRouter 多模態 API 呼叫失敗: {e}")
            raise

    @staticmethod
    def _is_rate_limit(e: Exception) -> bool:
        s = str(e).lower()
        return "rate_limit" in s or "429" in s
