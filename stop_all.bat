@echo off
REM ============================================================
REM  SG Trading Platform - Stop all services
REM  Finds and terminates processes bound to each service port.
REM ============================================================

setlocal enabledelayedexpansion

set PORTS=8001 8002 8003 8004 8005 8006 8007 8008 8009 8010 8011 8012 8013 3000 5000

for %%P in (%PORTS%) do (
    for /f "tokens=5" %%A in ('netstat -ano ^| findstr :%%P ^| findstr LISTENING') do (
        echo Killing process on port %%P (PID %%A^)...
        taskkill /PID %%A /F >nul 2>&1
    )
)

echo.
echo ============================================================
echo Done. All platform service ports should now be free.
echo ============================================================
echo.

