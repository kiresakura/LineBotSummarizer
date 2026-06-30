# 🧭 Lorekeeper

[![ci](https://github.com/kiresakura/lorekeeper/actions/workflows/ci.yml/badge.svg)](https://github.com/kiresakura/lorekeeper/actions/workflows/ci.yml)
[![secret-scan](https://github.com/kiresakura/lorekeeper/actions/workflows/secret-scan.yml/badge.svg)](https://github.com/kiresakura/lorekeeper/actions/workflows/secret-scan.yml)
![python](https://img.shields.io/badge/python-3.11%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)

**English** | [繁體中文](README.zh-TW.md)

Turn noisy group chats into a structured, searchable knowledge base — automatically.

Lorekeeper is a fully-async pipeline that ingests messages from a chat **source**,
uses a multimodal LLM to extract *complete knowledge points* (not just a summary),
and writes the result to one or more knowledge **sinks**. Sources, sinks, and the
LLM are swappable from config — the core pipeline depends only on interfaces.

```
 source ───▶ enrich ───▶ aggregate ───▶ classify ───▶ sink(s)
 (LINE)      (crawl       (debounce      (multimodal   (Notion /
             URLs)        bursts)        LLM routing)   Markdown)
```

> Want to see it work in 30 seconds with no accounts? → [`lorekeeper demo`](#quickstart).

---

## Why this design

The interesting part isn't "a LINE bot that writes to Notion" — it's that **none of
the core code knows about LINE or Notion**. The pipeline depends only on three
Protocols (`lorekeeper/ports.py`):

| Port | Responsibility | Adapters shipped |
|------|----------------|------------------|
| `MessageSource` (via a `MessageHandler`) | produce normalized `InboundMessage`s | LINE, Telegram |
| `LLMProvider` | classify + extract knowledge | OpenRouter, **Mock** (no key) |
| `KnowledgeSink` | persist a `KnowledgeEntry` | Notion, **Markdown** (no account), JSONL |

This **ports & adapters (hexagonal)** layout buys three concrete things:

1. **Swap integrations from config** — `SINKS=["markdown"]`, `LLM_PROVIDER=mock`, no code change.
2. **Run with zero credentials** — the Mock LLM + Markdown sink make the whole flow runnable and testable locally (that's how CI exercises it).
3. **Extend in a few lines** — every seam ships multiple adapters as proof (sources: LINE, Telegram · sinks: Notion, Markdown, JSONL · LLM: OpenRouter, Mock); adding more doesn't touch the pipeline.

```
            ┌──────────────────────── core (no vendor imports) ───────────────────────┐
 LINE  ─────▶  MessageHandler ─▶ Enricher ─▶ Aggregator ─▶ Orchestrator ─▶ KnowledgeSink ───▶ Notion
 webhook │                                                    │     ▲                     └▶ Markdown
         │                                              Classifier  │
         │                                                    ▼     │
         └──────────────────────────────────────────  LLMProvider (OpenRouter / Mock)
                         adapters ◀────── depend on ──────▶ ports ◀────── implement ────── adapters
```

---

## Quickstart

```bash
git clone https://github.com/kiresakura/lorekeeper.git
cd lorekeeper
pip install -e ".[dev]"
```

**See it run with no credentials** (Mock LLM → Markdown):

```bash
lorekeeper demo            # writes a knowledge entry to ./knowledge/*.md
```

**Run for real** (LINE source → Notion sink → OpenRouter):

```bash
cp .env.example .env       # fill in LINE / Notion / OpenRouter keys
lorekeeper serve           # or: uvicorn lorekeeper.app:app --port 8000
```

Then point your LINE channel's Webhook URL at `https://your-host/webhook`.

---

## Features

- **Multimodal extraction** — text, images, and audio in one batch; per-modality model routing.
- **Cost-aware model routing** — cheap models for text/vision, a stronger model only for mixed/complex batches (configurable).
- **Full knowledge extraction, not summaries** — the prompt is tuned to preserve every detail, code block, and step.
- **Smart aggregation** — per-conversation debounce so a burst of messages becomes one coherent entry.
- **SSRF-hardened URL crawling** — yt-dlp (1000+ video sites) + BeautifulSoup, behind a fetch guard that blocks private/loopback/cloud-metadata targets and caps response size.
- **Resilient Notion writes** — token-bucket rate limiting (2.5 req/s) + exponential-backoff retries, respecting Notion's 100-block / 2000-char limits.
- **Fan-out to multiple sinks** — write the same entry to Notion *and* local Markdown/JSONL at once.

## Extending it

Adding a sink is implementing one method. Here's the complete `JsonlSink` that ships:

```python
# lorekeeper/adapters/jsonl_sink.py
import asyncio
from pathlib import Path
from lorekeeper.models import KnowledgeEntry

class JsonlSink:
    name = "jsonl"

    def __init__(self, path: str = "./knowledge.jsonl"):
        self.path = Path(path)

    async def write(self, entry: KnowledgeEntry) -> None:
        line = entry.model_dump_json(exclude={"source_messages"})
        await asyncio.to_thread(self._append, line)

    def _append(self, line: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
```

It's wired in `lorekeeper/app.py:build_sinks`; set `SINKS=["jsonl"]` to enable. Adding
another sink doesn't touch the pipeline.

---

## Configuration

All via environment variables (see [`.env.example`](.env.example)):

| Variable | Purpose |
|----------|---------|
| `SOURCE` | message source: `line` or `telegram` |
| `SINKS` | JSON list of sinks: `["notion"]`, `["markdown"]`, `["jsonl"]`, or combined |
| `LLM_PROVIDER` | `openrouter` (real) or `mock` (no key, for local/CI) |
| `LINE_CHANNEL_SECRET` / `LINE_CHANNEL_ACCESS_TOKEN` | LINE Messaging API (when `SOURCE=line`) |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_WEBHOOK_SECRET` | Telegram Bot API (when `SOURCE=telegram`) |
| `ADMIN_LINE_USER_ID` | optional — recipient of error alerts |
| `NOTION_API_KEY` / `NOTION_DATABASE_ID` | Notion sink |
| `MARKDOWN_OUTPUT_DIR` / `JSONL_OUTPUT_PATH` | Markdown / JSONL sink output location |
| `OPENROUTER_API_KEY` | OpenRouter key; `AI_MODEL_*` override the routing |
| `COOLDOWN_SECONDS` / `MAX_BATCH_SIZE` | aggregation tuning |
| `NOISE_FILTER_ENABLED` | drop "noise"-rated batches |

**Notion DB schema** (sink expects these properties): `Title` (title), `Category` (select),
`Importance` (select), `Tags` (multi-select), `Source` (select), `Date` (date),
`Knowledge` (rich text), `Has Action Items` (checkbox), `URLs` (url).

---

## Project layout

```
lorekeeper/
├── ports.py            # the 3 Protocols the pipeline depends on (framework-free)
├── models.py           # provider-neutral domain models
├── config.py           # settings + adapter selection
├── app.py              # composition root: wires adapters from config
├── cli.py              # `lorekeeper demo` / `serve`
├── pipeline/           # enricher → aggregator → classifier → orchestrator
├── adapters/           # LINE, Telegram, Notion, Markdown, JSONL, OpenRouter, Mock — the only vendor code
└── services/           # safe_http (SSRF guard), url_fetcher
tests/                  # 36 tests: pure logic, SSRF guard, debounce, classifier, sinks, DI/webhook
```

## Testing

```bash
pytest            # 36 tests, no network or credentials required
ruff check . && ruff format --check .
```

The suite leans on the Mock LLM and pure converters, so it runs offline and
deterministically. CI (GitHub Actions) runs lint + a [gitleaks](.github/workflows/secret-scan.yml)
secret scan on every push.

## Security & privacy

- Webhook requests are verified with HMAC-SHA256 and **fail closed** if the secret is unset.
- URL crawling is SSRF-guarded (`lorekeeper/services/safe_http.py`).
- Secrets are env-only; `.env` and `.git` are kept out of the Docker image via `.dockerignore`.
- The bot processes third-party chat content — operators must obtain member consent and
  review local privacy law. See [`SECURITY.md`](SECURITY.md).

## Deployment

```bash
docker build -t lorekeeper .
docker run -p 8000:8000 --env-file .env lorekeeper   # runs as a non-root user
```

Deploys cleanly to Railway / Render / any container host. Estimated cost for a
moderately active group: **< NT$200/month** (OpenRouter usage + a small host;
Notion & LINE free tiers).

## License

[MIT](LICENSE) © kiresakura
