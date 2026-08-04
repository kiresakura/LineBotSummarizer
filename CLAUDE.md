# CLAUDE.md

> Lorekeeper — group chats → AI knowledge extraction → knowledge base.
> Ports & adapters (hexagonal), fully async. See `ARCHITECTURE.md`.

## Quick Reference

```bash
# Run locally (real adapters; needs .env)
uvicorn lorekeeper.app:app --reload --port 8000
# or:  lorekeeper serve

# Zero-credential demo (mock LLM + Markdown sink)
lorekeeper demo

# Test / lint
pytest
ruff check . && ruff format --check .
```

Install: `pip install -e ".[dev]"`

## Architecture (the dependency rule)

**`lorekeeper/pipeline/` and `models.py` import only `ports.py`** — never an
adapter or SDK. Adapters implement the ports; `app.py` is the only composition
root (wires adapters from `Settings`).

Pipeline: `enricher` → `aggregator` → `classifier` → `orchestrator` → sink(s).

- Ports: `lorekeeper/ports.py` (`LLMProvider`, `KnowledgeSink`, `Notifier`, `MessageHandler`).
- Adapters: `lorekeeper/adapters/` (line, notion_sink, notion_blocks, markdown_sink, openrouter_llm, mock_llm, notifiers) — the only place vendor code lives.
- Services: `lorekeeper/services/` (safe_http SSRF guard, url_fetcher).

## Key Constraints

- **All async** — no blocking I/O on the event loop (file writes use `asyncio.to_thread`).
- **Adapter selection from config** — `SOURCE`, `SINKS` (JSON list), `LLM_PROVIDER`. `LLM_PROVIDER=mock` and `SINKS=["markdown"]` run with no credentials.
- **Notion limits** — ≤100 blocks/page, ≤2000 chars/rich-text run, ≤3 req/s (TokenBucketRateLimiter at 2.5).
- **Aggregator debounce** — `COOLDOWN_SECONDS` (default 3) of silence flushes; `MAX_BATCH_SIZE` forces a flush.
- **URL crawl** — ≤3 URLs/message, yt-dlp first then BeautifulSoup, all via `safe_http.safe_get` (SSRF-guarded).
- **Model routing** — TEXT→DeepSeek V3.2, IMAGE/AUDIO→Gemini 3.1 Flash Lite, COMPLEX→Gemini 3 Pro (cost-driven; don't change casually).

## Code Style

- Python 3.11+, ruff (line-length 88).
- Pydantic v2 domain models in `lorekeeper/models.py`.
- Settings centralized in `lorekeeper/config.py` (BaseSettings + lru_cache).

## Repo hygiene (important)

- Public portfolio repo (`kiresakura/lorekeeper`). Never reintroduce the company name
  (繆思精工 / Muse / MusesCraft) or a personal email. Commit identity is
  `Crimson <kiresakura@users.noreply.github.com>`.
- Never commit `.env`. This file (CLAUDE.md) is intentionally untracked.
