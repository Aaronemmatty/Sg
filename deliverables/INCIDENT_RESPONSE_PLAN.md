# Incident Response Plan — SG Trading Platform

This is a personal deployment with (today) a one-person incident response
team — that person. The plan below is sized for that reality: clear
severity tiers, a short playbook per likely incident type, and explicit
use of the `observability_service` stack (Prometheus/Grafana/Loki/Tempo/
Alertmanager→Telegram) already built, since that's the detection
infrastructure that exists today.

## Severity tiers

| Tier | Definition | Examples from this audit |
|---|---|---|
| **SEV-1** | Active financial loss, or capability for one, in progress | `broker_service` order endpoints being hit by an unknown caller (AUTH-00); `risk_kill_switch_active` firing for real |
| **SEV-2** | A security control has failed but no confirmed exploitation yet | A service crash-loops because its auth public key mount broke (would trigger AUTH-01's fail-open path if unpatched); a credential is suspected (not confirmed) leaked |
| **SEV-3** | A finding or anomaly that needs investigation but isn't actively dangerous | An unexpected spike in 401/403 responses; a dependency advisory is published for a package this platform uses |

## Detection — what's actually watching, today

Before this audit, **nothing was watching for any of this.** The
`observability_service` built earlier in this engagement is the first time
the platform had alerting at all. Relevant wiring, as it stands:

- `ServiceDown`, `HighHttp5xxRate` — would catch a service crash-looping,
  not a silent auth bypass succeeding.
- **No existing alert detects AUTH-00 or AUTH-01 being exploited** — there
  is no metric today counting "requests that reached a mutating endpoint
  with no valid identity," because until this audit, no service
  distinguished that case from a normal authenticated request. This is a
  detection gap, not just a prevention gap — fixing AUTH-00/AUTH-01 (so
  unauthenticated requests are rejected) is necessary but not sufficient;
  also add a counter/log line for "request rejected for missing/invalid
  auth" and alert on a sustained spike in it, which is a leading indicator
  of either an attack or (more likely, for a personal deployment) a broken
  deployment of the very fix this audit recommends.
- `RiskKillSwitchActive`, `BrokerCircuitBreakerOpen` (from
  `observability_service`'s domain alerts) — genuinely useful SEV-1
  detection once the underlying metrics they assume exist are confirmed
  (see that service's `OPEN_ITEMS.md`).

**Action item:** add a `UnauthenticatedRequestSpike` alert once AUTH-00/
AUTH-01 are fixed and each service is actually emitting a
"rejected — no/invalid auth" counter. This is the single highest-value new
alert this audit's findings motivate.

## Playbook: suspected unauthorized order activity (SEV-1)

Trigger: an order in `broker_service`/`portfolio_management_service` you
don't recognize placing it, or `RiskKillSwitchActive` fires with no
corresponding action you took.

1. **Stop new orders immediately.** If the kill switch hasn't already
   engaged itself, engage it manually (mechanism not currently documented
   anywhere in the platform per `RUNBOOK.md`'s existing open item — confirm
   this *before* you need it, not during the incident).
2. **Cut `broker_service`'s network access** (`docker network disconnect`
   or stop the container) — this stops new orders from reaching Kite even
   if the kill switch mechanism itself is unclear under pressure.
3. **Rotate `KITE_API_SECRET`/`KITE_ACCESS_TOKEN` immediately** via
   Zerodha's developer console — assume the credential is compromised
   until proven otherwise; this is cheap and fast relative to the
   alternative.
4. **Check `broker_service`'s access logs** (now flowing into Loki per
   `observability_service`) for the source IP/timing of the suspicious
   order(s). Given AUTH-00, there is currently no caller identity to check
   — only network-level provenance (IP, timing) until that fix ships.
5. **Reconcile actual positions against `pm_*` ledger** — confirm
   `portfolio_management_service`'s view of the world matches what Kite
   itself reports, since an attacker who bypassed `risk_engine`/
   `execution_orchestrator` entirely (possible today via AUTH-00) may have
   placed orders that never appear correctly in the normal pipeline's
   event trail.
6. **Apply the AUTH-00 fix** (`fixes/AUTH-00_4_SERVICES_PATCH.md`) before
   bringing `broker_service` back online — do not restore service first
   and patch later for this specific finding.
7. **Post-incident:** add the `UnauthenticatedRequestSpike` alert above,
   and review whether the host's network exposure (port mapping, firewall
   rules) let this happen in the first place — the application-layer fix
   matters, but so does why an application-layer-only defense was the only
   thing standing between the internet and a brokerage account.

## Playbook: suspected JWT signing key compromise (SEV-1)

Trigger: `auth_service`'s host or `JWT_PRIVATE_KEY` is suspected exposed
(e.g. accidental commit, host compromise, leaked env var dump).

1. **Generate a new RSA 4096 keypair immediately.**
2. **Update `auth_service`'s `JWT_PRIVATE_KEY`** — per `SECRETS_MANAGEMENT.md`
   SEC-03, this should be a file-mounted secret, not a raw env var; rotating
   it means replacing that mounted file and restarting `auth_service`.
3. **Update the public key everywhere it's consumed** — per AUTH-03, this
   means restarting all 9 services that verify tokens locally (or, once
   the TTL-based cache refresh in `shared_security_lib/jwt_auth.py` is
   adopted platform-wide, waiting up to `PUBLIC_KEY_CACHE_TTL_SECONDS`
   instead of restarting — but don't rely on that until it's actually
   deployed everywhere).
4. **All existing tokens signed with the old key remain cryptographically
   valid until their natural `exp`** on any service still holding the old
   public key — there is no revocation list. Until every service has the
   new key loaded, an attacker holding the old private key can still mint
   accepted tokens against whichever services haven't rotated yet. Treat
   the rotation as incomplete, and the incident as ongoing, until you've
   confirmed (via each service's logs, or a quick synthetic request) that
   every one of the 9 verifying services has the new key.
5. **Force-expire active sessions** in `auth_service`'s own session store
   if it maintains one independent of token `exp` (the handover describes
   `auth_service` as having "sessions" — confirm the revocation mechanism
   exists and use it; not directly reviewed this session).
6. **Post-incident:** this is the scenario AUTH-03 makes worse than it
   needs to be — prioritize a real JWKS/`kid`-based rotation mechanism
   so a future key rotation doesn't require a coordinated 9-service
   restart under pressure.

## Playbook: suspected exploitation of AUTH-00 / AUTH-01 (no financial loss yet)

Trigger: Loki logs show requests to `regime_detection_service`,
`signal_aggregation_service`, `market_data_service`, `strategy_service`, or
`execution_orchestrator_service` from an unexpected source, or
`POST /recalculate`/`POST /api/v1/intents`/`POST /instances` fired without
you triggering it.

1. Treat as SEV-2 unless `execution_orchestrator_service`'s
   `POST /api/v1/intents` was hit (escalate to SEV-1 — that one can reach
   the live execution path).
2. Check whether the call actually carried a valid token (if AUTH-01's
   public-key-missing condition was active, it won't have — that's
   diagnostic) or no `Authorization` header at all (AUTH-00 services).
3. Apply the relevant fix from `fixes/` immediately rather than only
   investigating — the fix is known and ready; don't leave the gap open
   while investigating who walked through it.
4. Check `regime_detection_service`/`signal_aggregation_service`'s
   container logs around the incident time for `auth_dev_stub_user_active`
   or `auth_public_key_missing_in_production` log lines (present in both
   the old and fixed code) — these directly confirm whether AUTH-01's
   condition was active during the window in question.

## Communications

Single-operator deployment — no formal stakeholder communications process
needed today. If this ever changes (co-founder, investor, customer), define
before you need it:
- Who gets told, in what order, within what time.
- What gets disclosed externally vs. kept internal, especially for
  anything PII-adjacent (per `DATA_PROTECTION.md`'s email-address inventory)
  — most jurisdictions' breach-notification rules key off *confirmed*
  unauthorized access to PII, not just a vulnerability existing, so know
  the difference before an incident forces you to decide under pressure.

## Post-incident review

For any SEV-1/SEV-2: write down what happened, when it was detected vs.
when it actually started (the gap between those two is usually the most
actionable number), which fix in this audit (if any) would have prevented
or shortened it, and whether `observability_service`'s alerting actually
fired the way it was designed to. Feed the answer back into both this
document and the alert rules themselves.
