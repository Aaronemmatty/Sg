# OWASP Analysis — SG Trading Platform

This platform is API-first (FastAPI services, no server-rendered pages), so
**OWASP API Security Top 10 (2023)** is the primary lens, with **OWASP Top
10 (2021)** items layered in wherever they apply to infrastructure/config
rather than API logic specifically.

## OWASP API Security Top 10 (2023)

| # | Category | Applies? | Evidence |
|---|---|---|---|
| API1:2023 | Broken Object Level Authorization | **Yes** | No endpoint reviewed checks that the authenticated caller "owns" the `symbol`/`order_id`/`run_id` they're requesting — but this platform is single-tenant-per-deployment by design (one person's account), so the practical impact is low today. Re-flag this immediately if the platform ever becomes multi-user/multi-tenant; `tid` (tenant_id) is already in the JWT payload (`auth_service/app/core/security.py`) but downstream services never check it against the resource being accessed. |
| API2:2023 | Broken Authentication | **Yes — Critical** | AUTH-00 (no authentication mechanism exists at all in 4 services, including the brokerage order-placement service), AUTH-01 (fail-open in `regime_detection_service`/`signal_aggregation_service`), AUTH-02 (error detail leakage), AUTH-03 (no key rotation). See `AUTHENTICATION_REVIEW.md`. |
| API3:2023 | Broken Object Property Level Authorization | **Partial** | Not a property-masking issue (no over-permissive serialization found), but adjacent: `symbol`/`strategy`/`timeframe` accepted as unconstrained strings (VAL-01) means the *shape* of what an endpoint accepts is broader than the *shape* of what it should accept. |
| API4:2023 | Unrestricted Resource Consumption | **Yes** | RATE-01 — 10 of 12 services have no rate limiting. `POST /recalculate` on `regime_detection_service` is explicitly described in its own code comment as a manual operator trigger "for debugging or after a backfill" — i.e. an intentionally heavyweight operation — reachable with zero rate limit and, per AUTH-01, zero authentication. |
| API5:2023 | Broken Function Level Authorization | **Yes** | AUTHZ-01 — `risk_engine_service`'s `require_role()` treats "admin" as a bypass for every function-level role check, collapsing fine-grained role gating back to a single tier for anyone holding that one role. |
| API6:2023 | Unrestricted Access to Sensitive Business Flows | **Yes** | The entire live trading pipeline (signal → risk → execution) is a "sensitive business flow" in OWASP's sense, and AUTH-01 + RATE-01 together mean two of its stages can be triggered without authentication or throttling. |
| API7:2023 | Server Side Request Forgery | **Checked, not found** | All outbound `httpx` calls reviewed (`market_data_client.py` across 4 services, `execution_engine_service/app/clients.py`) use a fixed `base_url` from service config with only a path suffix built from input — the path-interpolation gap that exists (VAL-01) is real but does not allow redirecting the request to an arbitrary external host, since httpx only treats absolute URLs as base_url-overriding, and the f-string always prepends a literal `/`-rooted path. |
| API8:2023 | Security Misconfiguration | **Yes** | CORS-01 (wildcard + credentials), DOCKER-01 (root containers), CFG-01 (plaintext compose passwords). |
| API9:2023 | Improper Inventory Management | **Partial** | The platform's own handover docs (two versions, contradicting each other on what's built — see prior conversation) are themselves a mild instance of this at the documentation layer. At the code layer: 9 independently-maintained copies of the same JWT verification logic (see `AUTHENTICATION_REVIEW.md`) is exactly the kind of inventory sprawl this category warns about — a fix applied to one copy (as already happened: `execution_engine_service`'s `auth.py` explicitly comments "exact pattern from execution_engine_service (8008)" when copied elsewhere) is not guaranteed to propagate, and in this audit, it didn't — `regime_detection_service`/`signal_aggregation_service` drifted to a materially worse, fail-open version of the same idea. |
| API10:2023 | Unsafe Consumption of APIs | **Not assessed this session** | Would require reviewing how each service handles the *response* from its upstream dependencies (8002, 8007, 8008, Kite) for things like unbounded response size, content-type confusion, or trusting upstream-supplied data without revalidation. Flagged as a follow-up. |

## OWASP Top 10 (2021) — infrastructure/config-layer items

| # | Category | Applies? | Evidence |
|---|---|---|---|
| A02:2021 | Cryptographic Failures | **Partial** | `bcrypt` (12 rounds) for passwords and RS256 for JWTs are both sound choices. The gap is key *lifecycle*, not algorithm choice: no rotation mechanism (AUTH-03), and MFA backup codes are hashed with unsalted SHA-256 (SEC-02) — fine for a non-secret value, not fine for a credential. |
| A05:2021 | Security Misconfiguration | **Yes** | Same evidence as API8 above. |
| A07:2021 | Identification and Authentication Failures | **Yes — Critical** | Same evidence as API2 above; this is the same underlying bug viewed through the older Top 10's lens. |
| A08:2021 | Software and Data Integrity Failures | **Not assessed** | Would require checking CI/CD pipeline integrity (not in scope — no CI config was part of this upload) and dependency pinning/lockfile presence. `pyproject.toml` files use `>=` version constraints platform-wide per the established convention (see prior handover's Quick Reference) rather than exact pins — acceptable for a personal deployment, worth tightening (lockfiles) before anything resembling production-with-other-people's-money. |
| A09:2021 | Security Logging and Monitoring Failures | **Yes** | LOG-01 — redaction exists in only 1 of 12 services. Separately (not a new finding, just connecting the dots): the `observability_service` built in this conversation's prior session gives the platform real alerting/logging infrastructure for the *first* time — before that, even a successfully-exploited AUTH-01 bypass would have produced no alert anywhere, since nothing was watching for it. |

## What was checked and is NOT a finding

Documenting these explicitly so they aren't re-litigated in a future audit:

- **SQL Injection (A03:2021 / part of API8)** — checked across
  `portfolio_management_service`, `execution_engine_service`,
  `ml_platform_service`, `backtesting_engine_service`. All dynamic SQL
  builds clause skeletons with hardcoded column names; all actual values go
  through `asyncpg` parameter binding. No `ORDER BY`/column-name injection
  found either (no user input ever reaches a raw column/direction slot).
- **Algorithm confusion ("none"/HS256 substitution attacks)** — every JWT
  verification site pins `algorithms=["RS256"]` (or reads a single
  config-controlled value that is always "RS256" in practice) — never
  derived from the token's own header.
- **Command injection** — no `shell=True`, no `eval`/`exec` of
  externally-influenced strings, no unsafe `yaml.load`/`pickle.loads`
  anywhere in the codebase.
- **Hardcoded secrets in source** — none found via pattern-matched scan
  across all `.py` files (separate from the docker-compose plaintext
  password finding, CFG-01, which is a different artifact type).
