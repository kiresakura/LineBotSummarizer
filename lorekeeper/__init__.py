"""Lorekeeper — turn noisy group chats into a structured knowledge base.

A pluggable, fully-async pipeline:

    source ──▶ enrich ──▶ aggregate ──▶ classify ──▶ sink(s)
    (LINE)     (URLs)     (debounce)    (LLM)        (Notion / Markdown)

The pipeline depends only on the Protocols in `lorekeeper.ports`; concrete
integrations live in `lorekeeper.adapters` and are wired in `lorekeeper.app`.
"""

__version__ = "0.2.0"
