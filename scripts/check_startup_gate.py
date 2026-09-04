"""
Startup Pre-Flight Safety Gate — SG Trading Platform.

Reads mode flags from:
  1. broker_service/.env      (BROKER_MODE, ENABLE_REAL_MONEY_TRADING)
  2. strategy_service/.env    (TRADING_MODE)
  3. market_data_service/.env (KITE_MODE)

Enforces:
  - Paper mode: zero friction, boots immediately with exit code 0.
  - Live mode: high-visibility warning + mismatch analysis + exact case-sensitive "CONFIRM" prompt.
  - Any non-"CONFIRM" input: aborts startup with exit code 1 and no services launched.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def parse_env_file(file_path: Path) -> dict[str, str]:
    """Parse a simple .env file into key-value pairs."""
    env_vars: dict[str, str] = {}
    if not file_path.is_file():
        return env_vars

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip()
                    # Remove surrounding quotes if present
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                    env_vars[key] = val
    except Exception as e:
        print(f"[PRE-FLIGHT WARNING] Could not read {file_path}: {e}", file=sys.stderr)

    return env_vars


def run_preflight_gate(repo_root: Path | None = None) -> int:
    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent

    broker_env = parse_env_file(repo_root / "broker_service" / ".env")
    strategy_env = parse_env_file(repo_root / "strategy_service" / ".env")
    market_env = parse_env_file(repo_root / "market_data_service" / ".env")

    broker_mode = broker_env.get("BROKER_MODE", "paper").strip().lower()
    enable_real_money = broker_env.get("ENABLE_REAL_MONEY_TRADING", "").strip()
    trading_mode = strategy_env.get("TRADING_MODE", "paper").strip().lower()
    kite_mode = market_env.get("KITE_MODE", "mock").strip().lower()

    # Case 1: Pure paper / simulated mode
    if broker_mode != "live":
        mismatches: list[str] = []
        if trading_mode == "live":
            mismatches.append("strategy_service TRADING_MODE is 'live' while broker is 'paper'")

        if mismatches:
            print("=" * 70)
            print("[PRE-FLIGHT WARNING] Configuration Inconsistency Detected:")
            for m in mismatches:
                print(f"  • {m}")
            print("=" * 70)

        print(f"[PRE-FLIGHT] Mode: PAPER (Simulated) | No live capital at risk. Booting platform...")
        return 0

    # Case 2: LIVE REAL-MONEY MODE REQUESTED
    print()
    print("!" * 78)
    print("!" + " " * 76 + "!")
    print("!" + "   WARNING: LIVE REAL-MONEY TRADING MODE ACTIVATED IN CONFIGURATION   ".center(76) + "!")
    print("!" + " " * 76 + "!")
    print("!" * 78)
    print()
    print("Current Service Configurations:")
    print(f"  1. broker_service/.env:      BROKER_MODE               = {broker_mode.upper()}")
    print(f"  2. broker_service/.env:      ENABLE_REAL_MONEY_TRADING = {enable_real_money or '(EMPTY - UNSET)'}")
    print(f"  3. strategy_service/.env:    TRADING_MODE              = {trading_mode.upper()}")
    print(f"  4. market_data_service/.env: KITE_MODE                 = {kite_mode.upper()}")
    print()

    mismatches = []
    if enable_real_money != "CONFIRMED_REAL_CAPITAL_RISK":
        mismatches.append(
            "CRITICAL: ENABLE_REAL_MONEY_TRADING is NOT set to 'CONFIRMED_REAL_CAPITAL_RISK'. "
            "broker_service will FAIL CLOSED on startup."
        )
    if trading_mode != "live":
        mismatches.append(
            f"MISMATCH: strategy_service TRADING_MODE is '{trading_mode}' (expected 'live')."
        )
    if kite_mode != "live":
        mismatches.append(
            f"MISMATCH: market_data_service KITE_MODE is '{kite_mode}' (mock feed with live broker)."
        )

    if mismatches:
        print("Safety Issues & Mismatches Detected:")
        for item in mismatches:
            print(f"  [!] {item}")
        print()

    print("-" * 78)
    print("Orders placed in this mode WILL EXECUTE AGAINST REAL MARKET FUNDS (Zerodha Kite).")
    print("To proceed with startup, type exactly 'CONFIRM' (case-sensitive).")
    print("Any other input (or empty/Ctrl+C) will ABORT immediately with zero services started.")
    print("-" * 78)

    try:
        user_response = input("Enter confirmation ['CONFIRM']: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\n\n[ABORTED] Startup cancelled by user interrupt. No services launched.\n")
        return 1

    if user_response == "CONFIRM":
        print("\n[AUTHORIZED] Operator confirmation verified. Proceeding with LIVE startup...\n")
        return 0
    else:
        print(f"\n[ABORTED] Input '{user_response}' does not match 'CONFIRM'. Startup aborted. No services launched.\n")
        return 1


if __name__ == "__main__":
    sys.exit(run_preflight_gate())
