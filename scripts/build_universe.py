"""
NIFTY 200 Universe Builder & Filter Generator.

1. Downloads the official NIFTY 200 constituents CSV from NSE Indices (niftyindices.com / archives.nseindia.com).
2. Cross-references against Kite's instrument master (api.kite.trade/instruments).
3. Fetches recent price and volume data.
4. Applies Universe Filters:
   - Base pool: NIFTY 200 constituents (200 stocks).
   - Price filter: Close price < ₹500/share.
   - Liquidity filter: Average Daily Traded Value (ADTV) >= ₹25 Crore (₹250,000,000 / day)
     and Average Daily Volume >= 500,000 shares/day.
5. Saves the constituent metadata to json/csv and outputs python code for sg_security.universe.
"""
from __future__ import annotations

import csv
import io
import json
import os
import sys
import time
import urllib.request
import yfinance as yf

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNIVERSE_DATA_PATH = os.path.join(REPO_ROOT, "sg_security", "sg_security", "nifty200_universe.json")

NIFTY200_CSV_URLS = [
    "https://niftyindices.com/IndexConstituent/ind_nifty200list.csv",
    "https://archives.nseindia.com/content/indices/ind_nifty200list.csv",
]
KITE_INSTRUMENTS_URL = "https://api.kite.trade/instruments"

# Liquidity Thresholds:
MAX_PRICE_INR = 500.0
MIN_ADTV_INR = 250_000_000.0  # ₹25 Crore min average daily turnover
MIN_DAILY_VOLUME = 500_000     # 500k shares min average daily volume


def fetch_nifty200_constituents() -> dict[str, dict]:
    """Download official NIFTY 200 CSV."""
    headers = {"User-Agent": "Mozilla/5.0"}
    for url in NIFTY200_CSV_URLS:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=10) as resp:
                content = resp.read().decode("utf-8")
                reader = csv.DictReader(io.StringIO(content))
                symbols = {}
                for row in reader:
                    sym = row.get("Symbol", "").strip()
                    if sym:
                        symbols[sym] = {
                            "symbol": sym,
                            "company_name": row.get("Company Name", "").strip(),
                            "industry": row.get("Industry", "").strip(),
                            "isin": row.get("ISIN Code", "").strip(),
                            "series": row.get("Series", "EQ").strip(),
                        }
                if len(symbols) == 200:
                    print(f"Successfully downloaded {len(symbols)} NIFTY 200 constituents from {url}")
                    return symbols
        except Exception as e:
            print(f"Failed to download NIFTY 200 from {url}: {e}")
    raise RuntimeError("Could not download NIFTY 200 constituents from official sources")


def fetch_kite_tokens(symbols: set[str]) -> dict[str, int]:
    """Fetch instrument tokens from Kite instrument dump."""
    headers = {"User-Agent": "Mozilla/5.0"}
    req = urllib.request.Request(KITE_INSTRUMENTS_URL, headers=headers)
    token_map = {}
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8")
            reader = csv.DictReader(io.StringIO(content))
            for row in reader:
                if row.get("exchange") == "NSE" and row.get("segment") == "NSE":
                    sym = row.get("tradingsymbol", "").strip()
                    if sym in symbols:
                        token_map[sym] = int(row["instrument_token"])
        print(f"Matched {len(token_map)} / {len(symbols)} symbols with Kite instrument tokens")
    except Exception as e:
        print(f"Failed to fetch Kite tokens: {e}")
    return token_map


def fetch_market_metrics(symbols: list[str]) -> dict[str, dict]:
    """Fetch 1-month daily historical data to compute close price, volume, and ADTV."""
    print(f"Fetching market metrics for {len(symbols)} symbols via Yahoo Finance...")
    metrics = {}
    
    # Batch in groups of 50
    for i in range(0, len(symbols), 50):
        batch = symbols[i : i + 50]
        tickers = [f"{s}.NS" for s in batch]
        try:
            df = yf.download(tickers, period="1mo", interval="1d", progress=False, group_by="ticker")
            for s in batch:
                ticker = f"{s}.NS"
                try:
                    if (ticker, "Close") in df.columns:
                        closes = df[(ticker, "Close")].dropna()
                        volumes = df[(ticker, "Volume")].dropna() if (ticker, "Volume") in df.columns else None
                    elif ticker in df:
                        closes = df[ticker]["Close"].dropna()
                        volumes = df[ticker]["Volume"].dropna() if "Volume" in df[ticker] else None
                    else:
                        closes, volumes = None, None
                    
                    if closes is not None and not closes.empty:
                        last_close = float(closes.iloc[-1])
                        avg_vol = float(volumes.mean()) if volumes is not None and not volumes.empty else 0.0
                        adtv = last_close * avg_vol
                        metrics[s] = {
                            "last_price": round(last_close, 2),
                            "avg_daily_volume": int(avg_vol),
                            "adtv_inr": round(adtv, 2),
                            "adtv_crores": round(adtv / 1e7, 2),
                        }
                    else:
                        metrics[s] = {"last_price": 0.0, "avg_daily_volume": 0, "adtv_inr": 0.0, "adtv_crores": 0.0}
                except Exception:
                    metrics[s] = {"last_price": 0.0, "avg_daily_volume": 0, "adtv_inr": 0.0, "adtv_crores": 0.0}
        except Exception as e:
            print(f"Batch {i} download error: {e}")
            
    return metrics


def build_and_save_universe():
    nifty200 = fetch_nifty200_constituents()
    symbols = sorted(list(nifty200.keys()))
    tokens = fetch_kite_tokens(set(symbols))
    metrics = fetch_market_metrics(symbols)
    
    universe = {}
    filtered_tradeable = []
    filtered_out_price = []
    filtered_out_liquidity = []
    
    for s in symbols:
        info = nifty200[s]
        token = tokens.get(s, 0)
        m = metrics.get(s, {"last_price": 0.0, "avg_daily_volume": 0, "adtv_inr": 0.0, "adtv_crores": 0.0})
        price = m["last_price"]
        vol = m["avg_daily_volume"]
        adtv = m["adtv_inr"]
        
        is_price_ok = (0 < price <= MAX_PRICE_INR)
        is_liq_ok = (adtv >= MIN_ADTV_INR and vol >= MIN_DAILY_VOLUME)
        is_tradeable = is_price_ok and is_liq_ok
        
        entry = {
            "symbol": s,
            "nse_symbol": f"NSE:{s}",
            "company_name": info["company_name"],
            "industry": info["industry"],
            "isin": info["isin"],
            "instrument_token": token,
            "last_price": price,
            "avg_daily_volume": vol,
            "adtv_inr": adtv,
            "adtv_crores": m["adtv_crores"],
            "is_tradeable": is_tradeable,
            "filters": {
                "price_under_500": is_price_ok,
                "high_liquidity": is_liq_ok,
            }
        }
        universe[s] = entry
        
        if is_tradeable:
            filtered_tradeable.append(entry)
        elif not is_price_ok:
            filtered_out_price.append(entry)
        else:
            filtered_out_liquidity.append(entry)

    # Save to JSON
    os.makedirs(os.path.dirname(UNIVERSE_DATA_PATH), exist_ok=True)
    with open(UNIVERSE_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(universe, f, indent=2)
    print(f"\nSaved {len(universe)} universe definitions to {UNIVERSE_DATA_PATH}")
    
    print("=" * 80)
    print("UNIVERSE FILTER SUMMARY:")
    print("=" * 80)
    print(f"Total NIFTY 200 Base Pool      : {len(universe)} symbols")
    print(f"Tradeable Filtered Subset (<₹500 & high liq): {len(filtered_tradeable)} symbols")
    print(f"Filtered out by Price (>= ₹500) : {len(filtered_out_price)} symbols")
    print(f"Filtered out by Liquidity      : {len(filtered_out_liquidity)} symbols")
    print("-" * 80)
    print("Tradeable Symbols:")
    tradeable_syms = [x["symbol"] for x in filtered_tradeable]
    print(", ".join(tradeable_syms))
    
    return universe, filtered_tradeable, filtered_out_price, filtered_out_liquidity

if __name__ == "__main__":
    build_and_save_universe()
