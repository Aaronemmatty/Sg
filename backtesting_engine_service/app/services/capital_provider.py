from __future__ import annotations

import httpx

from app.core.config import settings
from app.core.logging import log
from app.models.domain import BacktestConfig


async def resolve_initial_capital(
    config: BacktestConfig,
    auth_header: str | None = None,
) -> tuple[float, str]:
    """
    Resolve starting capital for a backtest run:
    1. User-supplied override (explicit initial_capital_inr) always takes precedence.
    2. If omitted / None, dynamically fetch live account balance from broker_service (/v1/broker/account).
    3. If live fetch fails for any reason (broker down, timeout, bad status, etc.),
       fall back to static default (DEFAULT_INITIAL_CAPITAL_INR = 9,000).

    Logs clearly which path was used (live-fetched vs static-fallback vs user-override).
    Sets config.initial_capital_inr and config.capital_source in-place.
    """
    # 1. User-supplied explicit override
    if config.initial_capital_inr is not None and config.initial_capital_inr > 0:
        source = "user-override"
        config.capital_source = source
        log.info(
            "backtest_capital_resolved",
            run_name=config.name,
            initial_capital_inr=config.initial_capital_inr,
            source=source,
        )
        return config.initial_capital_inr, source

    # 2. Dynamic live balance fetch
    broker_url = settings.broker_service_url.rstrip("/")
    target_url = f"{broker_url}/v1/broker/account"
    headers = {"User-Agent": "SG-BacktestingEngine/1.0"}
    if auth_header:
        headers["Authorization"] = auth_header

    try:
        timeout = min(getattr(settings, "http_client_timeout_seconds", 15.0), 3.0)
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=1.0)) as client:
            resp = await client.get(target_url, headers=headers)
            resp.raise_for_status()
            data = resp.json()

            # available_cash is the primary trading balance; net_value as fallback
            live_cash = data.get("available_cash")
            if live_cash is None or float(live_cash) <= 0:
                live_cash = data.get("net_value")

            if live_cash is not None and float(live_cash) > 0:
                capital = float(live_cash)
                source = "live-fetched"
                config.initial_capital_inr = capital
                config.capital_source = source
                log.info(
                    "backtest_capital_resolved",
                    run_name=config.name,
                    initial_capital_inr=capital,
                    source=source,
                    broker=data.get("broker"),
                    account_id=data.get("account_id"),
                )
                return capital, source
            else:
                log.warning(
                    "live_balance_returned_invalid_cash_using_fallback",
                    data=data,
                    fallback=settings.default_initial_capital_inr,
                )
    except Exception as exc:
        log.warning(
            "live_balance_fetch_failed_using_fallback",
            url=target_url,
            error=str(exc),
            fallback_capital_inr=settings.default_initial_capital_inr,
        )

    # 3. Static fallback
    source = "static-fallback"
    config.initial_capital_inr = settings.default_initial_capital_inr
    config.capital_source = source
    log.info(
        "backtest_capital_resolved",
        run_name=config.name,
        initial_capital_inr=config.initial_capital_inr,
        source=source,
    )
    return config.initial_capital_inr, source
