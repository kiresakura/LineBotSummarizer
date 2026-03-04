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

    # AI (Claude)
    anthropic_api_key: str = ""
    ai_model: str = "claude-haiku-4-5-20251001"  # 初篩用 Haiku 省成本
    ai_model_advanced: str = "claude-sonnet-4-5-20250929"  # 複雜內容用 Sonnet

    # 處理設定
    aggregation_window_seconds: int = 300  # 訊息聚合視窗（秒）
    min_batch_size: int = 3
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
