# ai_analyst_service (8012)

LLM-backed trade/portfolio/risk/market/performance explanations for the SG
Trading Platform.

## Decisions made for this build

Per your "best for the program" delegation:

1. **LLM provider** — a fully provider-agnostic `LLMProvider` interface
   (`app/llm/base.py`), shipped with one concrete implementation,
   `AnthropicProvider` (`app/llm/anthropic_provider.py`), calling the
   Anthropic Messages API directly over `httpx` (no SDK dependency). Adding
   a second provider later is a new file + one line in `llm/factory.py` —
   nothing else in the codebase imports a provider-specific client.
2. **Response delivery** — synchronous by default, with `"stream": true` on
   any request body opening a Server-Sent-Events stream instead
   (`EventSourceResponse`). Rate limiting and cache lookups always complete
   *before* a stream opens, so a rejected/cached request still gets a clean
   HTTP status (429/200) rather than an error mid-stream.
3. **Data aggregation scope (v1)** — `portfolio_management_service` (8009,
   confirmed contract), `risk_engine_service` (8007), `execution_engine_service`
   (8008), and `market_data_service` (8002). `strategy_service` (8004) and
   `regime_detection_service` (8005) are not wired in — none of the 5
   capabilities need them yet; add a client under `app/clients/` the same
   way if a future capability does.

## The 5 capabilities

| Capability | Endpoint | Data sources |
|---|---|---|
| Trade review | `POST /api/v1/analysis/trade-review` | execution_engine (8008) + portfolio_management (8009) |
| Portfolio review | `POST /api/v1/analysis/portfolio-review` | portfolio_management (8009) |
| Risk explanation | `POST /api/v1/analysis/risk-explanation` | risk_engine (8007) |
| Market summary | `POST /api/v1/analysis/market-summary` | market_data (8002) |
| Performance explanation | `POST /api/v1/analysis/performance-explanation` | portfolio_management (8009) |

Every request body accepts an optional `user_note` (free text, capped at
500 chars) and a `stream` flag.

## Architecture

```
request -> JWT auth -> context_builder (read-only fetches, degrades
           gracefully per source) -> AnalysisService.prepare()
             -> active PromptTemplate (DB, 60s in-process cache)
             -> cache lookup (Redis, keyed on capability+params+prompt version)
             -> [cache miss] rate limiter (Redis, per-user + global, fail-open)
             -> render template (admin-authored, <data>/<user_note> tags)
           -> AnalysisService.run() / .stream()
             -> LLMProvider.generate() / .generate_stream() (Anthropic)
           -> cache the result, write an audit row, return/stream
```

### LLM abstraction layer
`app/llm/base.py` defines `LLMProvider` (`generate`, `generate_stream`,
`aclose`). `app/llm/anthropic_provider.py` is the only implementation today.
Retries on 429/5xx/transport errors via `tenacity`; never retries 4xx
(except 429) since those won't succeed on retry.

### Prompt management
`app/services/prompt_manager.py` + `ai_prompt_templates` table. One active
version per capability (enforced by a partial unique index), versioned and
swappable via the admin API without a redeploy:
- `GET /api/v1/admin/prompts` — list all versions
- `POST /api/v1/admin/prompts/{capability}` — create a new version
- `POST /api/v1/admin/prompts/{capability}/activate/{version}` — roll forward (or back)

All three require the `risk_officer` role. Five default v1 templates are
seeded in `migrations/002_seed_prompts.sql`.

### Caching
Redis, keyed on `capability + request params + active prompt version`
(`app/services/cache_service.py`) — a prompt rollout naturally busts the
cache instead of serving answers generated against a retired template.
Default TTL 5 min; market summaries 2 min (faster-moving), portfolio
reviews 3 min — all configurable via env vars. Fails open (a Redis outage
degrades to "always call the LLM", not a 500).

### Rate limiting
Redis fixed-window counters, per-user (default 10/min) and global (default
120/min) (`app/services/rate_limiter.py`). Only enforced on a cache miss —
re-reading a cached answer doesn't cost LLM spend, so it doesn't cost rate
limit budget either. Fails open on Redis outage (logged, not blocking).

### Monitoring
structlog (with automatic redaction of API keys/tokens/prompts from log
fields), OpenTelemetry tracing, and Prometheus metrics for: requests by
capability/status, end-to-end and LLM-only latency histograms, token usage,
cache hit/miss, rate-limit rejections, upstream client errors.

### Security controls
- JWT RS256 auth on every endpoint (dev stub fallback identical to other
  services); admin endpoints additionally require `risk_officer`.
- **Prompt-injection mitigation**: all upstream data is wrapped in
  `<data>...</data>`, the free-text user note in `<user_note>...</user_note>`,
  and every system prompt explicitly instructs the model to treat both as
  information to summarise, never as instructions — even if their contents
  look like commands.
- **Size limits**: `user_note` capped at 500 chars (Pydantic), the full
  serialized data context hard-capped at 12,000 chars
  (`truncate_json_context`, explicitly marked when truncated) before it
  ever reaches the LLM — bounds both cost and the chance of a malformed
  prompt from a pathological upstream response.
- **Secrets**: `ANTHROPIC_API_KEY` from env only; structlog redacts
  `api_key`/`authorization`/`token`/`prompt`/`system_prompt` keys from any
  log line automatically.
- **Audit trail**: every analysis request writes an `ai_audit_log` row
  (user, capability, cache hit, status, latency, token counts) — deliberately
  **never** the prompt or response text, so the audit trail itself can't
  become a sensitive-data sink. `GET /api/v1/admin/audit/summary` gives a
  rollup for cost/abuse review.
- **No financial advice**: every system prompt explicitly forbids
  forward-looking recommendations — the model explains historical,
  already-computed data only.

## Known limitations / open items for next session

1. **`risk_engine_service` (8007) and `execution_engine_service` (8008) REST
   contracts are unconfirmed** — the platform handover only documents their
   Redis channels and capabilities, not a REST API. `app/clients/risk_client.py`
   and `app/clients/execution_client.py` each document the assumed shape at
   the top of the file and are fully isolated — confirm against the real
   routers before relying on this in production. (`portfolio_client.py`'s
   contract IS confirmed — 8009's full API was specified in the handover.)
2. **Streaming responses don't carry token usage.** Anthropic's SSE stream
   is parsed for `content_block_delta` text only; the final usage figures
   (in a `message_delta`/`message_stop` event) aren't captured, so streamed
   requests log 0 tokens in the audit trail. Non-streaming requests have
   accurate token counts.
3. **Rate limiting is fixed-window, not sliding/token-bucket** — allows a
   burst of up to 2x the limit across a minute boundary. Fine for cost
   control, not for precise throttling.
4. **`strategy_service` (8004) and `regime_detection_service` (8005) are not
   wired in** — none of the 5 capabilities need them today, but a future
   "strategy explanation" capability would need a new client.
5. **No automated red-teaming of the prompt-injection mitigation** — the
   `<data>`/`<user_note>` tag separation and system-prompt instructions are
   the only defence; this is a reasonable v1 posture but hasn't been
   adversarially tested against real injection attempts.

## Running locally

```bash
pip install -e ".[dev]"
cp .env.example .env   # set DATABASE_URL and ANTHROPIC_API_KEY
uvicorn app.main:app --host 0.0.0.0 --port 8012 --reload
```

## Running tests

```bash
pip install -e ".[dev]"
pytest
```

> As with the previous service, this sandbox has no network access, so
> `pytest` could not actually be executed here — every test was written and
> manually traced through for correctness. Please run the suite for real in
> your dev environment before marking this service complete.
