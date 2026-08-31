import os
import sys
import subprocess
import re

REPO_ROOT = r"C:\Users\emmat\Downloads\sg_repo"
PYTEST_EXE = os.path.join(REPO_ROOT, ".venv", "Scripts", "pytest.exe")

test_dirs = [
    "sg_security",
    "auth_service",
    "market_data_service",
    "broker_service",
    "strategy_service",
    "regime_detection_service",
    "execution_orchestrator_service",
    "risk_engine_service",
    "portfolio_management_service",
    "backtesting_engine_service",
    "ml_platform_service",
    "ai_analyst_service",
    "signal_aggregation_service"
]

env = os.environ.copy()
env["SECRET_KEY"] = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
env["JWT_SECRET"] = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
env["DATABASE_URL"] = "postgresql+asyncpg://user:pass@localhost:5432/sg_db"
env["REDIS_URL"] = "redis://localhost:6379/0"
env["ENVIRONMENT"] = "testing"
env["TESTING"] = "true"

results = []

print("=" * 80)
print(f"Running pytest suites across all packages on Python 3.13")
print("=" * 80)

for item in test_dirs:
    item_dir = os.path.join(REPO_ROOT, item)
    tests_path = os.path.join(item_dir, "tests")
    if not os.path.isdir(tests_path):
        continue

    cmd = [PYTEST_EXE, "tests", "-v", "--tb=short"]
    res = subprocess.run(cmd, cwd=item_dir, env=env, capture_output=True, text=True)
    
    stdout = res.stdout
    stderr = res.stderr
    output = stdout + "\n" + stderr
    
    # Parse pytest summary line (e.g. "= 12 passed, 2 skipped in 0.45s =")
    summary_match = re.search(r"=+\s+([0-9\w\s,]+)\s+in\s+[\d\.]+s\s*=+", output)
    summary_text = summary_match.group(1) if summary_match else ""
    
    passed_m = re.search(r"(\d+)\s+passed", output)
    failed_m = re.search(r"(\d+)\s+failed", output)
    skipped_m = re.search(r"(\d+)\s+skipped", output)
    errors_m = re.search(r"(\d+)\s+error", output)
    
    passed = int(passed_m.group(1)) if passed_m else 0
    failed = int(failed_m.group(1)) if failed_m else 0
    skipped = int(skipped_m.group(1)) if skipped_m else 0
    errors = int(errors_m.group(1)) if errors_m else 0
    
    status = "PASS" if (res.returncode == 0 or (failed == 0 and errors == 0 and passed > 0)) else "FAIL"
    if passed == 0 and failed == 0 and errors == 0:
        status = "EMPTY / NO TESTS"
        
    results.append({
        "package": item,
        "status": status,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "errors": errors,
        "summary": summary_text or f"returncode: {res.returncode}"
    })
    
    print(f"[{status}] {item:<32} | Passed: {passed:<3} | Failed: {failed:<3} | Errors: {errors:<3} | {summary_text}")
    if status == "FAIL":
        print(f"--- Pytest output for {item} ---")
        print("\n".join(output.splitlines()[-20:]))

print("\n" + "=" * 80)
print("PYTEST SUITE SUMMARY TABLE (Python 3.13):")
print("=" * 80)
print(f"{'Package / Service':<32} | {'Status':<6} | {'Passed':<6} | {'Failed':<6} | {'Errors':<6} | {'Summary'}")
print("-" * 80)
total_p = 0
total_f = 0
total_e = 0
for r in results:
    total_p += r["passed"]
    total_f += r["failed"]
    total_e += r["errors"]
    print(f"{r['package']:<32} | {r['status']:<6} | {r['passed']:<6} | {r['failed']:<6} | {r['errors']:<6} | {r['summary']}")
print("-" * 80)
print(f"{'TOTALS':<32} | {'':<6} | {total_p:<6} | {total_f:<6} | {total_e:<6} |")
print("=" * 80)
