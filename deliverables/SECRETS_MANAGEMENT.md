# Secrets Management Review

## Inventory of secrets on this platform

| Secret | Held by | Storage mechanism today |
|---|---|---|
| `JWT_PRIVATE_KEY` (RSA 4096 PEM) | `auth_service` only | Raw env var (`Field(...)`, required string) — see SEC-03 below |
| `JWT_PUBLIC_KEY` / public key file | All 9 verifying services | File path via `AUTH_JWT_PUBLIC_KEY_PATH`, default `/run/secrets/auth_public_key.pem` — Docker secrets convention |
| `KITE_API_KEY`, `KITE_API_SECRET`, `KITE_ACCESS_TOKEN` | `broker_service` | Raw env vars, default `""` |
| `POSTGRES_PASSWORD` | All services connecting to `sg_db` | Env var; 3 services have it hardcoded in committed `docker-compose.yml` (CFG-01) rather than `${VAR}`-substituted |
| User password hashes, TOTP secrets, backup code hashes | `auth_service` DB | Postgres, presumably encrypted at rest only to the extent the underlying volume/disk is — not assessed (see Data Protection review) |
| `TELEGRAM_BOT_TOKEN` (from this session's `observability_service` build) | Alertmanager bridge | `.env` file, gitignored — consistent with the rest of the platform |

## SEC-01 (MEDIUM) — No secrets manager

Every secret above is either a plain environment variable or a file mounted
via Docker's basic secrets feature (`/run/secrets/*`). There is no
Vault/AWS Secrets Manager/age-encrypted-file or equivalent in the stack.
For a personal deployment, **this is a reasonable, proportionate choice** —
introducing Vault for one person's trading bot is its own maintenance
burden and attack surface. The recommendation here is sized accordingly:

- **Do now, regardless of scale:** the `.gitignore` already correctly
  excludes `.env` and `*.pem` platform-wide (confirmed) — good, keep it
  that way as new services get added.
- **Do if this ever becomes multi-person or production-for-other-people's-money:**
  adopt a real secrets manager. The trigger condition is "someone other
  than you needs access to the deployment," not a calendar date — env vars
  don't support per-person access control, audit logging of who read a
  secret and when, or automated rotation, all of which start to matter the
  moment more than one person can `docker exec` into the host.
- **Do regardless, cheaply:** rotate `KITE_API_SECRET`/`KITE_ACCESS_TOKEN`
  on a schedule (Kite access tokens are typically short-lived/daily by
  Zerodha's own design — confirm `broker_service`'s token refresh logic
  actually re-authenticates rather than relying on a long-lived token that
  may silently stop working or, worse, be cached past its intended
  lifetime).

## SEC-03 (LOW–MEDIUM) — Private key stored as raw env var, inconsistent with the rest of the platform's pattern

`auth_service/app/core/config.py`:

```python
JWT_PRIVATE_KEY: str = Field(...)       # PEM — RSA 4096
JWT_PUBLIC_KEY: str = Field(...)        # PEM — RSA 4096
```

Both keys are read as plain strings from the environment. This is backwards
from a risk-proportionality standpoint: the **public** key (not sensitive —
it's public) is distributed to 9 other services via Docker's file-based
secrets mechanism (`/run/secrets/auth_public_key.pem`, restricted
permissions, not inherited by child processes the way env vars are), while
the **private** key (the single most sensitive secret on the entire
platform — whoever holds it can forge a valid identity for any user with
any role on any service) sits in `auth_service`'s own environment variables
alongside everything else.

Env vars are more exposure-prone than a permissioned file mount: they're
visible via `docker inspect`, appear in `/proc/<pid>/environ`, get
inherited by every child process the application spawns, and commonly end
up in crash dumps or accidental `os.environ` debug logging in a way a file
read explicitly by one function does not.

**Fix:** mount `JWT_PRIVATE_KEY` the same way the public key is mounted
downstream — as a file via Docker secrets — and have `auth_service` read it
with `Path(settings.JWT_PRIVATE_KEY_PATH).read_text()` rather than
`Field(...)` directly off the environment. This is a small change with an
outsized benefit given what this specific key protects.

## SEC-02 (LOW) — MFA backup code entropy and hashing

Already detailed with a concrete fix in `fixes/QUICK_PATCHES.md` item 4 —
32 bits of entropy (`secrets.token_hex(4)`) and unsalted SHA-256 storage.
Repeated here because it's a secrets-management issue as much as an
authentication one: a backup code is, functionally, a low-entropy
long-lived credential, and should be treated with the same "what happens if
the hash table leaks" scrutiny as a password.

## Kite credential blast radius

`broker_service/app/brokers/kite/broker.py` already masks the API key in
one specific log line:

```python
account_id=settings.KITE_API_KEY[:8] + "****"
```

This is good practice, applied in exactly one place. It does not generalize
— any other log statement in `broker_service` (or any of its dependencies'
logging) that happens to include the full secret or access token is not
caught by anything, since `broker_service` has no general redaction
processor (LOG-01). Given this service holds the one secret on the
platform that's directly equivalent to "control of the brokerage account,"
it should be the **first**, not the last, service to get the
`shared_security_lib/redaction.py` processor applied.

## Recommendations, in order of cost-to-benefit

1. Apply `shared_security_lib/redaction.py` to `broker_service` first,
   then platform-wide (cheap, immediate risk reduction for the highest-value secret).
2. Fix SEC-03 (move `JWT_PRIVATE_KEY` to a file mount) — moderate effort,
   addresses the single highest-blast-radius secret on the platform.
3. Fix SEC-02 (backup code entropy + salted hash) — cheap, isolated change.
4. Fix CFG-01 (stop committing `POSTGRES_PASSWORD: sg`) — trivial, already
   has a one-line fix in `fixes/QUICK_PATCHES.md`.
5. Defer a real secrets manager until the trigger condition above
   (multi-person access) is actually met.
