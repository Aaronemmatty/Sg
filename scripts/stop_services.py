#!/usr/bin/env python3
"""
SG Platform - Service Stopper
Cleanly terminates all processes and child trees bound to SG microservice ports.
"""

import sys
import time
import socket
import subprocess
import re

PORTS = [5000, 3000, 8001, 8002, 8003, 8004, 8005, 8006, 8007, 8008, 8009, 8010, 8011, 8012, 8013, 8014]


def get_listening_pids(target_ports: list[int]) -> dict[int, set[int]]:
    """Return map of port -> set of PIDs listening on that exact port."""
    port_pids: dict[int, set[int]] = {p: set() for p in target_ports}
    try:
        out = subprocess.check_output(["netstat", "-ano"], text=True, errors="ignore")
    except Exception as e:
        print(f"[-] netstat failed: {e}", flush=True)
        return port_pids

    for line in out.splitlines():
        line = line.strip()
        if "LISTENING" not in line and "LISTEN" not in line:
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        local_addr = parts[1]
        pid_str = parts[-1]
        
        if not pid_str.isdigit():
            continue
        pid = int(pid_str)
        if pid <= 4:
            continue

        # Extract port from local_addr (e.g. 127.0.0.1:8001 or [::]:8001 or 0.0.0.0:8001)
        port_match = re.search(r":(\d+)$", local_addr)
        if port_match:
            port = int(port_match.group(1))
            if port in port_pids:
                port_pids[port].add(pid)

    return port_pids


def stop_all():
    print("============================================================", flush=True)
    print("  Stopping SG Trading Platform Services", flush=True)
    print("============================================================", flush=True)
    
    port_pids = get_listening_pids(PORTS)
    all_pids = set()
    for port, pids in port_pids.items():
        for pid in pids:
            all_pids.add((pid, port))

    if not all_pids:
        print("  [+] No active SG service processes found on ports 8001-8014, 3000, 5000.", flush=True)
    else:
        for pid, port in sorted(all_pids, key=lambda x: x[1]):
            print(f"  [*] Terminating process tree for port {port} (PID {pid})...", flush=True)
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)

    # Wait and verify ports are released
    time.sleep(1.0)
    remaining = get_listening_pids(PORTS)
    still_busy = [p for p, pids in remaining.items() if pids]
    if still_busy:
        print(f"  [!] Retrying termination for ports: {still_busy}...", flush=True)
        for p in still_busy:
            for pid in remaining[p]:
                subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        time.sleep(1.0)
        remaining = get_listening_pids(PORTS)
        still_busy = [p for p, pids in remaining.items() if pids]

    if not still_busy:
        print("\n[+] Success: All SG service ports are free and clear.", flush=True)
        print("============================================================\n", flush=True)
        return 0
    else:
        print(f"\n[-] Warning: Ports still in use: {still_busy}", flush=True)
        print("============================================================\n", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(stop_all())
