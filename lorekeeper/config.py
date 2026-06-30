"""Centralized settings (pydantic-settings) and adapter selection.

Which source / sinks / LLM provider are active is chosen here from env vars, so
swapping Notion for local Markdown — or OpenRouter for the mock provider — needs
no code change. See `lorekeeper.app.create_app` for how these strings are wired.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- adapter selection ---
    source: str = "line"  # "line" | "telegram"
    sinks: list[str] = ["notion"]  # any of: "notion", "markdown"
    llm_provider: str = "openrouter"  # "openrouter" | "mock"

    # --- LINE source / notifier ---
    line_channel_secret: str = ""
    line_channel_access_token: str = ""
    admin_line_user_id: str = ""

    # --- Telegram source / notifier ---
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""
    telegram_admin_chat_id: str = ""

    # --- Notion sink ---
    notion_api_key: str = ""
    notion_database_id: str = ""
    notion_rate_limit: float = 2.5  # req/s, kept below Notion's 3/s ceiling

    # --- Markdown sink ---
    markdown_output_dir: str = "./knowledge"

    # --- OpenRouter LLM ---
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    # model routing by modality (cost-aware; see README)
    ai_model_text: str = "deepseek/deepseek-v3.2-20251201"
    ai_model_vision: str = "google/gemini-3.1-flash-lite-preview-20260303"
    ai_model_audio: str = "google/gemini-3.1-flash-lite-preview-20260303"
    ai_model_complex: str = "google/gemini-3-pro-preview"

    # --- processing ---
    cooldown_seconds: float = 3.0  # debounce window for bursty messages
    max_batch_size: int = 20  # force a flush at this many messages
    noise_filter_enabled: bool = True  # drop low-value (noise) batches
    categories: list[str] = [
        "技術分享",
        "新聞資訊",
        "工具推薦",
        "問題討論",
        "學習資源",
        "專案更新",
        "靈感想法",
        "其他",
    ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
