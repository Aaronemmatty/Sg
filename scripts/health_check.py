#!/usr/bin/env python3
"""
SG Platform Native Health Checker
Checks availability, response latency, and status across:
- 13 Backend Microservices (ports 8001-8013)
- MLflow Tracking Server (port 5000)
- Next.js Web Dashboard (port 3000)
- Native PostgreSQL (port 5432)
- WSL2 Redis (port 6379)
"""

import sys
import time
import socket
import urllib.request
import urllib.error

SERVICES = [
    ("PostgreSQL", "127.0.0.1", 5432, "tcp"),
    ("Redis (WSL2)", "127.0.0.1", 6379, "tcp"),
    ("MLflow Server", "127.0.0.1", 5000, "http://127.0.0.1:5000/"),
    ("Auth Service", "127.0.0.1", 8001, "http://127.0.0.1:8001/health"),
    ("Market Data Service", "127.0.0.1", 8002, "http://127.0.0.1:8002/health"),
    ("Broker Service", "127.0.0.1", 8003, "http://127.0.0.1:8003/health"),
    ("Strategy Service", "127.0.0.1", 8004, "http://127.0.0.1:8004/health"),
    ("Regime Detection Service", "127.0.0.1", 8005, "http://127.0.0.1:8005/health"),
    ("Execution Orchestrator", "127.0.0.1", 8006, "http://127.0.0.1:8006/health"),
    ("Risk Engine Service", "127.0.0.1", 8007, "http://127.0.0.1:8007/health"),
    ("Execution Engine Service", "127.0.0.1", 8008, "http://127.0.0.1:8008/health"),
    ("Portfolio Management", "127.0.0.1", 8009, "http://127.0.0.1:8009/health"),
    ("Backtesting Engine", "127.0.0.1", 8010, "http://127.0.0.1:8010/api/v1/health"),
    ("ML Platform Service", "127.0.0.1", 8011, "http://127.0.0.1:8011/health"),
    ("AI Analyst Service", "127.0.0.1", 8012, "http://127.0.0.1:8012/api/v1/health"),
    ("Signal Aggregation Service", "127.0.0.1", 8013, "http://127.0.0.1:8013/health"),
    ("Notification Service", "127.0.0.1", 8014, "http://127.0.0.1:8014/health"),
    ("Next.js Dashboard", "127.0.0.1", 3000, "tcp"),
]

def check_tcp(host: str, port: int, timeout: float = 1.5) -> tuple[bool, float, str]:
    start = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            latency = (time.perf_counter() - start) * 1000
            return True, latency, "OPEN"
    except Exception as e:
        latency = (time.perf_counter() - start) * 1000
        return False, latency, str(e)

def check_http(url: str, timeout: float = 10.0) -> tuple[bool, float, str]:
    start = time.perf_counter()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SG-HealthCheck/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            latency = (time.perf_counter() - start) * 1000
            return True, latency, f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        latency = (time.perf_counter() - start) * 1000
        # If the endpoint returned 401 or 404, the server process is still alive and listening
        if e.code in (200, 204, 301, 302, 307, 308, 401, 403, 404):
            return True, latency, f"HTTP {e.code}"
        return False, latency, f"HTTP {e.code}"
    except Exception as e:
        latency = (time.perf_counter() - start) * 1000
        return False, latency, "DOWN"

def main():
    print("=" * 75)
    print(f"{'SG Platform Health Check (Native Windows)':^75}")
    print("=" * 75)
    print(f"{'Target Service':<30} | {'Port':<6} | {'Status':<8} | {'Latency':<9} | {'Details'}")
    print("-" * 75)

    all_passed = True
    for name, host, port, check_type in SERVICES:
        if check_type == "tcp":
            ok, lat, details = check_tcp(host, port)
        else:
            ok, lat, details = check_http(check_type)

        status_str = "[ PASS ]" if ok else "[ FAIL ]"
        if not ok:
            all_passed = False

        print(f"{name:<30} | {port:<6} | {status_str:<8} | {lat:>6.1f}ms | {details}", flush=True)

    print("=" * 75, flush=True)
    if all_passed:
        print("ALL SERVICES OPERATIONAL")
        sys.exit(0)
    else:
        print("SOME SERVICES ARE OFFLINE OR UNREACHABLE")
        sys.exit(1)

if __name__ == "__main__":
    main()
