# Fix for AUTH-00 — Adding Authentication to 4 Unprotected Services

`market_data_service`, `strategy_service`, `execution_orchestrator_service`,
and `broker_service` have **zero** JWT/auth config fields today (confirmed —
`grep`'d each `Settings` class; none define `JWT_PUBLIC_KEY_PATH`, `env`
vs. `APP_ENV` naming aside, none have anything auth-related at all). This
is a from-scratch addition, not a drift fix like the other services.

## Step 1 — add config fields

Each of these 4 services uses `APP_ENV` (not `env`, which is what the other
8 services use — yet another naming inconsistency worth flattening
eventually, but not blocking this fix). Add to each service's
`Settings` class in `app/core/config.py`:

```python
AUTH_JWT_PUBLIC_KEY_PATH: str = "/run/secrets/auth_public_key.pem"
AUTH_JWT_ALGORITHM: str = "RS256"
AUTH_JWT_ISSUER: str | None = None  # set to auth_service's issuer if it sets one
```

## Step 2 — add `app/auth.py`

Identical for all four services — uses the consolidated reference module
rather than yet another hand-rolled copy (see API9:2023 in
`OWASP_ANALYSIS.md` for why that matters: this is exactly how
`regime_detection_service`/`signal_aggregation_service` drifted into
AUTH-01 in the first place):

```python
# app/auth.py
from shared_security_lib.jwt_auth import JWTAuthConfig, JWTAuthDependencies
from app.core.config import settings  # adjust import path per service

_auth = JWTAuthDependencies(JWTAuthConfig(
    public_key_path=settings.AUTH_JWT_PUBLIC_KEY_PATH,
    algorithm=settings.AUTH_JWT_ALGORITHM,
    issuer=settings.AUTH_JWT_ISSUER,
    is_production=(settings.APP_ENV == "production"),
    dev_stub_roles=["analyst", "risk_officer"],  # adjust per service if needed
))

get_current_user = _auth.get_current_user_dependency
require_role = _auth.require_role
require_any_role = _auth.require_any_role
```

`shared_security_lib` needs to actually be installed/importable by each
service — either vendor the single `jwt_auth.py` file into each service's
`app/` (simplest, consistent with the platform's existing per-service
isolation), or package it as an internal pip dependency all 12 services
depend on (better long-term, more upfront work). Pick one approach
platform-wide rather than mixing — vendoring is the faster path to ship
this fix today.

## Step 3 — gate every endpoint

Minimum bar: every `POST`/`PUT`/`DELETE` endpoint gets a `require_role(...)`
dependency; every `GET` endpoint gets at least `get_current_user` so the
request has a real identity attached for logging/audit purposes (per
AUTH-00's blast-radius note — there is currently no identity at all on any
request to these 4 services).

```python
# broker_service/app/api/v1/endpoints/broker.py
from app.auth import get_current_user, require_role

@router.post("/orders", response_model=OrderResultResponse, ...)
async def place_order(
    ...,
    _user=Depends(require_role("trader")),   # or "risk_officer" — pick the
                                                # narrowest role that's actually
                                                # supposed to place live orders
):
    ...

@router.delete("/orders/{broker_order_id}", ...)
async def cancel_order(..., _user=Depends(require_role("trader"))):
    ...

@router.get("/positions", ...)
async def get_positions(..., _user=Depends(get_current_user)):
    ...

@router.post("/risk/reset-daily", ...)
async def reset_daily(..., _user=Depends(require_role("risk_officer"))):
    ...
```

Repeat the same pattern for every endpoint listed in
`AUTHENTICATION_REVIEW.md`'s AUTH-00 section, across all 4 services.
`strategy_service`'s `POST /reload` deserves particular care — it reloads
strategy code from disk, which is closer to a deploy action than a normal
API call; gate it to the narrowest role you have (`risk_officer` or a new
dedicated `platform_admin` role) rather than anything broader.

## Step 4 — propagate the JWT public key to these 4 containers

All 4 need the same Docker secret mount the other services already use
(`/run/secrets/auth_public_key.pem`, per the default path above) — check
each service's `docker-compose.yml` for whether the `secrets:` block
referencing `auth_public_key` is even present today; if these services were
scaffolded without auth, there's a good chance the secret mount was never
wired up either.

## Step 5 — verify, don't assume

None of this has been applied or run — write or update each service's
integration tests to assert a 401/403 on the previously-open endpoints
before considering this fix complete, per the platform's own testing rule
("all tests must pass before declaring a service complete").
