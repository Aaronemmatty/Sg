# Executive Summary — SG Trading Platform Security Audit

**Auditor stance:** Principal Security Engineer review of all 12 services'
actual source code (uploaded this session — `sg_-_Copy.zip`), not just the
architecture described in prior handovers. Findings below are evidenced by
file path and line number; every claim was verified by reading the actual
code, not inferred from documentation.

**Scope covered:** Authentication, authorization, secrets management, input
validation / injection surface, transport/CORS configuration, container
hardening, logging hygiene, and rate limiting, across all 12 FastAPI
services plus shared infrastructure (`database/`, `sg-dashboard/`).

**Not covered in this pass** (flag for a follow-up, see `OPEN_ITEMS` at the
end of each review doc): the React dashboard (`sg-dashboard/`) frontend
security (XSS/CSP), dependency CVE scanning (no network access in the audit
sandbox to check installed package versions against advisory databases),
and load/fuzz testing of any fix.

## Headline finding

**Four services have NO authentication mechanism at all — not fail-open,
not a stub, nothing: `market_data_service`, `strategy_service`,
`execution_orchestrator_service`, and `broker_service`.** No
`Depends(...)`-based auth check exists in any endpoint, router, or
app-level middleware in any of the four. This was verified by reading
every endpoint file, every `main.py`, and every router registration in all
four services — there is no auth code to find, anywhere.

The worst of the four is `broker_service` — the service that actually talks
to Zerodha Kite and places real money orders. With no authentication:

```
POST   /api/v1/orders                 — place a live brokerage order
DELETE /api/v1/orders/{broker_order_id}  — cancel any order
GET    /api/v1/positions, /api/v1/account — read live positions and margin
POST   /api/v1/risk/reset-daily       — reset the risk engine's daily state
```

are all reachable by anyone who can reach the port. `execution_orchestrator_service`
adds `POST /api/v1/intents` — create a trade intent directly, bypassing
strategy/regime logic. `strategy_service` adds `POST /instances` (start a
strategy) and `/reload` (reload strategy code from disk). All with zero
auth, zero rate limiting, on a personal deployment trading real capital.

Notably, these are the *same four services* that have the wildcard-CORS
misconfiguration (CORS-01, below) — strongly suggesting all four were built
from a common template that never received the auth treatment the other 8
services got. This is a pattern, not four independent coincidences — when
fixing this, check whether any *future* service gets scaffolded from the
same unreviewed template before assuming the other 8 are the permanent
baseline.

Separately, **two more services — `regime_detection_service` and
`signal_aggregation_service` — silently authenticate every request as a
valid user the moment their JWT public key file is missing for any
reason**, including in production — see `AUTH-01` below. Between this and
the four-services-with-no-auth-at-all finding above, **6 of the platform's
12 services have no real, enforced authentication today** under realistic
conditions.

## Severity-ranked findings

| ID | Severity | Finding | Services affected |
|---|---|---|---|
| AUTH-00 | **CRITICAL** | No authentication mechanism exists at all — no `Depends`-based check anywhere in any endpoint, router, or middleware | `market_data_service`, `strategy_service`, `execution_orchestrator_service`, `broker_service` |
| AUTH-01 | **CRITICAL** | Auth fails open (full bypass) in production when JWT public key is missing | `regime_detection_service`, `signal_aggregation_service` |
| AUTHZ-01 | **HIGH** | `require_role()` grants a platform-wide bypass to any caller with an "admin" role claim | `risk_engine_service` (the platform's safety-critical pre-trade risk gate) |
| CORS-01 | **HIGH** | `allow_origins=["*"]` + `allow_credentials=True` (invalid per spec, signals unreviewed config) | `market_data_service`, `execution_orchestrator_service`, `strategy_service`, `broker_service` |
| RATE-01 | **HIGH** | No inbound rate limiting at all | 10 of 12 services (only `ai_analyst_service` and `broker_service`'s *outbound* limiter exist) |
| AUTH-02 | **MEDIUM** | Raw JWT decode exception text returned to caller (info disclosure) | 8 of 9 services with their own `auth.py`/`security.py` |
| SEC-01 | **MEDIUM** | No secrets manager/vault — all credentials (Kite API secret/access token, JWT private key, DB passwords) are plain env vars with no rotation tooling | Platform-wide |
| LOG-01 | **MEDIUM** | Structured-log secret redaction exists in only 1 of 12 services, despite `broker_service` holding live brokerage credentials | 11 of 12 services |
| DOCKER-01 | **MEDIUM** | 6 of 14 Dockerfiles run as root (no `USER` directive) | `portfolio_management_service`, `risk_engine_service`, `execution_engine_service`, `ai_analyst_service`, `ml_platform_service`, `backtesting_engine_service` |
| VAL-01 | **MEDIUM** | `symbol`/`strategy`/`timeframe` path params are untyped `str` with no allow-list, used to build Redis keys and outbound REST paths | Platform-wide |
| AUTH-03 | **LOW** | No JWT key-rotation support — every downstream service caches the public key for its process lifetime with no refresh or `kid`/JWKS multi-key support | 9 services verifying tokens independently |
| AUTH-04 | **LOW** | `verify_aud: False` set explicitly, though moot today since `auth_service` issues no `aud` claim at all — fragile if that changes later | `ai_analyst_service`, `backtesting_engine_service` |
| SEC-02 | **LOW** | MFA backup codes: 32 bits of entropy, unsalted SHA-256 storage | `auth_service` |
| CFG-01 | **LOW** | Plaintext `POSTGRES_PASSWORD: sg` committed in 3 docker-compose files | `market_data_service`, `auth_service`, `strategy_service` |
| DEP-01 | **INFO** | Token issuance uses `python-jose`; all 9 verification sites use `PyJWT` — two JWT libraries to track for security advisories instead of one | Platform-wide |

**What's genuinely solid:** every SQL query reviewed (across
`portfolio_management_service`, `execution_engine_service`,
`ml_platform_service`, `backtesting_engine_service`) builds dynamic
`WHERE`/`SET` clauses with hardcoded column names and `$n` placeholders,
passing all actual values through `asyncpg`'s parameter binding — **no SQL
injection found anywhere**, which is a meaningfully good sign about the
team's (or prior sessions') discipline on this specific class of bug.
Password hashing (`bcrypt`, 12 rounds), TOTP MFA (`pyotp`, ±1 window), and
JWT algorithm pinning (no algorithm-confusion / "none" algorithm risk found
anywhere) are all implemented correctly.

## Recommended sequencing

1. **Immediately:** patch `AUTH-00` — four services have no authentication
   at all, including the one that places live brokerage orders. Apply
   `fixes/shared_security_lib/jwt_auth.py` to each (new `app/auth.py` files
   provided per service in `fixes/`) and gate every mutating endpoint with
   `require_role(...)` before this platform trades another rupee on a
   network you don't fully control the perimeter of. Then patch `AUTH-01`
   (drop-in fixes in `fixes/regime_detection_service/` and
   `fixes/signal_aggregation_service/`) and `AUTHZ-01`
   (`fixes/risk_engine_service/app/auth.py`).
2. **This week:** `CORS-01` and `RATE-01` (patches/module provided in
   `fixes/QUICK_PATCHES.md` and `fixes/shared_security_lib/rate_limit.py`).
3. **This sprint:** converge the remaining duplicated/drifted JWT
   verification implementations onto `fixes/shared_security_lib/jwt_auth.py`,
   roll out `redaction.py` and `validation.py` platform-wide, fix the 6 root
   containers.
4. **Backlog, deliberately not urgent:** secrets manager adoption (`SEC-01`)
   — env vars are a legitimate choice for a personal deployment; the
   recommendation in `SECRETS_MANAGEMENT.md` is sized for "when this stops
   being personal," not as something to do this week.

See `THREAT_MODEL.md`, `OWASP_ANALYSIS.md`, `AUTHENTICATION_REVIEW.md`,
`AUTHORIZATION_REVIEW.md`, `SECRETS_MANAGEMENT.md`, `DATA_PROTECTION.md`,
and `INCIDENT_RESPONSE_PLAN.md` for full detail behind each row above.
