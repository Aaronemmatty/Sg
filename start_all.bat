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

REM Step 0: Ensure Redis is running
echo [0/16] Redis verified on localhost:6379...


REM Step 1: Start MLflow Tracking Server (5000)
echo [1/16] Starting MLflow Tracking Server on 5000...
start "mlflow_server (5000)" cmd /k "cd /d %REPO% && call .venv\Scripts\activate && mlflow server --backend-store-uri sqlite:///mlflow.db --default-artifact-root ./mlruns --host 127.0.0.1 --port 5000"
ping -n 2 127.0.0.1 >nul

REM Step 2: Core Data & Identity Services
echo [2/16] Starting auth_service on 8001...
start "auth_service (8001)" cmd /k "cd /d %REPO%\auth_service && call %REPO%\.venv\Scripts\activate && uvicorn app.main:app --port 8001"
ping -n 2 127.0.0.1 >nul

echo [3/16] Starting market_data_service on 8002...
start "market_data_service (8002)" cmd /k "cd /d %REPO%\market_data_service && call %REPO%\.venv\Scripts\activate && uvicorn app.main:app --port 8002"
ping -n 2 127.0.0.1 >nul

echo [4/16] Starting broker_service on 8003...
start "broker_service (8003)" cmd /k "cd /d %REPO%\broker_service && call %REPO%\.venv\Scripts\activate && uvicorn app.main:app --port 8003"
ping -n 2 127.0.0.1 >nul

REM Step 3: Intelligence Layer
echo [5/16] Starting regime_detection_service on 8005...
start "regime_detection_service (8005)" cmd /k "cd /d %REPO%\regime_detection_service && call %REPO%\.venv\Scripts\activate && uvicorn app.main:app --port 8005"
ping -n 2 127.0.0.1 >nul

echo [6/16] Starting signal_aggregation_service on 8013...
start "signal_aggregation_service (8013)" cmd /k "cd /d %REPO%\signal_aggregation_service && call %REPO%\.venv\Scripts\activate && uvicorn app.main:app --port 8013"
ping -n 2 127.0.0.1 >nul

echo [7/16] Starting strategy_service on 8004...
start "strategy_service (8004)" cmd /k "cd /d %REPO%\strategy_service && call %REPO%\.venv\Scripts\activate && uvicorn app.main:app --port 8004"
ping -n 2 127.0.0.1 >nul

echo [8/16] Starting ml_platform_service on 8011...
start "ml_platform_service (8011)" cmd /k "cd /d %REPO%\ml_platform_service && call %REPO%\.venv\Scripts\activate && uvicorn app.main:app --port 8011"
ping -n 2 127.0.0.1 >nul

echo [9/16] Starting ai_analyst_service on 8012...
start "ai_analyst_service (8012)" cmd /k "cd /d %REPO%\ai_analyst_service && call %REPO%\.venv\Scripts\activate && uvicorn app.main:app --port 8012"
ping -n 2 127.0.0.1 >nul

REM Step 4: Execution & Risk Management Layer
echo [10/16] Starting risk_engine_service on 8007...
start "risk_engine_service (8007)" cmd /k "cd /d %REPO%\risk_engine_service && call %REPO%\.venv\Scripts\activate && uvicorn app.main:app --port 8007"
ping -n 2 127.0.0.1 >nul

echo [11/16] Starting execution_orchestrator_service on 8006...
start "execution_orchestrator_service (8006)" cmd /k "cd /d %REPO%\execution_orchestrator_service && call %REPO%\.venv\Scripts\activate && uvicorn app.main:app --port 8006"
ping -n 2 127.0.0.1 >nul

echo [12/16] Starting execution_engine_service on 8008...
start "execution_engine_service (8008)" cmd /k "cd /d %REPO%\execution_engine_service && call %REPO%\.venv\Scripts\activate && uvicorn app.main:app --port 8008"
ping -n 2 127.0.0.1 >nul

echo [13/16] Starting portfolio_management_service on 8009...
start "portfolio_management_service (8009)" cmd /k "cd /d %REPO%\portfolio_management_service && call %REPO%\.venv\Scripts\activate && uvicorn app.main:app --port 8009"
ping -n 2 127.0.0.1 >nul

echo [14/16] Starting backtesting_engine_service on 8010...
start "backtesting_engine_service (8010)" cmd /k "cd /d %REPO%\backtesting_engine_service && call %REPO%\.venv\Scripts\activate && uvicorn app.main:app --port 8010"
ping -n 2 127.0.0.1 >nul

REM Step 5: Web Frontend Dashboard
echo [15/16] Starting sg-dashboard on 3000...
if exist "%REPO%\sg-dashboard\package.json" (
    start "sg-dashboard (3000)" cmd /k "cd /d %REPO%\sg-dashboard && npm run dev"
)

echo.
echo ============================================================
echo   Platform startup initiated!
echo   - Dashboard:  http://localhost:3000
echo   - MLflow UI:  http://localhost:5000
echo   - Microservices: Ports 8001-8013
echo Platform services started.

