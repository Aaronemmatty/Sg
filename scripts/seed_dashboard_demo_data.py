"""
Seeds realistic demo/dummy data for the SG Trading Dashboard:
- Portfolios & Cash Balance
- Open Equity Positions (RELIANCE, TCS, INFY, HDFCBANK, ICICIBANK, SBIN)
- 30-day Order Book & Trade Execution History
- 30-day Daily Portfolio Equity Curve Snapshots
- Registered Trading Strategies
- Redis Market Ticks, Candles, Regime & Risk Metrics
"""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import os
import random
import uuid
import psycopg
import redis.asyncio as aioredis
from dotenv import dotenv_values

REPO_ROOT = r"c:\Users\emmat\Downloads\sg_repo"
ENV_PATH = os.path.join(REPO_ROOT, ".env")
env_vals = dotenv_values(ENV_PATH)

DATABASE_URL = env_vals.get(
    "DATABASE_URL",
    "postgresql://sg_user:sg_password@localhost:5432/sg_db"
).replace("+asyncpg", "")
REDIS_URL = env_vals.get("REDIS_URL", "redis://localhost:6379/0")

SYMBOLS_DATA = [
    {"symbol": "NSE:RELIANCE", "name": "Reliance Industries Ltd", "price": 2965.50, "qty": 45, "cost": 2890.00},
    {"symbol": "NSE:TCS", "name": "Tata Consultancy Services", "price": 3845.20, "qty": 30, "cost": 3720.00},
    {"symbol": "NSE:INFY", "name": "Infosys Ltd", "price": 1785.40, "qty": 70, "cost": 1710.00},
    {"symbol": "NSE:HDFCBANK", "name": "HDFC Bank Ltd", "price": 1640.80, "qty": 60, "cost": 1615.00},
    {"symbol": "NSE:ICICIBANK", "name": "ICICI Bank Ltd", "price": 1180.60, "qty": 85, "cost": 1130.00},
    {"symbol": "NSE:SBIN", "name": "State Bank of India", "price": 842.15, "qty": 110, "cost": 810.00},
    {"symbol": "NSE:BHARTIARTL", "name": "Bharti Airtel Ltd", "price": 1420.00, "qty": 0, "cost": 1390.00},
    {"symbol": "NSE:ITC", "name": "ITC Ltd", "price": 490.50, "qty": 0, "cost": 480.00},
]

STRATEGIES_DATA = [
    {
        "name": "Alpha-Momentum-Trend-v2",
        "description": "Multi-timeframe trend following using EMA crossovers and ATR trailing stops on NSE Largecaps",
        "type": "MOMENTUM",
        "version": "2.1.0",
        "status": "ACTIVE",
    },
    {
        "name": "MeanReversion-Intraday-v1",
        "description": "RSI & Bollinger Band mean reversion strategy for intraday MIS equity trading",
        "type": "MEAN_REVERSION",
        "version": "1.4.0",
        "status": "ACTIVE",
    },
    {
        "name": "Breakout-Volatility-v3",
        "description": "Opening range breakout with volume confirmation and dynamic regime gating",
        "type": "BREAKOUT",
        "version": "3.0.0",
        "status": "ACTIVE",
    },
]

def seed_postgres():
    print("--- Seeding PostgreSQL Database ---")
    with psycopg.connect(DATABASE_URL) as conn:
        with conn.cursor() as cur:
            # 1. Fetch default tenant and admin user
            cur.execute("SELECT id FROM tenants WHERE slug = 'default';")
            row = cur.fetchone()
            if not row:
                tenant_id = uuid.uuid4()
                cur.execute("INSERT INTO tenants (id, name, slug) VALUES (%s, %s, %s);", (tenant_id, "Default Tenant", "default"))
            else:
                tenant_id = row[0]

            cur.execute("SELECT id FROM users WHERE email = 'admin@sg-trading.com';")
            user_row = cur.fetchone()
            user_id = user_row[0] if user_row else None

            # 2. Upsert Portfolio
            cur.execute("SELECT id FROM portfolios WHERE tenant_id = %s LIMIT 1;", (tenant_id,))
            p_row = cur.fetchone()
            if not p_row:
                portfolio_id = uuid.uuid4()
                cur.execute(
                    """
                    INSERT INTO portfolios (
                        id, tenant_id, owner_id, name, description, base_currency,
                        mode, initial_capital, cash_balance, is_default, settings, created_at, updated_at
                    ) VALUES (
                        %s, %s, %s, 'Primary Algorithmic Alpha Fund', 'Main paper trading portfolio for NSE equities', 'INR',
                        'PAPER', 1000000.00, 485600.00, true, '{"max_leverage": 5.0}', NOW(), NOW()
                    );
                    """,
                    (portfolio_id, tenant_id, user_id),
                )
            else:
                portfolio_id = p_row[0]
                cur.execute(
                    """
                    UPDATE portfolios SET
                        cash_balance = 485600.00,
                        updated_at = NOW()
                    WHERE id = %s;
                    """,
                    (portfolio_id,),
                )
            print(f"  [OK] Portfolio: {portfolio_id}")

            # 3. Seed Strategies
            strategy_ids = []
            for s in STRATEGIES_DATA:
                cur.execute("SELECT id FROM strategies WHERE tenant_id = %s AND name = %s;", (tenant_id, s["name"]))
                s_row = cur.fetchone()
                if not s_row:
                    s_id = uuid.uuid4()
                    cur.execute(
                        """
                        INSERT INTO strategies (
                            id, tenant_id, name, description, version, strategy_type, status,
                            config, parameters, supported_timeframes, created_by, created_at, updated_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, '{}', '{"max_allocation_inr": 200000}', '["1m", "5m", "15m", "1d"]', %s, NOW(), NOW()
                        );
                        """,
                        (s_id, tenant_id, s["name"], s["description"], s["version"], s["type"], s["status"], user_id),
                    )
                else:
                    s_id = s_row[0]
                strategy_ids.append(s_id)
            print(f"  [OK] Strategies: {len(strategy_ids)} active strategies")

            # 4. Upsert Open Positions
            cur.execute("DELETE FROM positions WHERE portfolio_id = %s;", (portfolio_id,))
            for item in SYMBOLS_DATA:
                if item["qty"] > 0:
                    pos_id = uuid.uuid4()
                    mkt_val = item["qty"] * item["price"]
                    cost_val = item["qty"] * item["cost"]
                    unrealized = mkt_val - cost_val
                    cur.execute(
                        """
                        INSERT INTO positions (
                            id, tenant_id, portfolio_id, symbol, exchange, quantity,
                            avg_cost, market_price, market_value, unrealized_pnl, realized_pnl,
                            mode, last_trade_at, created_at, updated_at
                        ) VALUES (
                            %s, %s, %s, %s, 'NSE', %s,
                            %s, %s, %s, %s, 0.00,
                            'PAPER', NOW(), NOW(), NOW()
                        );
                        """,
                        (pos_id, tenant_id, portfolio_id, item["symbol"], item["qty"], item["cost"], item["price"], mkt_val, unrealized),
                    )
            print("  [OK] Open Positions seeded")

            # 5. Seed 30-day Order and Trade History
            now = datetime.now(timezone.utc)
            for i in range(25):
                item = random.choice(SYMBOLS_DATA)
                side = random.choice(["BUY", "BUY", "SELL"])
                qty = random.randint(10, 40)
                price = round(item["price"] * (1 + random.uniform(-0.02, 0.02)), 2)
                order_time = now - timedelta(days=random.randint(0, 28), hours=random.randint(1, 6), minutes=random.randint(1, 55))
                order_id = uuid.uuid4()
                broker_order_id = f"paper_{order_id.hex[:8]}"
                strat_id = random.choice(strategy_ids)

                cur.execute(
                    """
                    INSERT INTO orders (
                        id, tenant_id, portfolio_id, strategy_id, symbol, exchange,
                        side, order_type, quantity, filled_quantity, avg_fill_price,
                        status, mode, idempotency_key, correlation_id, broker_order_id,
                        created_at, updated_at, submitted_at, filled_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, 'NSE',
                        %s, 'MARKET', %s, %s, %s,
                        'FILLED', 'PAPER', %s, %s, %s,
                        %s, %s, %s, %s
                    ) ON CONFLICT DO NOTHING;
                    """,
                    (
                        order_id, tenant_id, portfolio_id, strat_id, item["symbol"],
                        side, qty, qty, price,
                        f"idem_{order_id.hex[:12]}", str(uuid.uuid4()), broker_order_id,
                        order_time, order_time, order_time, order_time
                    ),
                )

                trade_id = uuid.uuid4()
                cur.execute(
                    """
                    INSERT INTO trades (
                        id, tenant_id, order_id, order_created_at, portfolio_id, strategy_id,
                        symbol, side, quantity, price, commission, fees, mode,
                        broker_trade_id, correlation_id, executed_at, created_at, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, 15.00, 5.50, 'PAPER',
                        %s, %s, %s, %s, %s
                    ) ON CONFLICT DO NOTHING;
                    """,
                    (
                        trade_id, tenant_id, order_id, order_time, portfolio_id, strat_id,
                        item["symbol"], side, qty, price,
                        f"trd_{trade_id.hex[:8]}", str(uuid.uuid4()), order_time, order_time, order_time
                    ),
                )
            print("  [OK] 25 Executed Orders and Trades inserted")

            # 6. Seed 30-day Daily Portfolio Snapshots (for equity curve)
            cur.execute("DELETE FROM portfolio_snapshots WHERE portfolio_id = %s;", (portfolio_id,))
            base_val = 1000000.00
            for day in range(30, -1, -1):
                snap_time = now - timedelta(days=day)
                # Random daily drift with positive trend
                growth_factor = 1 + (0.0018 * (30 - day)) + random.uniform(-0.004, 0.005)
                tot = round(base_val * growth_factor, 2)
                cash = round(tot * 0.45, 2)
                eq = round(tot - cash, 2)
                pnl = round(tot - base_val, 2)
                cur.execute(
                    """
                    INSERT INTO portfolio_snapshots (
                        id, tenant_id, portfolio_id, snapshot_at, total_value, cash,
                        equity, day_pnl, total_pnl, positions, metrics, created_at, updated_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, '[]', '{"sharpe": 2.48}', %s, %s
                    );
                    """,
                    (
                        uuid.uuid4(), tenant_id, portfolio_id, snap_time, tot, cash,
                        eq, round(random.uniform(-2500, 6500), 2), pnl, snap_time, snap_time
                    ),
                )
            print("  [OK] 30 Daily Equity Curve Snapshots created")

            conn.commit()

async def seed_redis():
    print("\n--- Seeding Redis Live Cache ---")
    r = aioredis.from_url(REDIS_URL, decode_responses=True)

    # 1. Market Ticks & Candle Prices
    for s in SYMBOLS_DATA:
        sym = s["symbol"]
        price = s["price"]
        high = round(price * 1.018, 2)
        low = round(price * 0.985, 2)
        open_p = round(price * 0.992, 2)
        vol = random.randint(250000, 2500000)
        chg = round(((price - open_p) / open_p) * 100, 2)

        tick_payload = {
            "symbol": sym,
            "exchange": "NSE",
            "last_price": price,
            "open": open_p,
            "high": high,
            "low": low,
            "close": price,
            "volume": vol,
            "change_pct": chg,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Cache ticks under standard key formats
        await r.setex(f"tick:{sym}", 86400, json.dumps(tick_payload))
        await r.setex(f"tick:NSE:{sym.replace('NSE:', '')}", 86400, json.dumps(tick_payload))
        await r.setex(f"sg:market:tick:{sym}", 86400, json.dumps(tick_payload))
        print(f"  [TICK] {sym} -> Rs.{price} ({chg:+.2f}%)")

    # 2. Market Regime
    regime_payload = {
        "regime": "BULL_TRENDING",
        "confidence": 0.89,
        "volatility": "NORMAL",
        "trend_strength": "STRONG",
        "vix": 13.45,
        "detected_at": datetime.now(timezone.utc).isoformat(),
    }
    await r.set("sg:regime:current", json.dumps(regime_payload))
    await r.set("regime:current", json.dumps(regime_payload))
    print("  [REGIME] Set to BULL_TRENDING (Confidence 89%)")

    # 3. Risk Engine State & Metrics
    risk_payload = {
        "var_95_daily_inr": 18450.00,
        "portfolio_exposure_pct": 53.92,
        "max_drawdown_pct": 2.15,
        "sharpe_ratio_30d": 2.48,
        "kill_switch_active": False,
        "circuit_breaker_active": False,
        "risk_status": "NORMAL",
        "active_alerts": 0,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await r.set("sg:risk:metrics", json.dumps(risk_payload))
    await r.set("risk:metrics", json.dumps(risk_payload))
    print("  [RISK] Set Risk Metrics (VaR 95: Rs.18,450 | Sharpe: 2.48 | Status: NORMAL)")

    # 4. ML Champion Models
    ml_models = [
        {
            "model_id": "xgb-trend-nse-v3",
            "name": "XGBoost Trend Classifier",
            "framework": "xgboost",
            "accuracy": 0.684,
            "f1_score": 0.672,
            "status": "CHAMPION",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        {
            "model_id": "lstm-volatility-v2",
            "name": "LSTM Volatility Forecaster",
            "framework": "pytorch",
            "accuracy": 0.712,
            "f1_score": 0.705,
            "status": "CHAMPION",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    ]
    await r.set("sg:ml:champions", json.dumps(ml_models))
    print("  [ML] Set Champion Models in Redis")

    await r.aclose()
    print("\n--- Dummy Data Seeding Complete ---")

if __name__ == "__main__":
    seed_postgres()
    asyncio.run(seed_redis())
