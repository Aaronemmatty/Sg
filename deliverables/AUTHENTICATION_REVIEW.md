# Authentication Review

Nine services independently implement JWT verification against
`auth_service`'s RS256-signed tokens (no shared library — see API9 in
`OWASP_ANALYSIS.md`). This review reads all nine plus the issuing code.

## AUTH-00 (CRITICAL) — No authentication mechanism at all

**Services:** `market_data_service`, `strategy_service`,
`execution_orchestrator_service`, `broker_service`.

Searched each service's entire `app/` tree for `HTTPBearer`,
`get_current_user`, `verify_token`, `require_role`, `jwt.decode`, or any
`Depends(...)` referencing auth — none found. Then checked each
`app/main.py` and `app/api/v1/router.py` for an app-level or
router-level `dependencies=[...]` that might apply auth globally without
appearing per-endpoint — none found there either. There is no auth code in
any of these four services, at any layer. This was confirmed by direct
inspection of every endpoint file, not inferred from an absence of a
particular filename.

**Confirmed-reachable, unauthenticated endpoints** (full lists, not
samples — every single endpoint in each of these four files is
unauthenticated, since there's nothing to gate any of them):

```
broker_service/app/api/v1/endpoints/broker.py
  POST   /api/v1/orders                    — place a live Kite order
  PUT    /api/v1/orders/{broker_order_id}   — modify an order
  DELETE /api/v1/orders/{broker_order_id}   — cancel an order
  GET    /api/v1/positions                  — read live positions
  GET    /api/v1/account                    — read account/margin info
  GET    /api/v1/risk/status
  POST   /api/v1/risk/reset-daily           — reset risk engine daily state
  GET    /api/v1/status

execution_orchestrator_service/app/api/v1/endpoints/intents.py
  GET    /api/v1/intents
  GET    /api/v1/intents/{intent_id}
  GET    /api/v1/intents/{intent_id}/audit
  POST   /api/v1/intents                    — create a trade intent directly

strategy_service/app/api/v1/endpoints/strategy.py
  POST   /reload                            — reload all strategies from disk
  POST   /instances                         — start a strategy instance
  POST   /instances/{id}/stop|pause|resume
  GET    /, /{name}, /instances, /instances/{id}, /signals/latest, /performance

market_data_service/app/api/v1/endpoints/market.py
  POST   /subscribe, /unsubscribe, /backfill
  GET    /quote/*, /bars/*, /instruments/*, /status, /market-status
```

`broker_service`'s exposure is the most severe by a wide margin —
`POST /api/v1/orders` with no authentication on a service holding live Kite
credentials is, functionally, "anyone who can reach this port can trade
with your money." `execution_orchestrator_service`'s `POST /api/v1/intents`
is nearly as serious: it accepts a trade intent directly, which (per the
frozen pipeline contract) flows on to `risk_engine_service` for approval —
so it doesn't *skip* risk checks the way hitting `broker_service` directly
does, but it does let an external caller inject arbitrary intents into a
pipeline meant to only receive them from `execution_orchestrator`'s own
eligibility/Kelly-allocation logic.

**Likely root cause:** all four of these services also carry the
`allow_origins=["*"], allow_credentials=True` CORS misconfiguration
(CORS-01) — the same four, no others. That's a strong signal these four
were scaffolded from one shared template that never had the auth layer
added, while the other 8 services (which do have per-service `auth.py`
files, however drifted) came from a template that did. This is worth
confirming directly — if there's a known "service template" or generator
used when bootstrapping a new service, fix the template, not just these
four instances, or the next service built from it inherits the same gap.

**Fix:** apply `shared_security_lib/jwt_auth.py`
(`JWTAuthConfig`/`JWTAuthDependencies`, see that file's docstring for exact
usage) as each service's new `app/auth.py`, then add
`Depends(require_role(...))` or `Depends(get_current_user)` to every
endpoint listed above — at minimum, every mutating endpoint
(`POST`/`PUT`/`DELETE`) needs a role gate before this fix is meaningful;
read-only `GET` endpoints need at least `get_current_user` (authenticated,
any role) so the platform has an actual identity in its logs/audit trail
for who queried what. `broker_service`'s order-placing/cancelling endpoints
specifically should gate to a narrow role (e.g. `risk_officer` or a new
`trader` role) rather than "any authenticated user," given what they do.

## AUTH-01 (CRITICAL) — Fail-open authentication bypass

**Files:**
`regime_detection_service/app/core/security.py`,
`signal_aggregation_service/app/core/security.py` (byte-identical files —
confirms one was copy-pasted from the other, or both from a common
ancestor, without independent review).

```python
async def verify_token(...) -> dict:
    settings = get_settings()
    if not settings.AUTH_REQUIRED:
        return {"sub": "anonymous", "tenant_id": settings.DEFAULT_TENANT_ID}

    public_key = _load_public_key()
    if public_key is None:
        # Dev/standalone mode without auth_service's key mounted.
        return {"sub": "dev", "tenant_id": settings.DEFAULT_TENANT_ID}
    ...
```

Compare to the equivalent check in every other service, e.g.
`execution_engine_service/app/auth.py`:

```python
if public_key is None:
    if settings.is_production:
        log.error("auth_public_key_missing_in_production")
        raise HTTPException(status_code=503, detail="...")
    log.warning("auth_dev_stub_user_active", env=settings.env)
    return CurrentUser(...)
```

The difference is the entire vulnerability: every other service asks "are
we in production?" before falling back to a stub user. These two don't ask
at all. `AUTH_REQUIRED` defaults to `True`
(`regime_detection_service/app/config.py:81`,
`signal_aggregation_service/app/config.py:143`), so the more obvious
bypass (`AUTH_REQUIRED=False`) requires an explicit misconfiguration — but
the public-key-missing path requires nothing more than the Docker secret at
`/run/secrets/auth_public_key.pem` (the configured default path) not being
mounted, mounted under a different name, or unreadable due to a permissions
mismatch. All three are routine operational failures, not attacker actions.

**Confirmed impact** (not just theoretical — read the actual endpoints):

```
regime_detection_service/app/api/v1/regime.py:143  POST /recalculate
signal_aggregation_service/app/api/v1/aggregation.py:106  POST /recalculate
```

Both are mutating, compute-heavy, pipeline-adjacent endpoints, gated only by
`Depends(verify_token)` — no `require_role` exists in either file at all,
so even with a *valid* token, there is no authorization tier beyond "any
authenticated (or, per this bug, any unauthenticated) caller."

**Fix provided:** `fixes/regime_detection_service/app/core/security.py`,
`fixes/signal_aggregation_service/app/core/security.py` — both fail closed
in production and add a `require_role()` dependency that didn't exist
before. Apply `require_role("risk_officer")` (or whatever role the platform
intends for "operator debugging" actions, per the existing code comment on
the `recalculate` function) to both `/recalculate` endpoints once the fix
lands — the fix file makes this *possible*, it doesn't change the router
file itself; see `fixes/QUICK_PATCHES.md` for the one-line call-site change
needed in each router.

## AUTH-02 (MEDIUM) — Exception detail leakage

Eight of nine verification implementations return the raw `PyJWTError`
text to the caller:

```python
except jwt.PyJWTError as exc:
    raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")
```

(`portfolio_management_service/app/auth.py`,
`execution_engine_service/app/auth.py`, `ml_platform_service/app/auth.py`,
and others — same pattern, confirmed by direct read of each file.)

This isn't a high-impact leak on its own — PyJWT's error messages don't
typically contain secrets — but it does give an attacker free, precise
feedback on *why* a forged/tampered token failed ("Signature verification
failed" vs "Token is expired" vs "Invalid issuer"), which materially speeds
up any attempt to iteratively craft a working forgery, and fingerprints the
exact JWT library/version in use. Generic `"Invalid token"` costs nothing
and removes the oracle.

**Fix:** included in all provided fix files and in
`shared_security_lib/jwt_auth.py`.

## AUTH-03 (LOW) — No key rotation support

Every verification site loads `AUTH_JWT_PUBLIC_KEY_PATH` once and caches it
for the life of the process (`_public_key_cache` module-level global, or
equivalent `@lru_cache`). There is no `kid` header check, no JWKS endpoint
consumption, no periodic refresh. Practical consequence: rotating
`auth_service`'s signing keypair — the correct incident response to a
suspected key compromise — requires **restarting all 9 verifying services**
to pick up the new public key, and until that restart happens, those
services continue to accept tokens signed by the *old*, presumptively
compromised key with no warning.

**Fix:** `shared_security_lib/jwt_auth.py` adds a `PUBLIC_KEY_CACHE_TTL_SECONDS`
(default 300s) so a key rotation propagates without a restart, *if* the new
key is written to the same file path. True overlap-window multi-key (JWKS)
support is a larger change — noted as a v2 item, not attempted here.

## AUTH-04 (LOW) — `verify_aud: False`

`ai_analyst_service/app/auth.py` and `backtesting_engine_service/app/auth.py`
both explicitly disable audience verification:

```python
payload = jwt.decode(..., options={"verify_aud": False})
```

Checked against the issuing code
(`auth_service/app/core/security.py: create_access_token`) — **no `aud`
claim is ever set in the first place**, so this is currently a no-op, not
an active vulnerability. It's fragile, though: if the platform ever
introduces per-service audiences (e.g. to stop a token meant for one
service being replayed against another — a real "confused deputy" risk
worth considering precisely *because* the platform has 12 services trusting
one shared signing key), these two services would silently continue
ignoring that protection while the other 7 picked it up correctly (since
they don't explicitly disable it). Recommend removing the explicit
override now, before it's covering for something real.

## What's solid

- **Algorithm pinning** — every site pins `algorithms=["RS256"]` or reads a
  single config value that is always `"RS256"`. No site reads the
  algorithm from the token's own header. No "none"-algorithm or
  HS256-confusion path exists anywhere checked.
- **Password hashing** — `bcrypt`, 12 rounds, via `passlib`
  (`auth_service/app/core/security.py`). Reasonable, current-practice cost
  factor.
- **TOTP MFA** — `pyotp`, standard 30s-equivalent period (config-driven via
  `MFA_OTP_PERIOD`), ±1 window tolerance for clock drift. Correctly
  implemented.
- **Required claims** — most sites pass `options={"require": ["exp", "sub"]}`,
  meaning a token missing either claim is rejected outright rather than
  silently treated as non-expiring or subject-less.

## Open items for a follow-up pass

- `auth_service`'s own `decode_token()` (used for its internal
  session/refresh-token handling, separate from the per-service
  verification reviewed above) sets `options={"verify_exp": True,
  "verify_nbf": True}` but does **not** set a `require` list — meaning if a
  refresh token were ever issued without `exp`/`nbf` (shouldn't happen given
  `create_refresh_token` always sets both, but defense-in-depth costs
  nothing), `decode_token` wouldn't catch the omission the way the
  downstream services' `require` option would. Low priority; tighten when
  touching this file for another reason.
- Whether the MFA backup-code verification endpoint is rate-limited was not
  confirmed this session (see SEC-02 in `EXECUTIVE_SUMMARY.md`) — check
  `auth_service`'s login/MFA router directly before treating the 40-bit
  entropy fix in `QUICK_PATCHES.md` as sufficient on its own.
- The four services with no auth at all (AUTH-00) were confirmed by direct
  inspection this session, not left as an open item — but their *fix* has
  not been applied or tested. Treat the fix files in `fixes/` as drafted,
  not verified against a running stack (no network in the build sandbox).
