@echo off
REM ============================================================
REM  SG Trading Platform - Stop all services
REM  Finds and cleanly terminates process trees bound to each service port.
REM ============================================================

set REPO=%~dp0
if "%REPO:~-1%"=="\" set REPO=%REPO:~0,-1%

if exist "%REPO%\.venv\Scripts\python.exe" (
    "%REPO%\.venv\Scripts\python.exe" "%REPO%\scripts\stop_services.py"
    exit /b %ERRORLEVEL%
)

setlocal enabledelayedexpansion

powershell -NoProfile -Command "$ports = 8001..8014 + 3000, 5000; $pids = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in $ports } | Select-Object -ExpandProperty OwningProcess -Unique; foreach ($p in $pids) { if ($p -gt 4) { Write-Host \"Killing process tree for PID $p...\"; taskkill /PID $p /T /F 2>$null } }"

echo.
echo ============================================================
echo Done. All platform service ports should now be free.
echo ============================================================
echo.


