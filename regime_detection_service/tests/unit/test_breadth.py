from __future__ import annotations

import pytest

from app.core.breadth import BreadthCalculator
from app.models.domain import RegimeType


def test_breadth_risk_on_when_majority_advancing():
    calc = BreadthCalculator(risk_on_threshold=0.6, risk_off_threshold=0.4)
    pct_changes = {f"sym{i}": 0.01 for i in range(8)} | {f"sym{i}": -0.01 for i in range(8, 10)}
    snapshot = calc.compute(pct_changes)
    assert snapshot.breadth_regime == RegimeType.RISK_ON
    assert snapshot.advancing == 8
    assert snapshot.declining == 2
    assert calc.is_extreme(snapshot) is True


def test_breadth_risk_off_when_majority_declining():
    calc = BreadthCalculator(risk_on_threshold=0.6, risk_off_threshold=0.4)
    pct_changes = {f"sym{i}": -0.01 for i in range(8)} | {f"sym{i}": 0.01 for i in range(8, 10)}
    snapshot = calc.compute(pct_changes)
    assert snapshot.breadth_regime == RegimeType.RISK_OFF
    assert calc.is_extreme(snapshot) is True


def test_breadth_neutral_is_not_extreme():
    calc = BreadthCalculator(risk_on_threshold=0.6, risk_off_threshold=0.4)
    pct_changes = {f"sym{i}": 0.01 for i in range(5)} | {f"sym{i}": -0.01 for i in range(5, 10)}
    snapshot = calc.compute(pct_changes)
    assert calc.is_extreme(snapshot) is False


def test_breadth_raises_on_empty_input():
    calc = BreadthCalculator()
    with pytest.raises(ValueError):
        calc.compute({})


def test_breadth_counts_unchanged():
    calc = BreadthCalculator()
    pct_changes = {"a": 0.0, "b": 0.01, "c": -0.01, "d": 0.0}
    snapshot = calc.compute(pct_changes)
    assert snapshot.unchanged == 2
    assert snapshot.advancing == 1
    assert snapshot.declining == 1
    assert snapshot.universe_size == 4
