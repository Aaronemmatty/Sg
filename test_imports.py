import os
import sys
import subprocess

REPO_ROOT = r"C:\Users\emmat\Downloads\sg_repo"
PYTHON_EXE = os.path.join(REPO_ROOT, ".venv", "Scripts", "python.exe")

services = [
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
]

env = os.environ.copy()
env["SECRET_KEY"] = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
env["JWT_SECRET"] = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
env["DATABASE_URL"] = "postgresql+asyncpg://user:pass@localhost:5432/sg_db"
env["REDIS_URL"] = "redis://localhost:6379/0"
env["ENVIRONMENT"] = "development"
env["BROKER_API_KEY"] = "test"
env["BROKER_API_SECRET"] = "test"
env["KITE_API_KEY"] = "test"
env["KITE_API_SECRET"] = "test"

results = []

print("=" * 70)
print(f"Testing service imports on Python 3.13 in isolated processes")
print("=" * 70)

for svc, port in services:
    svc_dir = os.path.join(REPO_ROOT, svc)
    cmd = [
        PYTHON_EXE,
        "-c",
        "import app.main as m; app = getattr(m, 'app', None); print(f'APP_LOADED:{type(app).__name__ if app else None}')"
    ]
    res = subprocess.run(cmd, cwd=svc_dir, env=env, capture_output=True, text=True)
    if res.returncode == 0 and "APP_LOADED:" in res.stdout:
        app_type = [line for line in res.stdout.splitlines() if line.startswith("APP_LOADED:")][0].split(":", 1)[1]
        status = "PASS"
        detail = f"FastAPI app loaded ({app_type})"
    else:
        status = "FAIL"
        err_lines = [l for l in (res.stderr or res.stdout).strip().splitlines() if l.strip()]
        detail = err_lines[-1] if err_lines else "Unknown error"
        print(f"--- Error for {svc} ---")
        print(res.stderr or res.stdout)
    results.append((svc, port, status, detail))
    print(f"[{status}] {svc:<32} (port {port}): {detail}")

print("\n" + "=" * 70)
print("PYTHON 3.13 MICROSERVICE IMPORT VERIFICATION TABLE:")
print("=" * 70)
print(f"{'Service':<35} | {'Port':<5} | {'Status':<6} | {'Details'}")
print("-" * 70)
for svc, port, status, detail in results:
    print(f"{svc:<35} | {port:<5} | {status:<6} | {detail}")
print("=" * 70)
