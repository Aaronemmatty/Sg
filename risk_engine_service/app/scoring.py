from __future__ import annotations

from app.models import CheckResult, RiskBand

# Weights sum to 1.0 across factors that have a continuous "value vs
# threshold" reading. Boolean-only checks (margin, circuit breaker, sizing)
# contribute through hard rejection rather than score weighting, since they
# are binary gates, not graduated risk.
WEIGHTS = {
    "var": 0.30,
    "concentration": 0.20,
    "sector_exposure": 0.10,
    "correlation": 0.15,
    "volatility": 0.15,
    "drawdown": 0.05,
    "daily_loss": 0.05,
}


def _normalized_pressure(check: CheckResult) -> float:
    """Returns a 0..1+ "pressure" ratio of value/threshold. Values beyond
    the threshold push above 1.0 (capped at 1.5 for score stability);
    missing/skipped checks contribute 0 pressure."""
    if check.value is None or check.threshold is None or check.threshold == 0:
        return 0.0
    ratio = abs(check.value) / abs(check.threshold)
    return min(ratio, 1.5)


def compute_risk_score(checks: dict[str, CheckResult]) -> tuple[float, RiskBand]:
    score = 0.0
    for factor, weight in WEIGHTS.items():
        check = checks.get(factor)
        if check is None:
            continue
        pressure = _normalized_pressure(check)
        score += weight * pressure * 100.0

    # Any hard-failed check (regardless of weighting) pulls the score
    # toward CRITICAL since it represents a breached guardrail, not just
    # elevated pressure.
    hard_fail_count = sum(1 for c in checks.values() if not c.passed)
    if hard_fail_count > 0:
        score = max(score, 75.0 + min(hard_fail_count, 5) * 5.0)

    score = max(0.0, min(score, 100.0))

    if score <= 30:
        band = RiskBand.LOW
    elif score <= 60:
        band = RiskBand.MEDIUM
    elif score <= 80:
        band = RiskBand.HIGH
    else:
        band = RiskBand.CRITICAL

    return round(score, 2), band
