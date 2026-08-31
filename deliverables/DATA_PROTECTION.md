# Data Protection Review

## Encryption in transit

**Internal service-to-service traffic is plain HTTP, platform-wide** —
confirmed by absence of any TLS context, `https://` internal URL, or
`sslmode` configuration anywhere in the 12 services' code or compose files
(checked all `docker-compose*.yml` and Python source). For traffic confined
to a private Docker bridge network on a single host, this is a defensible,
common choice — but it is currently an *implicit* one, not a documented
decision. Make it explicit: if every service genuinely only ever talks to
another service over `sg_trading_net` and never crosses a host boundary
unencrypted, say so in the platform's architecture docs as a stated
assumption, so a future change (e.g. splitting services across multiple
hosts, or exposing any internal port to a network you don't fully trust)
gets flagged as "this assumption just broke" rather than silently
inheriting plaintext traffic across a boundary that used to be safe and no
longer is.

**Postgres connections have no `sslmode` configured** — same reasoning
applies; acceptable for same-host/same-private-network Postgres, worth
revisiting the moment `sg_db` is reachable from anywhere outside that
boundary (including the `postgres-exporter` / `DATA_SOURCE_NAME` setup in
this session's `observability_service` build — that connection string
should also specify `sslmode=require` or stronger the day Postgres stops
being purely localhost/internal-network-only).

## Encryption at rest

Not assessed at the infrastructure level (this audit reviewed application
code, not the host's disk/volume encryption configuration) — confirm
separately whether the Docker volumes backing `sg_db` sit on an encrypted
filesystem. At the application level: password hashes (`bcrypt`), TOTP
secrets, and backup code hashes are all stored as hashes/derived values,
not plaintext — correct. **Email addresses are stored in plain
`String(320)` columns** (`auth_service/app/models/auth.py`) — normal and
expected (the application needs the actual email to send mail), not a
finding on its own, but worth knowing for breach-notification scope: if
`auth_service`'s database were ever exfiltrated, every registered email
address is recoverable in full, in addition to (separately) the password
hashes.

## PII inventory

| Field | Table | Notes |
|---|---|---|
| `email` | `email_verification_tokens` and (presumed) the main users table | Plaintext, 320-char column — standard RFC 5321 max length, no truncation risk |
| `provider_email` | same area | OAuth-provider-supplied email, also plaintext |
| Password hash | users table (not directly inspected this session — inferred from `hash_password`/`verify_password` usage) | `bcrypt`, correctly hashed |
| TOTP secret | MFA table | Stored as the raw TOTP secret (required for `pyotp.TOTP(secret)` to keep working) — this is **not** a hashable credential the way a password is; it must be retrievable to generate the expected code, so encryption-at-rest of the *column itself* (not just the disk) is the relevant control here, not hashing. Not confirmed whether column-level encryption is applied — flag as a follow-up. |
| Backup codes | MFA backup codes table | Hashed (SHA-256, unsalted — see SEC-02) |

For a personal deployment, this is a low-severity inventory — there's one
real user. The reason to get the patterns right anyway: if `auth_service`
is ever reused for any multi-user purpose, the PII-handling patterns
established now (or not established now) are what ships, by default,
unless someone deliberately revisits them.

## Trading/portfolio data

Positions, trade ledger, P&L, and order history (`pm_*` tables in
`portfolio_management_service`) are financial records, not PII in the
strict sense for a single-user deployment, but are the platform's actual
business data and the thing an attacker would most want to either read
(confidentiality) or tamper with (integrity — e.g. to mask a loss or
fabricate a profitable track record). No field-level encryption found or
expected here (correctly — you need to query and aggregate this data
constantly; field-level encryption would make the FIFO/MTM logic
impractical). The relevant controls are access control (see
`AUTHENTICATION_REVIEW.md`/`AUTHORIZATION_REVIEW.md` — currently weak, per
AUTH-00/AUTH-01) and integrity (database-level — not assessed for
tamper-evidence such as audit triggers or append-only ledger enforcement
beyond what `pm_trade_ledger`'s schema implies).

## Data retention

Not governed by any explicit policy found in code — retention is whatever
Postgres holds indefinitely (no TTL/archival job found for `pm_*`, `bt_*`,
`ml_*`, or `ai_*` tables), except where this session's `observability_service`
build introduced explicit retention for logs (Loki, 30d) and traces (Tempo,
7d). `ai_audit_log` (8012) is documented elsewhere as the
compliance-grade, metadata-only record — confirm whether it has an intended
retention period (regulatory or otherwise) that the current
indefinite-retention default satisfies or violates; not assessed this
session.

## Recommendations

1. Document the "internal traffic is plaintext HTTP by design, confined to
   `sg_trading_net`" decision explicitly, so it's a decision rather than an
   assumption nobody wrote down.
2. Confirm TOTP secret column encryption (or accept the risk explicitly —
   for a personal deployment with disk-level encryption already in place,
   this may be a reasonable accepted risk, but make it a decision, not a
   gap nobody looked at).
3. Define an explicit retention policy per table family (`pm_*`, `bt_*`,
   `ml_*`, `ai_*`) even if the answer is "keep forever" — an explicit
   "forever, because X" beats an implicit "nobody set a TTL."
4. Apply `sslmode=require` (or stronger) to any Postgres connection string
   that crosses a network boundary you don't fully control — including the
   `postgres-exporter` connection introduced by `observability_service`,
   the moment that boundary assumption changes.
