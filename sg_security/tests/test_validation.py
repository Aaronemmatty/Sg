import pytest

from sg_security.validation import validate_strategy_name, validate_symbol, validate_timeframe


def test_validation_accepts_expected_values():
    assert validate_symbol("RELIANCE") == "RELIANCE"
    assert validate_timeframe("5m") == "5m"
    assert validate_strategy_name("trend_following") == "trend_following"


@pytest.mark.parametrize("value", ["../bad", "RELIANCE/", "", "bad symbol"])
def test_validation_rejects_invalid_symbol(value):
    with pytest.raises(ValueError):
        validate_symbol(value)
