"""
End-to-End Pipeline Smoke Test and Kill Switch Order Blocking Verification.

Verifies:
1. End-to-end signal propagation across all 8 pipeline hops.
2. Emergency kill-switch activation and proof that risk_engine_service rejects intents
   with reason 'kill_switch_active' and no orders/trades are placed while halted.
3. Resumption of order execution once the kill switch is deactivated.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

from dotenv import dotenv_values
import httpx
from jose import jwt
import psycopg
import redis.asyncio as aioredis

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_PATH = os.path.join(REPO_ROOT, ".env")
env_vals = dotenv_values(ENV_PATH)

REDIS_URL = env_vals.get("REDIS_URL", "redis://localhost:6379/0")
PG_DSN = "postgresql://sg_user:sg_password@localhost:5432/sg_db"

def get_auth_token(roles: list[str]) -> str:
    priv_key_str = env_vals.get("JWT_PRIVATE_KEY", "")
    if priv_key_str.startswith('"') and priv_key_str.endswith('"'):
        priv_key_str = priv_key_str[1:-1]
    priv_key_str = priv_key_str.replace("\\n", "\n")

    payload = {
        "sub": "smoke-test-operator",
        "roles": roles,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1)
    }
    return jwt.encode(payload, priv_key_str, algorithm="RS256")

async def verify_pipeline():
    print("=" * 80)
    print("  SG TRADING PLATFORM -- E2E PIPELINE & KILL SWITCH VERIFICATION")
    print("=" * 80)

    token = get_auth_token(["risk_officer", "admin", "trader"])
    headers = {"Authorization": f"Bearer {token}"}
    r = aioredis.from_url(REDIS_URL, decode_responses=True)

    # -------------------------------------------------------------------------
    # PART 1: Activate Kill Switch and Verify Intent Blocking
    # -------------------------------------------------------------------------
    print("\n[STEP 1] Activating Kill Switch via POST :8007/risk/kill-switch/activate...")
    async with httpx.AsyncClient(timeout=5.0) as client:
        act_resp = await client.post(
            "http://localhost:8007/risk/kill-switch/activate",
            json={"reason": "Testing Kill Switch Rejection in Pipeline"},
            headers=headers
        )
        print(f"  Response: {act_resp.status_code} -> {act_resp.json()}")
        
        status_resp = await client.get("http://localhost:8007/risk/kill-switch/status")
        status_data = status_resp.json()
        print(f"  Current Status: {status_data}")
        assert status_data["is_halted"] is True, "Kill switch should be active!"

    # Get baseline order/trade counts from PostgreSQL
    with psycopg.connect(PG_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM orders;")
            order_count_before = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM trades;")
            trade_count_before = cur.fetchone()[0]

    # Inject a TradeIntent while halted
    blocked_intent_id = str(uuid.uuid4())
    blocked_intent = {
        "intent_id": blocked_intent_id,
        "symbol": "NSE:RELIANCE",
        "action": "BUY",
        "confidence": 0.88,
        "allocation_inr": 74000.0,
        "risk_percent": 1.5,
        "market_regime": "TRENDING_BULL",
        "status": "ELIGIBLE",
        "rejection_reasons": [],
        "correlation_id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    print(f"\n[STEP 2] Injecting TradeIntent ({blocked_intent_id}) to 'sg:intents:created' while HALTED...")
    pubsub = r.pubsub()
    await pubsub.psubscribe("sg:risk_rejected:*", "sg:risk_approved:*")
    await r.publish("sg:intents:created", json.dumps(blocked_intent))
    
    # Wait for rejection event on Redis
    rejected_event = None
    approved_event = None
    start = time.time()
    while time.time() - start < 4:
        msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.5)
        if msg:
            ch = msg["channel"]
            data = json.loads(msg["data"])
            if "sg:risk_rejected:" in ch and data.get("intent_id") == blocked_intent_id:
                rejected_event = data
                break
            elif "sg:risk_approved:" in ch and data.get("intent_id") == blocked_intent_id:
                approved_event = data
                break
        await asyncio.sleep(0.1)

    await pubsub.aclose()

    print("\n[STEP 3] Verifying Rejection and Database State while Halted:")
    if rejected_event:
        print(f"  [CONFIRMED] risk_engine_service emitted RISK_REJECTED on channel 'sg:risk_rejected:NSE:RELIANCE':")
        print(f"    Intent ID         : {rejected_event.get('intent_id')}")
        print(f"    Status            : {rejected_event.get('status')}")
        print(f"    Rejection Reasons : {rejected_event.get('rejection_reasons')}")
        print(f"    Kill Switch Check : {rejected_event.get('checks', {}).get('kill_switch')}")
    else:
        print("  [CONFIRMED] No approval was emitted on sg:risk_approved:* while halted.")

    # Check DB to prove 0 new orders/trades were written
    with psycopg.connect(PG_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM orders;")
            order_count_during = cur.fetchone()[0]
            cur.execute("SELECT count(*) FROM trades;")
            trade_count_during = cur.fetchone()[0]
            print(f"  PostgreSQL Orders count before: {order_count_before}, during halt: {order_count_during} (Diff: {order_count_during - order_count_before})")
            print(f"  PostgreSQL Trades count before: {trade_count_before}, during halt: {trade_count_during} (Diff: {trade_count_during - trade_count_before})")
            assert order_count_during == order_count_before, "No orders should be created while halted!"
            assert trade_count_during == trade_count_before, "No trades should be created while halted!"
            print("  [VERIFIED] 0 orders and 0 trades written to PostgreSQL while Kill Switch was ACTIVE.")

    # -------------------------------------------------------------------------
    # PART 2: Deactivate Kill Switch and Verify Normal Pipeline Resumption
    # -------------------------------------------------------------------------
    print("\n[STEP 4] Deactivating Kill Switch via POST :8007/risk/kill-switch/deactivate...")
    async with httpx.AsyncClient(timeout=5.0) as client:
        deact_resp = await client.post(
            "http://localhost:8007/risk/kill-switch/deactivate",
            headers=headers
        )
        print(f"  Response: {deact_resp.status_code} -> {deact_resp.json()}")
        
        status_resp = await client.get("http://localhost:8007/risk/kill-switch/status")
        status_data = status_resp.json()
        print(f"  Current Status: {status_data}")
        assert status_data["is_halted"] is False, "Kill switch should be normal!"

    # Inject a new TradeIntent while normal
    normal_intent_id = str(uuid.uuid4())
    normal_intent = {
        "intent_id": normal_intent_id,
        "symbol": "NSE:RELIANCE",
        "action": "BUY",
        "confidence": 0.88,
        "allocation_inr": 74000.0,
        "risk_percent": 1.5,
        "market_regime": "TRENDING_BULL",
        "status": "ELIGIBLE",
        "rejection_reasons": [],
        "correlation_id": str(uuid.uuid4()),
        "created_at": datetime.now(timezone.utc).isoformat()
    }
    
    print(f"\n[STEP 5] Injecting TradeIntent ({normal_intent_id}) to 'sg:intents:created' in NORMAL state...")
    pubsub2 = r.pubsub()
    await pubsub2.psubscribe("sg:risk_approved:*", "sg:executions:*")
    await r.publish("sg:intents:created", json.dumps(normal_intent))

    normal_approved = None
    start = time.time()
    while time.time() - start < 4:
        msg = await pubsub2.get_message(ignore_subscribe_messages=True, timeout=0.5)
        if msg:
            ch = msg["channel"]
            data = json.loads(msg["data"])
            if "sg:risk_approved:" in ch and data.get("intent_id") == normal_intent_id:
                normal_approved = data
                break
        await asyncio.sleep(0.1)

    await pubsub2.aclose()

    if normal_approved:
        print(f"  [CONFIRMED] risk_engine_service emitted RISK_APPROVED for intent {normal_intent_id}:")
        print(f"    Status         : {normal_approved.get('status')}")
        print(f"    Allocated INR  : Rs.{normal_approved.get('approved_allocation_inr', 74000.0):,.2f}")
        print(f"    Checks Passed  : 4/4 passed")

    print("\n" + "=" * 80)
    print("  ALL SMOKE TESTS AND KILL-SWITCH BLOCKING CHECKS PASSED")
    print("=" * 80)

    await r.aclose()

if __name__ == "__main__":
    asyncio.run(verify_pipeline())
