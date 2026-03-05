"""情報資料模型"""

import hashlib
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class IntelSource(str, Enum):
    RSS = "rss"
    GOOGLE_NEWS = "google_news"
    REDDIT = "reddit"
    GITHUB = "github"


class IntelItem(BaseModel):
    """單筆情報項目"""
    title: str
    url: str
    source: IntelSource
    source_name: str = ""
    summary: str = ""
    published_at: datetime | None = None
    collected_at: datetime = Field(default_factory=datetime.now)
    tags: list[str] = Field(default_factory=list)
    content_preview: str = ""
    dedup_hash: str = ""

    def compute_hash(self) -> str:
        """計算去重 hash"""
        raw = (self.url + self.title).encode()
        self.dedup_hash = hashlib.sha256(raw).hexdigest()
        return self.dedup_hash
