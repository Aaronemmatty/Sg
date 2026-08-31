# Threat Model — SG Trading Platform

Method: STRIDE per trust boundary, walking the frozen pipeline
(`signal_aggregation → regime_detection → execution_orchestrator →
risk_engine → execution_engine → portfolio_management`) plus the two
offline analyst services and the Kite brokerage boundary. Each section
lists the boundary, the assets crossing it, and the threats that are either
**confirmed exploitable** (code-verified this session) or **plausible but
unconfirmed** (architectural reasoning only — no code access to that gap
yet, or simply out of scope for this pass).

## Assets

- **Capital** — the actual money the platform trades with. Ultimate target.
- **Trading decisions** — signals, regime classifications, risk
  approvals/rejections, orders. Tampering here = financial loss without
  ever touching credentials.
- **Brokerage credentials** — `KITE_API_KEY`, `KITE_API_SECRET`,
  `KITE_ACCESS_TOKEN`. Direct capital-equivalent: holding these is
  equivalent to holding the brokerage session itself.
- **JWT signing key** (`JWT_PRIVATE_KEY`, `auth_service` only) — compromise
  here means forging valid identity/authorization for every other service
  on the platform simultaneously.
- **User credentials & PII** — password hashes, TOTP secrets, backup codes,
  email addresses in `auth_service`'s database.
- **Historical/portfolio data** — P&L, positions, trade history. Less
  immediately weaponizable than the above, but a confidentiality target
  (insider-trading-adjacent value if this were ever multi-tenant) and an
  integrity target (tampering with `pm_*` tables could mask real losses).

## Trust boundary 1 — Internet/operator ⇄ any service's REST API

**Threat actor:** anyone who can reach an exposed port. For a personal
deployment this is nominally "just you," but Docker port mapping mistakes,
a future cloud deployment, or a compromised machine on the same LAN all
turn "internal" into "internet-reachable" without anyone deciding that on
purpose.

| STRIDE | Threat | Status |
|---|---|---|
| Spoofing | Forge a request as an authenticated user | **Confirmed exploitable, two distinct ways.** (1) `market_data_service`, `strategy_service`, `execution_orchestrator_service`, `broker_service` have no authentication mechanism at all — AUTH-00 — so there is no identity to spoof, every caller is already "anyone." (2) `regime_detection_service`/`signal_aggregation_service` fail open when the public key is missing — AUTH-01. |
| Tampering | Place, modify, or cancel a live brokerage order directly | **Confirmed exploitable** — `broker_service`'s `POST /api/v1/orders`, `PUT /api/v1/orders/{id}`, `DELETE /api/v1/orders/{id}` have zero authentication (AUTH-00). This bypasses the entire risk_engine/execution_orchestrator decision chain entirely — an attacker doesn't need to fool the pipeline, they can skip it. |
| Tampering | Trigger `POST /recalculate` to force expensive recomputation or feed bad data into the pipeline | **Confirmed reachable** unauthenticated via the AUTH-01 gap. |
| Repudiation | No audit trail ties a request back to a real identity when AUTH-00 or AUTH-01 is active | Confirmed — there is no identity to repudiate in the first place under either condition. |
| Information Disclosure | JWT decode error messages leak library/claim internals | Confirmed (AUTH-02) — low impact alone, useful as fingerprinting in a chained attack. |
| Denial of Service | Hammer any of the 10 unprotected services' endpoints | **Confirmed exploitable** (RATE-01) — no rate limiting exists to stop it. Combine with AUTH-00/AUTH-01's free authentication and the most expensive endpoints on the platform (`recalculate`, order placement) become a particularly cheap DoS/abuse vector. |
| Elevation of Privilege | Hold a token with `roles: ["admin"]` issued for an unrelated purpose, use it against `risk_engine_service` | **Confirmed exploitable** (AUTHZ-01) — any "admin"-tagged token bypasses every role check in the platform's risk gate, not just the endpoints actually meant for admins. |

## Trust boundary 2 — service ⇄ service (internal Docker network)

**Threat actor:** a compromised container on the same `sg_trading_net`
(e.g. via a dependency RCE in one of the 6 root-running containers —
DOCKER-01 — or a supply-chain compromise of any pinned package).

| STRIDE | Threat | Status |
|---|---|---|
| Tampering | A compromised service publishes forged messages onto `sg:*` Redis channels (e.g. fake `sg:risk_approved:{symbol}` to push an order past risk checks) | **Plausible, unconfirmed** — Redis pub/sub has no per-publisher authentication; any container that can reach Redis can publish to any channel. Not code-reviewed for a channel-level ACL or message-signing scheme this session — recommend checking `risk_engine_service`'s consumer for `sg:intents:{symbol}` to see if it validates message provenance beyond schema shape. |
| Information Disclosure | A compromised root container (DOCKER-01) reads other services' mounted secrets if Docker secrets are shared via the same mount path/volume | **Plausible** — root inside a container with a shared volume mount has a meaningfully larger blast radius than a non-root user scoped to its own files. |
| Elevation of Privilege | A compromised service uses its own valid (but narrowly-scoped) JWT/role to call an endpoint it shouldn't reach, exploiting AUTHZ-01's admin-bypass if it can obtain or forge an admin-tagged token | Confirmed mechanism exists (AUTHZ-01); requires a separate initial compromise to have a token to begin with. |

## Trust boundary 3 — platform ⇄ Zerodha Kite (brokerage)

**Threat actor:** anyone who obtains `KITE_API_SECRET` / `KITE_ACCESS_TOKEN`
— this is the closest thing to "anyone who obtains the keys to the brokerage
account itself."

| STRIDE | Threat | Status |
|---|---|---|
| Information Disclosure | Credentials leak via logs | **Partially mitigated** — `broker_service` already masks the API key in one specific log line (`account_id=settings.KITE_API_KEY[:8] + "****"`), but has no general redaction processor (LOG-01), so any other log statement that happens to include the full secret/token is not caught. |
| Information Disclosure | Credentials leak via a 500 error / stack trace returned to a caller | Not specifically tested against `broker_service`'s exception handlers this session — recommend a follow-up pass specifically fuzzing broker_service's error paths for credential leakage, given the asymmetric cost of getting this one wrong. |
| Repudiation | An order is placed and there's no way to prove which internal actor/service caused it | `ExecutionEvent`'s frozen contract carries `correlation_id`/`intent_id` end-to-end, which is good provenance *between services* — but if AUTH-01 is exploited upstream, the `correlation_id` chain still traces back to an unauthenticated origin with no real identity behind it. |

## Trust boundary 4 — operator ⇄ auth_service (identity root of trust)

`auth_service` is the single point that, if compromised, compromises every
other trust decision on the platform (it mints the tokens every other
service trusts).

| STRIDE | Threat | Status |
|---|---|---|
| Tampering | Forge a token without the private key | Not possible without the key — algorithm is pinned to RS256 everywhere checked, no "none" algorithm or HS256-confusion path found. |
| Information Disclosure | `JWT_PRIVATE_KEY` leaks | Not assessed where this key is actually stored at rest this session (env var presumably, per platform convention) — see `SECRETS_MANAGEMENT.md` for the recommendation. If it leaks, the blast radius is "every service, indefinitely, with no detection" given AUTH-03 (no key rotation/kid support) — there is currently no mechanism to revoke a compromised key without restarting all 9 verifying services with a new key file. |
| Elevation of Privilege | A backup MFA code is brute-forced (32 bits of entropy, SEC-02) | Plausible if the verification endpoint isn't independently rate-limited (not confirmed checked this session) — flagged as an open item in `AUTHENTICATION_REVIEW.md`. |

## What this threat model deliberately does not claim

- It does not claim these are the *only* threats — it's bounded by what
  code was actually reviewed this session (see `EXECUTIVE_SUMMARY.md`
  scope note).
- "Plausible, unconfirmed" items are architectural reasoning from the
  frozen Redis/REST contracts documented in prior handovers, not from
  reading the relevant consumer code line-by-line. Treat them as a
  prioritized follow-up list, not a verified finding.
