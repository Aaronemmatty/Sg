# SG Trading Platform — Security Audit Deliverables

Principal-Security-Engineer-level audit of all 12 services, based on direct
code review of the actual source (`sg_-_Copy.zip`, uploaded this session) —
not just the architecture described in prior handover documents.

**Start here:** `EXECUTIVE_SUMMARY.md` — severity-ranked findings table and
recommended sequencing.

## Reading order

1. `EXECUTIVE_SUMMARY.md` — the headline finding and full findings table.
2. `THREAT_MODEL.md` — STRIDE per trust boundary across the trading pipeline.
3. `OWASP_ANALYSIS.md` — OWASP API Security Top 10 (2023) + Top 10 (2021) mapping.
4. `AUTHENTICATION_REVIEW.md` — deep dive, AUTH-00 through AUTH-04.
5. `AUTHORIZATION_REVIEW.md` — deep dive, AUTHZ-01 and role-system gaps.
6. `SECRETS_MANAGEMENT.md` — credential inventory, SEC-01 through SEC-03.
7. `DATA_PROTECTION.md` — encryption, PII inventory, retention.
8. `INCIDENT_RESPONSE_PLAN.md` — severity tiers and playbooks tied to the actual findings above, leveraging the `observability_service` stack built earlier this engagement.
9. `fixes/` — actual code. See below.

## `fixes/` — what's actually drop-in-able

```
fixes/
├── QUICK_PATCHES.md                          CORS, Dockerfile USER, compose secrets, backup-code entropy
├── AUTH-00_4_SERVICES_PATCH.md               step-by-step: adding auth where none exists
├── shared_security_lib/
│   ├── jwt_auth.py                           consolidated, hardened JWT verification (replaces 9 drifted copies)
│   ├── rate_limit.py                         Redis rate limiter — middleware + per-route dependency
│   ├── redaction.py                          structlog secret-redaction processor, generalized from 8012's
│   └── validation.py                         symbol/strategy/timeframe input validation (regex allow-lists)
├── regime_detection_service/app/core/security.py    drop-in fix for AUTH-01
├── signal_aggregation_service/app/core/security.py  drop-in fix for AUTH-01
└── risk_engine_service/app/auth.py                  drop-in fix for AUTHZ-01
```

All Python files in `fixes/` were syntax-checked (`python3 -m py_compile`)
this session. **None were run against a live service or test suite** — no
network access in the build sandbox to pull dependencies or stand up a real
stack. Run each affected service's existing test suite after applying a
fix, per the platform's own rule that all tests must pass before a service
is considered complete.

## Severity-1 items — fix these before anything else

- **AUTH-00**: `market_data_service`, `strategy_service`,
  `execution_orchestrator_service`, `broker_service` have **no
  authentication at all**. `broker_service` places real brokerage orders.
- **AUTH-01**: `regime_detection_service`, `signal_aggregation_service`
  authenticate every request as valid (including the unauthenticated
  caller) when their JWT public key file is missing — including in
  production.

Everything else in this audit matters, but these two are the difference
between "this platform has authentication" and "it doesn't, in 6 of 12
services, under realistic conditions."

## What this audit did not cover

- The React dashboard (`sg-dashboard/`) — frontend XSS/CSP review not done.
- Dependency CVE scanning — no network access in the audit sandbox to check
  installed package versions against advisory databases.
- Load/penetration testing of any kind — this is a code-review-based audit,
  not a live pentest.
- Full read of every file in every service — this audit prioritized
  breadth across all 12 services on the categories requested (auth, authz,
  secrets, data protection) over an exhaustive line-by-line read of every
  module; see each review doc's "Open items" section for what's flagged as
  not-yet-confirmed rather than silently assumed fine.
