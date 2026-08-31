# Authorization Review

Authentication (who are you) and authorization (what can you do) are
reviewed separately deliberately — `AUTHENTICATION_REVIEW.md` covers the
former; this covers role/permission enforcement once a caller is
authenticated.

## AUTHZ-01 (HIGH) — Platform-wide "admin" bypass in risk_engine_service

`risk_engine_service/app/auth.py`:

```python
def require_role(role: str):
    async def _dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.has_role(role) and not user.has_role("admin"):
            raise HTTPException(status_code=403, detail=f"Requires role '{role}'")
        return user
    return _dependency
```

No other service implements this pattern (checked all nine `auth.py`/
`security.py` files) — every other `require_role()` checks only the exact
role requested. In `risk_engine_service` specifically — the platform's
pre-trade risk gate, holding VaR/drawdown/exposure/kill-switch logic — any
caller whose token carries `roles: [..., "admin"]` silently passes *every*
role check in the service, regardless of what the endpoint actually
required. This collapses whatever fine-grained role design exists in this
service (presumably distinguishing read-only analysts from
risk-officer-level actions) down to a single tier for anyone holding that
one role claim.

**Is this intentional?** Possibly — a "break-glass" admin override for a
risk-critical service isn't an unreasonable thing to want. But if so, it
needs to be:
- Documented as a deliberate decision (it currently isn't, anywhere),
- Audited specifically (every use of the admin bypass should be logged
  distinctly from a normal role match — currently it isn't, the log line
  is identical either way),
- Scoped to only the operations that genuinely need an override (e.g.
  clearing the kill switch), not silently applied to *every* role-gated
  endpoint in the service.

**Fix provided:** `fixes/risk_engine_service/app/auth.py` removes the
implicit bypass and adds an explicit, separately-named
`require_any_role(["risk_officer", "platform_admin"])` helper for the
specific endpoints (if any) that genuinely need a multi-role gate — apply
it deliberately, endpoint by endpoint, rather than restoring a blanket
bypass.

## Role vocabulary is inconsistent across services

Roles observed in dev-stub fallbacks and `require_role()` calls across the
codebase: `analyst`, `risk_officer`, `ml_engineer`, `admin`, `trader`,
`platform_admin` (the last two introduced by this audit's fixes, not found
in the original code). There is no single source of truth enumerating
"these are the platform's roles and what each one can do" — each service's
dev-stub fallback just lists whatever roles its own author happened to
think it needed. `auth_service` presumably owns the canonical role list
(since it issues the tokens), but nothing in the 9 downstream services'
code constrains what role *strings* they'll accept — a typo'd role name in
a token would simply fail every `require_role()` check silently (safe
direction to fail), but there's also nothing stopping `auth_service` from
issuing a role string that no downstream service recognizes, with no
warning anywhere that the role is meaningless.

**Recommendation:** maintain one enum/constant list of valid roles, shared
between `auth_service` (who issues them) and the `shared_security_lib`
reference module (who checks them) — even a simple
`shared_security_lib/roles.py` with a `class Role(str, Enum): ...` that
every service imports rather than hardcoding role strings, would catch a
typo at token-issuance time instead of silently producing a token nobody
downstream will ever match.

## Permissions claim is issued but never checked

`auth_service/app/core/security.py`'s `create_access_token()` accepts and
embeds a `permissions: list[str]` parameter (serialized as `perms` in the
JWT payload) — clearly designed for fine-grained, permission-level
authorization as a complement to coarse role-based checks. **No downstream
service reads the `perms` claim anywhere** (confirmed — `grep`'d
`perms`/`permissions` usage across all 9 verification sites; only
`shared_security_lib/jwt_auth.py`, written as part of this audit's fix,
reads it at all, as a fallback if `roles` is absent). This means
`auth_service` has built half of a two-tier authorization system, and the
other half was never implemented downstream. Either:
- Build out permission-level checks downstream to actually use this claim
  (worth it if the role vocabulary above ever needs finer grain than
  "analyst can do X, risk_officer can do Y"), or
- Stop issuing `perms` if nothing will ever check it — an unused claim
  that *looks* like an active security control is worse than no claim at
  all, because it creates false confidence that fine-grained authorization
  exists when it doesn't.

## Tenant isolation claim is issued but never checked

Same pattern as above for `tid` (tenant_id) — issued by `auth_service`,
present in every token, never checked against the resource being accessed
by any downstream service (see API1:2023 in `OWASP_ANALYSIS.md`). Low
practical risk today (single-tenant personal deployment), but flagged here
because it's the same "claim exists, nothing checks it" pattern as
`perms` — worth fixing both at once if either gets addressed, since the
plumbing (read the claim in `shared_security_lib`, plumb it through to a
"does this resource belong to this tenant" check at the repository layer)
is the same shape of work.

## What's solid

- Where role checks *do* exist (8 of 9 services' `require_role()`,
  excluding `risk_engine_service`'s bypass), they correctly check the exact
  role requested, no more, no less.
- `ai_analyst_service`'s admin endpoints (`/admin/prompts`,
  `/admin/audit/summary`) are correctly gated to `risk_officer` per the
  platform's existing documentation, and that gate is enforced in code
  (not just documented).

## Open items

- Whether `execution_engine_service`'s "manual order cancellation override"
  (mentioned in its own `auth.py` docstring as a `risk_officer`-gated
  action) is actually wired to `require_role("risk_officer")` at the
  relevant endpoint, vs. just described in a comment, was not directly
  confirmed against the endpoint file this session — verify before
  assuming the docstring matches the code.
- Function-level authorization for the 4 services fixed under AUTH-00 is
  entirely new (there was no authorization to review because there was no
  authentication to hang it on) — the role assignments suggested in
  `fixes/AUTH-00_4_SERVICES_PATCH.md` are reasonable defaults, not a
  reviewed, final role design. Confirm them against how you actually want
  `broker_service`'s order endpoints gated before shipping.
