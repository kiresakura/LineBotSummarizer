"""集中管理所有設定 & 環境變數"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # LINE
    line_channel_secret: str = ""
    line_channel_access_token: str = ""

    # Notion
    notion_api_key: str = ""
    notion_database_id: str = ""        # 主知識庫 Database ID
    notion_digest_database_id: str = ""  # 每日摘要 Database ID

    # AI (OpenRouter)
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    # 模型路由（依內容類型自動選擇最適合的模型）
    ai_model_text: str = "deepseek/deepseek-v3.2-20251201"
    ai_model_vision: str = "google/gemini-3.1-flash-lite-preview-20260303"
    ai_model_audio: str = "google/gemini-3.1-flash-lite-preview-20260303"
    ai_model_complex: str = "google/gemini-3-pro-preview"

    # 管理員通知
    admin_line_user_id: str = ""

    # 處理設定
    aggregation_window_seconds: int = 30  # 訊息聚合視窗（秒）
    min_batch_size: int = 1
    max_batch_size: int = 20
    notion_rate_limit: float = 2.5  # req/s，低於 Notion 上限 3/s

    # 分類設定
    noise_filter_enabled: bool = True  # 是否過濾噪音訊息
    categories: list[str] = [
        "技術分享", "新聞資訊", "工具推薦", "問題討論",
        "學習資源", "專案更新", "靈感想法", "其他"
    ]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
