"""
Universe filter module for NIFTY 200 constituents.

Provides:
- Base pool of all 200 NIFTY 200 constituents (sourced from NSE Indices official CSV).
- Instrument token mappings (cross-referenced against Zerodha Kite instruments master).
- Price and liquidity filters (price < ₹500/share, high liquidity based on average daily traded value).
- Dynamic universe filtering using live quote or historical bar data.
- Periodic / programmatic universe refresh mechanism.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import os
import urllib.request
from functools import lru_cache
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DATA_FILE = Path(__file__).parent / "nifty200_universe.json"

# Default retail calibration filter thresholds
DEFAULT_MAX_PRICE_INR: float = 500.0
# High Liquidity: Minimum Average Daily Traded Value (ADTV) = ₹25 Crore (~$3M USD/day)
# and Minimum Average Daily Volume = 500,000 shares/day.
# Rationale: Guarantees tight bid-ask spreads (<0.05%), minimal slippage, and immediate execution
# for retail order sizes (e.g. ₹1,800 to ₹10,000).
DEFAULT_MIN_ADTV_INR: float = 250_000_000.0
DEFAULT_MIN_AVG_VOLUME: int = 500_000

NIFTY200_CSV_URLS = [
    "https://niftyindices.com/IndexConstituent/ind_nifty200list.csv",
    "https://archives.nseindia.com/content/indices/ind_nifty200list.csv",
]
KITE_INSTRUMENTS_URL = "https://api.kite.trade/instruments"


@lru_cache(maxsize=1)
def load_universe_data() -> dict[str, dict[str, Any]]:
    """
    Load the cached NIFTY 200 universe metadata JSON.
    Returns mapping of symbol -> metadata dict.
    """
    if DATA_FILE.exists():
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.warning("failed_to_load_cached_universe_data", error=str(e))

    # Fallback minimal universe if file is missing
    return {}


def get_nifty200_symbols(prefix: bool = True) -> list[str]:
    """
    Return all 200 NIFTY 200 constituents.
    :param prefix: If True, prepends 'NSE:' (e.g. 'NSE:RELIANCE'). If False, returns 'RELIANCE'.
    """
    data = load_universe_data()
    if not data:
        return []
    if prefix:
        return [f"NSE:{s}" for s in sorted(data.keys())]
    return sorted(data.keys())


def get_nifty200_token_map(prefix: bool = True) -> dict[str, int]:
    """
    Return dictionary mapping symbol to Kite instrument token for all 200 constituents.
    """
    data = load_universe_data()
    res = {}
    for s, info in data.items():
        key = f"NSE:{s}" if prefix else s
        res[key] = int(info.get("instrument_token", 0))
    return res


def get_nifty200_base_prices(prefix: bool = True) -> dict[str, float]:
    """
    Return dictionary mapping symbol to recent reference price for all 200 constituents.
    """
    data = load_universe_data()
    res = {}
    for s, info in data.items():
        key = f"NSE:{s}" if prefix else s
        res[key] = float(info.get("last_price", 1000.0))
    return res


def get_tradeable_universe(
    prefix: bool = False,
    max_price: float = DEFAULT_MAX_PRICE_INR,
    min_adtv_inr: float = DEFAULT_MIN_ADTV_INR,
    min_volume: int = DEFAULT_MIN_AVG_VOLUME,
) -> list[str]:
    """
    Return the tradeable universe filtered by:
      1. NIFTY 200 constituent membership.
      2. Share price <= max_price (default ₹500).
      3. High liquidity (ADTV >= min_adtv_inr and avg volume >= min_volume).

    :param prefix: If True, prepends 'NSE:'. If False, returns bare symbols.
    """
    data = load_universe_data()
    tradeable = []
    for s, info in data.items():
        price = float(info.get("last_price", 0.0))
        adtv = float(info.get("adtv_inr", 0.0))
        vol = int(info.get("avg_daily_volume", 0))

        # Check price and liquidity criteria
        if 0.0 < price <= max_price:
            if adtv >= min_adtv_inr and vol >= min_volume:
                sym = f"NSE:{s}" if prefix else s
                tradeable.append(sym)

    return sorted(tradeable)


def filter_universe(
    symbols: list[str] | None = None,
    price_map: dict[str, float] | None = None,
    volume_map: dict[str, float] | None = None,
    max_price: float = DEFAULT_MAX_PRICE_INR,
    min_adtv_inr: float = DEFAULT_MIN_ADTV_INR,
    min_volume: int = DEFAULT_MIN_AVG_VOLUME,
    prefix: bool = False,
) -> list[str]:
    """
    Filter any candidate list of symbols dynamically using live or provided price and volume data.
    If price_map or volume_map are omitted, falls back to the universe reference metadata.
    """
    universe = load_universe_data()
    target_symbols = symbols if symbols is not None else list(universe.keys())

    filtered = []
    for raw_sym in target_symbols:
        clean_sym = raw_sym.replace("NSE:", "").strip()
        info = universe.get(clean_sym, {})

        price = price_map.get(raw_sym, price_map.get(clean_sym, float(info.get("last_price", 0.0)))) if price_map else float(info.get("last_price", 0.0))
        vol = volume_map.get(raw_sym, volume_map.get(clean_sym, float(info.get("avg_daily_volume", 0.0)))) if volume_map else float(info.get("avg_daily_volume", 0.0))
        adtv = price * vol if (price_map and volume_map) else float(info.get("adtv_inr", price * vol))

        if 0.0 < price <= max_price and (adtv >= min_adtv_inr and vol >= min_volume):
            sym = f"NSE:{clean_sym}" if prefix else clean_sym
            filtered.append(sym)

    return sorted(filtered)


def refresh_universe(
    save_path: str | Path | None = None,
    fetch_market_data: bool = False,
) -> dict[str, dict[str, Any]]:
    """
    Refresh the NIFTY 200 universe from official NSE and Kite endpoints.
    Can be run as a scheduled maintenance task or CLI tool.
    """
    headers = {"User-Agent": "Mozilla/5.0"}
    nifty200_symbols: dict[str, dict[str, str]] = {}

    for url in NIFTY200_CSV_URLS:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                content = resp.read().decode("utf-8")
                reader = csv.DictReader(io.StringIO(content))
                for row in reader:
                    sym = row.get("Symbol", "").strip()
                    if sym:
                        nifty200_symbols[sym] = {
                            "symbol": sym,
                            "company_name": row.get("Company Name", "").strip(),
                            "industry": row.get("Industry", "").strip(),
                            "isin": row.get("ISIN Code", "").strip(),
                            "series": row.get("Series", "EQ").strip(),
                        }
                if len(nifty200_symbols) >= 200:
                    break
        except Exception as e:
            log.warning("failed_to_fetch_nifty200_csv", url=url, error=str(e))

    if not nifty200_symbols:
        raise RuntimeError("Failed to fetch NIFTY 200 constituents from NSE sources")

    # Fetch Kite instrument tokens
    tokens: dict[str, int] = {}
    try:
        req = urllib.request.Request(KITE_INSTRUMENTS_URL, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8")
            reader = csv.DictReader(io.StringIO(content))
            for row in reader:
                if row.get("exchange") == "NSE" and row.get("segment") == "NSE":
                    sym = row.get("tradingsymbol", "").strip()
                    if sym in nifty200_symbols:
                        tokens[sym] = int(row["instrument_token"])
    except Exception as e:
        log.warning("failed_to_fetch_kite_tokens", error=str(e))

    existing = load_universe_data()
    updated_universe: dict[str, dict[str, Any]] = {}

    for s, info in nifty200_symbols.items():
        prev = existing.get(s, {})
        last_price = prev.get("last_price", 0.0)
        avg_vol = prev.get("avg_daily_volume", 0)
        adtv = prev.get("adtv_inr", 0.0)

        entry = {
            "symbol": s,
            "nse_symbol": f"NSE:{s}",
            "company_name": info["company_name"],
            "industry": info["industry"],
            "isin": info["isin"],
            "instrument_token": tokens.get(s, prev.get("instrument_token", 0)),
            "last_price": last_price,
            "avg_daily_volume": avg_vol,
            "adtv_inr": adtv,
            "adtv_crores": round(adtv / 1e7, 2),
            "is_tradeable": (0.0 < last_price <= DEFAULT_MAX_PRICE_INR and adtv >= DEFAULT_MIN_ADTV_INR and avg_vol >= DEFAULT_MIN_AVG_VOLUME),
        }
        updated_universe[s] = entry

    target_path = Path(save_path) if save_path else DATA_FILE
    with open(target_path, "w", encoding="utf-8") as f:
        json.dump(updated_universe, f, indent=2)

    load_universe_data.cache_clear()
    return updated_universe
