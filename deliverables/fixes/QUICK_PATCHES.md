# Quick-Apply Patches

Small, surgical diffs — not worth a full file replacement, but each maps to
a real finding in the review docs.

## 1. CORS — wildcard origin + credentials (CRITICAL)

**Finding:** `market_data_service`, `execution_orchestrator_service`,
`strategy_service`, `broker_service` all configure:

```python
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, ...)
```

`allow_origins=["*"]` combined with `allow_credentials=True` is invalid per
the Fetch spec (browsers will reject the actual cross-origin credentialed
request), but Starlette doesn't stop you from configuring it, and it's a
loud signal of copy-pasted config that was never meant to reach production —
`auth_service` already does this correctly:

```python
allow_origins=[str(o) for o in settings.ALLOWED_ORIGINS],
```

**Fix — apply to all 4 services:**

```python
# main.py — replace the wildcard with the same settings-driven pattern auth_service uses
app.add_middleware(
    CORSMiddleware,
    allow_origins=[str(o) for o in settings.ALLOWED_ORIGINS],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

This requires each of the 4 services' `Settings` class to actually define
`ALLOWED_ORIGINS` (copy the field from `auth_service/app/core/config.py`) if
it doesn't already exist there — check before assuming the field is missing
vs. just unused.

If any of these 4 services genuinely has no browser-facing client (e.g.
`strategy_service` is only ever called server-to-server), the more correct
fix is to **drop CORSMiddleware entirely** rather than configure it
permissively — CORS only matters for browser-originated requests in the
first place.

## 2. Dockerfiles running as root (MEDIUM)

**Finding:** 6 of 14 Dockerfiles have no `USER` directive and therefore run
as root inside the container: `portfolio_management_service`,
`risk_engine_service`, `execution_engine_service`, `ai_analyst_service`,
`ml_platform_service`, `backtesting_engine_service`. The other 8 services
already do this correctly.

**Fix — add to each affected Dockerfile**, matching the pattern the other 8
already use (check `auth_service/Dockerfile` for the exact existing
convention to copy verbatim rather than inventing a new one):

```dockerfile
RUN groupadd -r appuser && useradd -r -g appuser appuser
# ... COPY/RUN steps that need root (e.g. pip install) happen above this line ...
USER appuser
```

Ensure file ownership of `/srv/app` is set to `appuser` before the `USER`
line (`COPY --chown=appuser:appuser . .` or a `chown` RUN step), or the
container will fail to start with a permissions error — don't just append
`USER appuser` at the bottom without checking this.

## 3. Plaintext Postgres password in committed docker-compose files (LOW–MEDIUM)

**Finding:** `market_data_service/docker-compose.yml`,
`auth_service/docker-compose.yml`, `strategy_service/docker-compose.yml` all
have:

```yaml
POSTGRES_PASSWORD: sg
```

committed directly (not `${POSTGRES_PASSWORD}`). Low severity for a
personal/local deployment, but exactly the kind of value that gets copied
verbatim into a "production" compose file later by someone in a hurry.

**Fix:**

```yaml
POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?Set POSTGRES_PASSWORD in .env}
```

The `:?` form makes Compose refuse to start without the variable set,
rather than silently falling back to a weak default — preferable to a
`:-default` fallback for anything credential-shaped.

## 4. MFA backup code entropy (LOW)

**Finding:** `auth_service/app/core/security.py`:

```python
def generate_backup_codes(n: int = 10) -> list[str]:
    return [secrets.token_hex(4).upper() for _ in range(n)]
```

`token_hex(4)` = 4 bytes = 32 bits of entropy per code (8 hex chars). Not
trivially guessable, but thin for a credential meant to substitute for MFA
during account recovery — and `hash_backup_code()` uses unsalted SHA-256, so
if the `auth_db` backup-codes table ever leaks, every code becomes an
offline dictionary/brute-force target with no per-code or per-user salt
slowing an attacker down.

**Fix:**

```python
def generate_backup_codes(n: int = 10) -> list[str]:
    # 5 bytes = 40 bits — still short/typeable, meaningfully harder to
    # brute-force than 32 bits if the hash table ever leaks.
    return [secrets.token_hex(5).upper() for _ in range(n)]

def hash_backup_code(code: str, *, pepper: str) -> str:
    # `pepper` = a server-side secret (e.g. from the same secrets manager
    # holding JWT_PRIVATE_KEY), NOT stored alongside the hash in the DB.
    # Turns an offline brute-force of a leaked hash table into one that
    # also requires the pepper, which a DB-only breach doesn't expose.
    return hashlib.sha256((pepper + code).encode()).hexdigest()
```

Also confirm (not checked in this pass — see AUTHENTICATION_REVIEW.md open
item) that the backup-code *verification* endpoint in `auth_service` is
itself rate-limited; short codes are only as safe as the attempt budget an
attacker gets to guess them online.

## 5. Confirm before treating as fixed

None of the above were tested against a running stack (no network in the
build sandbox — same caveat as every other deliverable this session). Run
each service's test suite after applying, and for the CORS fix specifically,
confirm `ALLOWED_ORIGINS` is actually populated correctly per environment
before deploying — an empty list silently blocks every legitimate browser
client just as effectively as the wildcard let in illegitimate ones.
