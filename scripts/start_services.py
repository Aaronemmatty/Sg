#!/usr/bin/env python3
"""
SG Platform - Background Service Launcher.
Starts MLflow, all 14 microservices, and the Next.js Dashboard.
"""
from __future__ import annotations

import os
import sys
import time
import socket
import subprocess
from pathlib import Path

REPO_ROOT = Path("c:/Users/emmat/Downloads/sg_repo")
PYTHON_EXE = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
LOGS_DIR = REPO_ROOT / "logs"
LOGS_DIR.mkdir(exist_ok=True)

SERVICES = [
    ("auth_service", 8001),
    ("market_data_service", 8002),
    ("broker_service", 8003),
    ("strategy_service", 8004),
    ("regime_detection_service", 8005),
    ("execution_orchestrator_service", 8006),
    ("risk_engine_service", 8007),
    ("execution_engine_service", 8008),
    ("portfolio_management_service", 8009),
    ("backtesting_engine_service", 8010),
    ("ml_platform_service", 8011),
    ("ai_analyst_service", 8012),
    ("signal_aggregation_service", 8013),
    ("notification_service", 8014),
]


def is_port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def main():
    print("============================================================")
    print("  Starting SG Trading Platform Services...")
    print("============================================================")

    env = dict(os.environ)
    sg_security_dir = str(REPO_ROOT / "sg_security")

    DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

    # 1. MLflow
    if not is_port_open(5000):
        mlflow_log = open(LOGS_DIR / "mlflow.log", "w", encoding="utf-8")
        mlflow_cmd = [
            str(PYTHON_EXE), "-m", "mlflow", "server",
            "--backend-store-uri", "sqlite:///mlflow.db",
            "--default-artifact-root", "./mlruns",
            "--host", "127.0.0.1", "--port", "5000"
        ]
        subprocess.Popen(mlflow_cmd, cwd=str(REPO_ROOT), env=env, stdout=mlflow_log, stderr=subprocess.STDOUT, creationflags=DETACHED)
        print("  [*] Started MLflow on port 5000")

    # 2. Microservices
    for name, port in SERVICES:
        if not is_port_open(port):
            svc_dir = REPO_ROOT / name
            log_file = open(LOGS_DIR / f"{name}.log", "w", encoding="utf-8")
            s_env = dict(env)
            s_env["PYTHONPATH"] = f"{REPO_ROOT};{sg_security_dir};{svc_dir};."
            cmd = [
                str(PYTHON_EXE), "-m", "uvicorn", "app.main:app",
                "--host", "0.0.0.0", "--port", str(port)
            ]
            proc = subprocess.Popen(cmd, cwd=str(svc_dir), env=s_env, stdout=log_file, stderr=subprocess.STDOUT, creationflags=DETACHED)
            print(f"  [*] Started {name} on port {port} (PID {proc.pid})")
            time.sleep(0.3)
        else:
            print(f"  [+] {name} already listening on port {port}")

    # 3. Next.js Dashboard
    if not is_port_open(3000):
        dash_dir = REPO_ROOT / "sg-dashboard"
        dash_log = open(LOGS_DIR / "sg-dashboard.log", "w", encoding="utf-8")
        subprocess.Popen(["npm.cmd", "run", "dev"], cwd=str(dash_dir), env=env, stdout=dash_log, stderr=subprocess.STDOUT, creationflags=DETACHED)
        print("  [*] Started sg-dashboard on port 3000")
    else:
        print("  [+] sg-dashboard already listening on port 3000")

    print("\nWaiting for services to become healthy...")
    time.sleep(5)

    active_ports = [p for _, p in SERVICES if is_port_open(p)]
    print(f"[+] Active Microservices: {len(active_ports)}/{len(SERVICES)}")
    print(f"[+] MLflow (5000): {'OPEN' if is_port_open(5000) else 'PENDING'}")
    print(f"[+] Dashboard (3000): {'OPEN' if is_port_open(3000) else 'PENDING'}")
    print("Platform services launched! Keeping supervisory process alive...")
    try:
        while True:
            time.sleep(10)
    except KeyboardInterrupt:
        print("Stopping supervisor...")


if __name__ == "__main__":
    main()
