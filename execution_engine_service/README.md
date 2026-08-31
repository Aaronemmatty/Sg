# execution_engine_service (8008)

Consumes risk-approved trade intents from `sg:risk_approved:{symbol}`,
routes and places orders via `broker_service` (8003), tracks the full order
lifecycle through to fill/rejection/cancellation, and publishes execution
events for `portfolio_management_service` (8009, not yet built).

## Pipeline position

```
risk_engine (8007) → sg:risk_approved:{symbol} → execution_engine (8008) → sg:executions:{symbol} → portfolio_management (8009)
```

## Run locally

```bash
cp .env.example .env       # edit DATABASE_URL / REDIS_URL / BROKER_SERVICE_BASE_URL as needed
pip install -e . --break-system-packages   # or use a venv
uvicorn app.main:app --host 0.0.0.0 --port 8008 --reload
```

Migrations in `migrations/*.sql` run automatically at startup against `sg_db`.

## State machine

```
PENDING --> ROUTING --> SUBMITTED --> ACKNOWLEDGED --> PARTIALLY_FILLED --> FILLED
  |            |            |               |                 |
  v            v            v               v                 v
HELD       FAILED      REJECTED/      CANCELLED/         CANCELLED/
  |                     CANCELLED/      EXPIRED/           EXPIRED/
  v                      FAILED         FAILED             FAILED
EXPIRED/CANCELLED
```
All transitions are enforced centrally in `app/state_machine.py` — nothing
writes `state` directly outside of `app/db.py::update_order_state`, which
also guards against concurrent updates (optimistic check on `from_state`)
and writes the audit log in the same transaction.

## Module map

| Module | Responsibility |
|---|---|
| `app/worker.py` | Core execution workflow: consume → route → submit → poll |
| `app/order_router.py` | Smart-execution routing (style/qty/order-type/limit price) |
| `app/state_machine.py` | Legal order-state transitions |
| `app/clients.py` | broker_service (8003) HTTP client, retry via tenacity |
| `app/market_data_client.py` | market_data_service (8002) last-price lookup |
| `app/fill_processor.py` | Maps broker status payloads → state + fills + slippage |
| `app/reconciliation.py` | Periodic safety-net sweep of all non-terminal orders |
| `app/hold_manager.py` | RISK_HOLD parking + TTL expiry |
| `app/redis_bus.py` | Inbound psubscribe, outbound publish |
| `app/events.py` | In-process pub/sub (metrics, Redis publish, SSE all subscribe) |
| `app/db.py` | asyncpg persistence + audit trail |
| `app/auth.py` | JWT RS256 verification, matches auth_service/risk_engine pattern |
| `app/metrics.py` | Domain-specific Prometheus metrics |
| `app/api/*` | REST: orders, executions, audit, manual cancel, SSE stream, health |

## Open decisions / assumptions requiring confirmation

These were either explicitly flagged as open in the platform handover, or
are new assumptions introduced while building 8008. **Do not treat any of
these as final** — confirm against the real upstream/downstream services
before production cutover.

1. **RISK_HOLD handling** (`app/hold_manager.py`) — default behavior: park as
   `HELD`, expire via TTL (`HOLD_MAX_AGE_SECONDS`) if risk_engine never
   re-publishes the intent as approved/rejected. execution_engine does not
   poll risk_engine; it only reacts if the *same* `intent_id` is republished
   to `sg:risk_approved:{symbol}` with a different status. **This was an
   explicitly undefined decision in the handover — confirm the intended
   design with whoever owns risk_engine.**
2. **broker_service (8003) order API shape** (`app/clients.py`) — assumed
   `POST /orders`, `GET /orders/{id}`, `POST /orders/{id}/cancel`, with an
   `Idempotency-Key` header. **Unconfirmed**, same caveat risk_engine flagged
   for `/margins` and `/portfolio/snapshot`.
3. **broker order-status payload shape** (`app/fill_processor.py`) — assumed
   `status` / `filled_quantity` / `average_price` / `fills[]` fields.
   **Unconfirmed.**
4. **market_data_service (8002) price endpoint** (`app/market_data_client.py`)
   — assumed `GET /symbols/{symbol}/ltp`. **Unconfirmed** — if 8002 only
   exposes price via the `sg:market:candle:{symbol}:{tf}` Redis stream,
   swap this client's implementation (callers are unaffected).
5. **Outbound channel naming** — `sg:executions:{symbol}` and
   `sg:execution:events` are new channels added by this service (the
   original contract didn't define an 8008→8009 channel). Confirm naming
   before 8009 is built against it.
6. **Order types in v1** — market and limit only. No SL/SL-M, no order
   slicing/TWAP. The router (`app/order_router.py`) is the place to extend
   this later.
7. **Application-level retry** — one retry (fresh price + re-route +
   re-submit) on top of tenacity's network-level retries inside
   `BrokerServiceClient`, then `FAILED`. No further automatic retry or
   manual-intervention queue exists yet beyond that.

## Rules carried over from the platform handover

- Does not rebuild any of 8001–8007.
- Does not include the master `docker-compose.yml` — this `Dockerfile` is
  service-level only, to be wired into the master compose once 8009 exists.
- JWT verification matches the auth_service/risk_engine pattern: real
  RS256 key required in production, dev stub fallback only in
  non-production.
