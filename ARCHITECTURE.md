# Architecture

A short tour of *why* Lorekeeper is shaped the way it is. For how to run it, see
the [README](README.md).

## Data flow

```
LINE webhook
   │  verify HMAC signature, normalize event, download media
   ▼
InboundMessage ──▶ Enricher ──▶ Aggregator ──▶ Orchestrator ──▶ Sink(s)
                   crawl URLs    debounce per     classify +       Notion /
                   (SSRF-safe)   conversation     fan-out          Markdown
                                                       │
                                                  LLMProvider
                                               (OpenRouter / Mock)
```

Each stage is small and single-purpose; stages communicate through the domain
models in `models.py` (`InboundMessage`, `KnowledgeEntry`), never through
vendor types.

## Ports & adapters (the core idea)

The dependency rule: **`pipeline/` and `models.py` import only `ports.py`** —
never an adapter, an SDK, or a transport. Adapters depend inward on the ports;
the pipeline never depends outward.

```
adapters/ ──implements──▶ ports.py ◀──depends on── pipeline/
(LINE, Notion, Markdown,                            (enricher, aggregator,
 OpenRouter, Mock)                                   classifier, orchestrator)
```

`app.py` is the single composition root: it reads `Settings`, picks adapters by
name (`build_llm`, `build_sinks`), and injects them. Nothing else constructs an
adapter. That's what makes the LLM and sinks swappable from env vars, and makes
the whole pipeline unit-testable with fakes.

## Key decisions & trade-offs

| Decision | Why | Trade-off |
|----------|-----|-----------|
| **Ports & adapters** | swap source/sink/LLM from config; test offline | more indirection than a one-file script |
| **Mock LLM + Markdown sink** | clone-and-run with zero credentials; deterministic tests | mock output is canned, not "real" |
| **Per-conversation debounce** (`Aggregator`) | a burst of messages becomes one coherent entry; fewer LLM calls | adds up to `COOLDOWN_SECONDS` latency |
| **Cost-aware model routing** | text/vision on cheap models, a stronger model only for mixed batches | routing rules are heuristic, not learned |
| **SSRF guard resolves DNS + re-checks each redirect hop** | blocks metadata/internal targets even via redirect | residual DNS-rebinding risk → pair with network egress policy in prod |
| **Fire-and-forget tasks + global fetch semaphore** | webhook returns 200 fast (LINE requirement) | backpressure is bounded, not persisted |
| **In-memory aggregation** | simple, no broker needed for a single instance | not horizontally scalable as-is (see roadmap) |

## Security

- Webhook verified with HMAC-SHA256, **fail-closed** on empty secret/signature.
- `services/safe_http.py` enforces: http/https only, no embedded credentials,
  DNS-resolved IP must be public (blocks private/loopback/link-local/metadata),
  manual redirect re-validation, streamed response-size cap, bounded outbound
  concurrency.
- Secrets are env-only; `.dockerignore` keeps `.env`/`.git` out of image layers.

## Testing strategy

The most logic-dense, pure pieces get the most tests:

- `notion_blocks` — Markdown → Notion conversion (pure, exhaustive).
- `safe_http` — SSRF classification + DNS checks (monkeypatched resolver).
- `aggregator` — debounce/flush timing and conversation isolation.
- `classifier` — JSON / fenced-JSON parsing, enum fallback, URL extraction (fake LLM).
- `app` — DI wiring, `/health`, webhook signature rejection (FastAPI TestClient).

Everything runs offline via the Mock provider — no network, no credentials.

## Roadmap

Natural next steps, in rough priority order:

1. **More adapters** — `TelegramSource`, `ObsidianSink` / `JsonlSink` (proves the seam).
2. **Durable queue** — swap in-memory aggregation for Redis/SQS to scale out and survive restarts.
3. **Idempotency / de-dup** — persist processed message ids (LINE may redeliver).
4. **Daily digest** — scheduled roll-up of a conversation's entries.
5. **Observability** — structured logs + OpenTelemetry traces around each stage.
