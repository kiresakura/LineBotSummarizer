"""Composition root — wire adapters from config and expose the FastAPI app.

This is the *only* module that imports concrete adapters. It reads the active
source / sinks / LLM provider from `Settings` and assembles the pipeline. Pass a
custom `Settings` to `create_app` (e.g. with `llm_provider="mock"`) to run the
whole thing without any external credentials — that's how the tests drive it.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from lorekeeper import __version__
from lorekeeper.adapters.line import LineClient, LineNotifier, LineSource
from lorekeeper.adapters.markdown_sink import MarkdownSink
from lorekeeper.adapters.mock_llm import MockLLMProvider
from lorekeeper.adapters.notifiers import NullNotifier
from lorekeeper.adapters.notion_sink import NotionSink
from lorekeeper.adapters.openrouter_llm import OpenRouterProvider
from lorekeeper.config import Settings, get_settings
from lorekeeper.models import InboundMessage
from lorekeeper.pipeline.aggregator import MessageAggregator
from lorekeeper.pipeline.classifier import MessageClassifier
from lorekeeper.pipeline.enricher import MessageEnricher
from lorekeeper.pipeline.orchestrator import Orchestrator
from lorekeeper.ports import KnowledgeSink, LLMProvider, Notifier

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def build_llm(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "mock":
        return MockLLMProvider()
    return OpenRouterProvider(
        settings.openrouter_api_key,
        settings.openrouter_base_url,
        model_text=settings.ai_model_text,
        model_vision=settings.ai_model_vision,
        model_audio=settings.ai_model_audio,
        model_complex=settings.ai_model_complex,
    )


def build_sinks(settings: Settings) -> list[KnowledgeSink]:
    sinks: list[KnowledgeSink] = []
    for name in settings.sinks:
        if name == "notion":
            sinks.append(
                NotionSink(
                    settings.notion_api_key,
                    settings.notion_database_id,
                    rate_limit=settings.notion_rate_limit,
                )
            )
        elif name == "markdown":
            sinks.append(MarkdownSink(settings.markdown_output_dir))
        else:
            logger.warning(f"未知的 sink: {name!r}，已略過")
    if not sinks:
        logger.warning("未設定任何有效 sink，改用本地 Markdown")
        sinks.append(MarkdownSink(settings.markdown_output_dir))
    return sinks


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    llm = build_llm(settings)
    sinks = build_sinks(settings)

    line_client: LineClient | None = None
    if settings.source == "line":
        line_client = LineClient(
            settings.line_channel_secret, settings.line_channel_access_token
        )
        notifier: Notifier = LineNotifier(line_client, settings.admin_line_user_id)
    else:
        notifier = NullNotifier()

    classifier = MessageClassifier(llm)
    orchestrator = Orchestrator(
        classifier, sinks, notifier, noise_filter_enabled=settings.noise_filter_enabled
    )
    aggregator = MessageAggregator(
        orchestrator.process,
        cooldown_seconds=settings.cooldown_seconds,
        max_batch_size=settings.max_batch_size,
    )
    enricher = MessageEnricher()

    async def handle(msg: InboundMessage) -> None:
        await enricher.enrich(msg)
        await aggregator.add(msg.conversation_id, msg)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        logger.info(
            f"Lorekeeper {__version__} 啟動 — source={settings.source}, "
            f"sinks={[s.name for s in sinks]}, llm={settings.llm_provider}"
        )
        yield
        await aggregator.flush_all()
        logger.info("Lorekeeper 已關閉")

    app = FastAPI(
        title="Lorekeeper",
        description="Turn group chats into a structured knowledge base.",
        version=__version__,
        lifespan=lifespan,
    )

    @app.get("/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "service": "lorekeeper",
            "version": __version__,
            "source": settings.source,
            "sinks": [s.name for s in sinks],
            "llm": settings.llm_provider,
        }

    if settings.source == "line" and line_client is not None:
        app.include_router(LineSource(line_client, handle).router)

    return app


# Module-level app for `uvicorn lorekeeper.app:app`.
app = create_app()
