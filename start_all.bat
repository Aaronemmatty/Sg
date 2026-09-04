@echo off
REM ============================================================
REM  SG Trading Platform - Start Native Stack
REM  Starts WSL2 Redis, Native MLflow, all 13 microservices,
REM  and the Next.js Frontend Dashboard (Python 3.13 + Node.js)
REM ============================================================

set REPO=%~dp0
if "%REPO:~-1%"=="\" set REPO=%REPO:~0,-1%

if not exist "%REPO%\.venv\Scripts\activate.bat" (
    echo.
    echo [ERROR] Unified virtual environment not found at %REPO%\.venv
    echo Please run the setup script first:
    echo     powershell -ExecutionPolicy Bypass -File .\setup_env.ps1
    echo.
    pause
    exit /b 1
)

echo ============================================================
echo   Starting SG Trading Platform (Native Windows Stack)
echo ============================================================

REM Pre-flight Safety Gate Check (CONFIRM required if BROKER_MODE=live)
"%REPO%\.venv\Scripts\python.exe" "%REPO%\scripts\check_startup_gate.py"
if %ERRORLEVEL% neq 0 (
    echo [ABORTED] Platform startup cancelled by pre-flight safety gate.
    exit /b 1
)

REM Step 0: Ensure Core Infrastructure (PostgreSQL & Redis)
echo [0/5] Verifying Core Infrastructure (PostgreSQL :5432, Redis :6379)...
"%REPO%\.venv\Scripts\python.exe" "%REPO%\scripts\wait_for_tier.py" --infra --timeout 15
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Core infrastructure is not available. Aborting startup.
    exit /b 1
)

REM Step 1: Start MLflow Tracking Server (5000)
echo [1/5] Starting MLflow Tracking Server on 5000...
start "mlflow_server (5000)" cmd /k "cd /d %REPO% && "%REPO%\.venv\Scripts\python.exe" -m mlflow server --backend-store-uri sqlite:///mlflow.db --default-artifact-root ./mlruns --host 127.0.0.1 --port 5000"
"%REPO%\.venv\Scripts\python.exe" "%REPO%\scripts\wait_for_tier.py" --ports 5000 --timeout 45

REM Step 2: Core Data and Identity Services (8001, 8002, 8003)
echo [2/5] Starting Core Data and Identity Services (auth, market_data, broker)...
start "auth_service (8001)" cmd /k "cd /d %REPO%\auth_service && "%REPO%\.venv\Scripts\python.exe" -m uvicorn app.main:app --port 8001"
start "market_data_service (8002)" cmd /k "cd /d %REPO%\market_data_service && "%REPO%\.venv\Scripts\python.exe" -m uvicorn app.main:app --port 8002"
start "broker_service (8003)" cmd /k "cd /d %REPO%\broker_service && "%REPO%\.venv\Scripts\python.exe" -m uvicorn app.main:app --port 8003"
"%REPO%\.venv\Scripts\python.exe" "%REPO%\scripts\wait_for_tier.py" --ports 8001 8002 8003 --timeout 30

REM Step 3: Intelligence and Strategy Layer (8005, 8013, 8004, 8011, 8012)
echo [3/5] Starting Intelligence and Strategy Layer (regime, signals, strategy, ml_platform, ai_analyst)...
start "regime_detection_service (8005)" cmd /k "cd /d %REPO%\regime_detection_service && "%REPO%\.venv\Scripts\python.exe" -m uvicorn app.main:app --port 8005"
start "signal_aggregation_service (8013)" cmd /k "cd /d %REPO%\signal_aggregation_service && "%REPO%\.venv\Scripts\python.exe" -m uvicorn app.main:app --port 8013"
start "strategy_service (8004)" cmd /k "cd /d %REPO%\strategy_service && "%REPO%\.venv\Scripts\python.exe" -m uvicorn app.main:app --port 8004"
start "ml_platform_service (8011)" cmd /k "cd /d %REPO%\ml_platform_service && "%REPO%\.venv\Scripts\python.exe" -m uvicorn app.main:app --port 8011"
start "ai_analyst_service (8012)" cmd /k "cd /d %REPO%\ai_analyst_service && "%REPO%\.venv\Scripts\python.exe" -m uvicorn app.main:app --port 8012"
"%REPO%\.venv\Scripts\python.exe" "%REPO%\scripts\wait_for_tier.py" --ports 8005 8013 8004 8011 8012 --timeout 45

REM Step 4: Execution and Risk Management Layer (8007, 8006, 8008, 8009, 8010, 8014)
echo [4/5] Starting Execution and Risk Management Layer (risk, orchestrator, execution, portfolio, backtesting, notification)...
start "risk_engine_service (8007)" cmd /k "cd /d %REPO%\risk_engine_service && "%REPO%\.venv\Scripts\python.exe" -m uvicorn app.main:app --port 8007"
start "execution_orchestrator_service (8006)" cmd /k "cd /d %REPO%\execution_orchestrator_service && "%REPO%\.venv\Scripts\python.exe" -m uvicorn app.main:app --port 8006"
start "execution_engine_service (8008)" cmd /k "cd /d %REPO%\execution_engine_service && "%REPO%\.venv\Scripts\python.exe" -m uvicorn app.main:app --port 8008"
start "portfolio_management_service (8009)" cmd /k "cd /d %REPO%\portfolio_management_service && "%REPO%\.venv\Scripts\python.exe" -m uvicorn app.main:app --port 8009"
start "backtesting_engine_service (8010)" cmd /k "cd /d %REPO%\backtesting_engine_service && "%REPO%\.venv\Scripts\python.exe" -m uvicorn app.main:app --port 8010"
start "notification_service (8014)" cmd /k "cd /d %REPO%\notification_service && "%REPO%\.venv\Scripts\python.exe" -m uvicorn app.main:app --port 8014"
"%REPO%\.venv\Scripts\python.exe" "%REPO%\scripts\wait_for_tier.py" --ports 8007 8006 8008 8009 8010 8014 --timeout 35

REM Step 5: Web Frontend Dashboard (3000)
echo [5/5] Starting sg-dashboard on 3000...
if exist "%REPO%\sg-dashboard\package.json" (
    start "sg-dashboard (3000)" cmd /k "cd /d %REPO%\sg-dashboard && npm run dev"
    "%REPO%\.venv\Scripts\python.exe" "%REPO%\scripts\wait_for_tier.py" --ports 3000 --timeout 45
)

echo.
echo ============================================================
echo   Platform startup complete! All tiers verified healthy.
echo   - Dashboard:      http://localhost:3000
echo   - MLflow UI:      http://localhost:5000
echo   - Microservices:  Ports 8001-8014
echo ============================================================
echo.

