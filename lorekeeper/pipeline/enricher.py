"""Pipeline stage 1 — enrich messages by crawling URLs found in their text.

Media (images/audio) is already downloaded by the source adapter, so the
enricher is fully provider-neutral: it only looks at text.
"""

import logging
import re

from lorekeeper.models import InboundMessage, MessageType
from lorekeeper.services.url_fetcher import fetch_url_content

logger = logging.getLogger(__name__)

URL_PATTERN = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+', re.IGNORECASE)
MAX_URLS_PER_MESSAGE = 3


class MessageEnricher:
    """Crawls up to N URLs in a text message and attaches the fetched content."""

    def __init__(self, max_urls: int = MAX_URLS_PER_MESSAGE):
        self.max_urls = max_urls

    async def enrich(self, msg: InboundMessage) -> None:
        if msg.type != MessageType.TEXT or not msg.text:
            return

        urls = URL_PATTERN.findall(msg.text)[: self.max_urls]
        if not urls:
            return

        logger.info(f"發現 {len(urls)} 個 URL，開始爬取內容...")
        for url in urls:
            content = await fetch_url_content(url)
            if content:
                msg.url_contents.append(content)
                logger.info(f"已爬取: {content.title[:50]}")
