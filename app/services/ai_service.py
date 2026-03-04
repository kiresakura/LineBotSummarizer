"""AI 服務封裝 — 統一 Claude API 呼叫介面"""

import logging
from app.config import get_settings

logger = logging.getLogger(__name__)


class AIService:
    """封裝 Anthropic Claude API"""

    async def complete(
        self,
        prompt: str,
        model: str | None = None,
        max_tokens: int = 1024,
    ) -> str:
        """呼叫 Claude API 並回傳文字結果"""
        settings = get_settings()
        model = model or settings.ai_model

        import anthropic
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

        try:
            response = await client.messages.create(
                model=model,
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )

            result = response.content[0].text
            logger.debug(
                f"AI 回應 (model={model}, "
                f"input_tokens={response.usage.input_tokens}, "
                f"output_tokens={response.usage.output_tokens})"
            )
            return result

        except anthropic.RateLimitError:
            logger.warning("Claude API 限流，等待後重試...")
            import asyncio
            await asyncio.sleep(5)
            return await self.complete(prompt, model, max_tokens)

        except Exception as e:
            logger.error(f"Claude API 呼叫失敗: {e}")
            raise
