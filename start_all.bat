@echo off
REM ============================================================
REM  SG Trading Platform - Start all 13 backend services
REM  Uses the unified Python 3.13 root virtual environment (.venv)
REM  Opens one fresh Command Prompt window per service in the
REM  established startup order.
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
echo Starting SG Trading Platform (13 Services on Python 3.13)
echo ============================================================

echo Starting auth_service on 8001...
start "auth_service (8001)" cmd /k "cd /d %REPO%\auth_service && call %REPO%\.venv\Scripts\activate && uvicorn app.main:app --port 8001"
timeout /t 5 /nobreak >nul

echo Starting market_data_service on 8002...
start "market_data_service (8002)" cmd /k "cd /d %REPO%\market_data_service && call %REPO%\.venv\Scripts\activate && uvicorn app.main:app --port 8002"
timeout /t 5 /nobreak >nul

echo Starting regime_detection_service on 8005...
start "regime_detection_service (8005)" cmd /k "cd /d %REPO%\regime_detection_service && call %REPO%\.venv\Scripts\activate && uvicorn app.main:app --port 8005"
timeout /t 5 /nobreak >nul

echo Starting signal_aggregation_service on 8013...
start "signal_aggregation_service (8013)" cmd /k "cd /d %REPO%\signal_aggregation_service && call %REPO%\.venv\Scripts\activate && uvicorn app.main:app --port 8013"
timeout /t 5 /nobreak >nul

echo Starting strategy_service on 8004...
start "strategy_service (8004)" cmd /k "cd /d %REPO%\strategy_service && call %REPO%\.venv\Scripts\activate && uvicorn app.main:app --port 8004"
timeout /t 5 /nobreak >nul

echo Starting execution_orchestrator_service on 8006...
start "execution_orchestrator_service (8006)" cmd /k "cd /d %REPO%\execution_orchestrator_service && call %REPO%\.venv\Scripts\activate && uvicorn app.main:app --port 8006"
timeout /t 5 /nobreak >nul

echo Starting risk_engine_service on 8007...
start "risk_engine_service (8007)" cmd /k "cd /d %REPO%\risk_engine_service && call %REPO%\.venv\Scripts\activate && uvicorn app.main:app --port 8007"
timeout /t 5 /nobreak >nul

echo Starting execution_engine_service on 8008...
start "execution_engine_service (8008)" cmd /k "cd /d %REPO%\execution_engine_service && call %REPO%\.venv\Scripts\activate && uvicorn app.main:app --port 8008"
timeout /t 5 /nobreak >nul

echo Starting broker_service on 8003...
start "broker_service (8003)" cmd /k "cd /d %REPO%\broker_service && call %REPO%\.venv\Scripts\activate && uvicorn app.main:app --port 8003"
timeout /t 5 /nobreak >nul

echo Starting portfolio_management_service on 8009...
start "portfolio_management_service (8009)" cmd /k "cd /d %REPO%\portfolio_management_service && call %REPO%\.venv\Scripts\activate && uvicorn app.main:app --port 8009"
timeout /t 5 /nobreak >nul

echo Starting backtesting_engine_service on 8010...
start "backtesting_engine_service (8010)" cmd /k "cd /d %REPO%\backtesting_engine_service && call %REPO%\.venv\Scripts\activate && uvicorn app.main:app --port 8010"
timeout /t 5 /nobreak >nul

echo Starting ml_platform_service on 8011...
start "ml_platform_service (8011)" cmd /k "cd /d %REPO%\ml_platform_service && call %REPO%\.venv\Scripts\activate && uvicorn app.main:app --port 8011"
timeout /t 5 /nobreak >nul

echo Starting ai_analyst_service on 8012...
start "ai_analyst_service (8012)" cmd /k "cd /d %REPO%\ai_analyst_service && call %REPO%\.venv\Scripts\activate && uvicorn app.main:app --port 8012"

echo.
echo ============================================================
echo All 13 services launched in separate windows.
echo Check each window for "Application startup complete".
echo ============================================================
echo.
pause
