#!/usr/bin/env python3
"""
SG Platform - Tiered Readiness Poller
Waits for infrastructure and microservice tiers to become healthy before proceeding.
"""

import sys
import time
import socket
import argparse
import subprocess
import urllib.request
import urllib.error

ENDPOINT_MAP = {
    5432: ("PostgreSQL", "tcp", None),
    6379: ("Redis (WSL2)", "tcp", None),
    5000: ("MLflow Server", "http", "http://127.0.0.1:5000/"),
    8001: ("Auth Service", "http", "http://127.0.0.1:8001/health"),
    8002: ("Market Data Service", "http", "http://127.0.0.1:8002/health"),
    8003: ("Broker Service", "http", "http://127.0.0.1:8003/health"),
    8004: ("Strategy Service", "http", "http://127.0.0.1:8004/health"),
    8005: ("Regime Detection", "http", "http://127.0.0.1:8005/health"),
    8006: ("Execution Orchestrator", "http", "http://127.0.0.1:8006/health"),
    8007: ("Risk Engine", "http", "http://127.0.0.1:8007/health"),
    8008: ("Execution Engine", "http", "http://127.0.0.1:8008/health"),
    8009: ("Portfolio Management", "http", "http://127.0.0.1:8009/health"),
    8010: ("Backtesting Engine", "http", "http://127.0.0.1:8010/health"),
    8011: ("ML Platform", "http", "http://127.0.0.1:8011/health"),
    8012: ("AI Analyst", "http", "http://127.0.0.1:8012/health"),
    8013: ("Signal Aggregation", "http", "http://127.0.0.1:8013/health"),
    8014: ("Notification Service", "http", "http://127.0.0.1:8014/health"),
    3000: ("Next.js Dashboard", "tcp", None),
}


def check_tcp(port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except Exception:
        return False


def check_http(url: str, timeout: float = 1.0) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "SG-ReadinessPoller/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True
    except urllib.error.HTTPError as e:
        # Standard active HTTP status codes indicating web server is alive and responding
        return e.code in (200, 204, 301, 302, 307, 308, 401, 403, 404)
    except Exception:
        return False


def check_single(port: int) -> bool:
    info = ENDPOINT_MAP.get(port)
    if not info:
        return check_tcp(port)
    name, check_type, url = info
    if check_type == "tcp":
        return check_tcp(port)
    return check_http(url)


def ensure_infrastructure(timeout: float = 10.0) -> bool:
    """Verify and if necessary trigger start of PostgreSQL and Redis."""
    print("  [*] Checking Core Infrastructure (PostgreSQL :5432, Redis :6379)...", flush=True)
    t0 = time.time()
    
    # Try starting Redis via WSL if not listening
    if not check_tcp(6379, timeout=0.3):
        print("  [*] Redis is not running. Attempting to start WSL2 Redis...", flush=True)
        try:
            subprocess.run(["wsl", "service", "redis-server", "start"], capture_output=True, timeout=5)
        except Exception as e:
            print(f"  [-] Failed to auto-start WSL2 Redis: {e}", flush=True)
            
    # Poll for both
    pg_ok = False
    redis_ok = False
    while time.time() - t0 < timeout:
        if not pg_ok and check_tcp(5432, timeout=0.3):
            pg_ok = True
            print("  [+] PostgreSQL is READY on port 5432", flush=True)
        if not redis_ok and check_tcp(6379, timeout=0.3):
            redis_ok = True
            print("  [+] Redis (WSL2) is READY on port 6379", flush=True)
        if pg_ok and redis_ok:
            return True
        time.sleep(0.3)
        
    if not pg_ok:
        print("  [-] [ERROR] PostgreSQL failed to respond on port 5432 within timeout!", flush=True)
    if not redis_ok:
        print("  [-] [ERROR] Redis failed to respond on port 6379 within timeout!", flush=True)
    return pg_ok and redis_ok


def wait_for_ports(ports: list[int], timeout: float = 30.0) -> bool:
    t0 = time.time()
    pending = set(ports)
    print(f"  [*] Waiting for {len(pending)} service(s) to become ready ({', '.join(str(p) for p in pending)})...", flush=True)
    
    while time.time() - t0 < timeout:
        for port in list(pending):
            if check_single(port):
                info = ENDPOINT_MAP.get(port, (f"Port {port}", "tcp", None))
                latency = time.time() - t0
                print(f"  [+] {info[0]} (port {port}) is READY [{latency:4.1f}s]", flush=True)
                pending.remove(port)
        if not pending:
            return True
        time.sleep(0.25)
        
    if pending:
        missing_names = [f"{ENDPOINT_MAP.get(p, (f'Port {p}',))[0]} ({p})" for p in pending]
        print(f"  [-] [WARN/TIMEOUT] Still pending after {timeout:.0f}s: {', '.join(missing_names)}", flush=True)
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description="SG Platform Readiness Poller")
    parser.add_argument("--infra", action="store_true", help="Check PostgreSQL and Redis readiness")
    parser.add_argument("--ports", nargs="+", type=int, help="List of ports to wait for")
    parser.add_argument("--timeout", type=float, default=30.0, help="Max wait timeout in seconds")
    
    args = parser.parse_args()
    
    if args.infra:
        if not ensure_infrastructure(timeout=args.timeout):
            sys.exit(1)
        sys.exit(0)
        
    if args.ports:
        if not wait_for_ports(args.ports, timeout=args.timeout):
            sys.exit(1)
        sys.exit(0)
        
    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
