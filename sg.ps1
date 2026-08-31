<#
.SYNOPSIS
    SG Trading Platform - Native Process Management CLI (Windows)

.DESCRIPTION
    Manages all 13 Python microservices, Next.js frontend dashboard,
    MLflow tracking server, and local database/cache tools.

.EXAMPLE
    .\sg.ps1 start
    .\sg.ps1 stop
    .\sg.ps1 restart
    .\sg.ps1 health
    .\sg.ps1 status
    .\sg.ps1 db
    .\sg.ps1 redis
    .\sg.ps1 secrets
#>

param (
    [Parameter(Position=0)]
    [ValidateSet("start", "up", "stop", "down", "restart", "health", "status", "ps", "secrets", "db", "redis", "backup", "mlflow", "help")]
    [string]$Command = "help"
)

$RepoRoot = $PSScriptRoot
$PythonExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"

function Show-Help {
    Write-Host @"
================================================================================
  SG Trading Platform - Native Windows Management CLI
================================================================================

Usage: .\sg.ps1 <command>

Commands:
  start | up       Launch PostgreSQL check, Redis (WSL2), MLflow, all 13 microservices & dashboard
  stop  | down     Terminate all running SG services on ports 8001-8013, 3000, 5000
  restart          Perform full platform stop and clean startup
  health           Run comprehensive health check across all endpoints and latency
  status | ps      Check which service ports are active and listening
  secrets          Generate and patch local encryption & JWT secrets into .env
  db               Open native psql shell connected to localhost:5432 (sg_db)
  redis            Open WSL2 redis-cli connected to localhost:6379
  mlflow           Start standalone MLflow tracking server on http://localhost:5000
  backup           Dump PostgreSQL database and trigger WSL2 Redis snapshot
  help             Show this help screen
================================================================================
"@ -ForegroundColor Cyan
}

switch ($Command) {
    { $_ -in "start", "up" } {
        Write-Host "Starting SG Trading Platform natively..." -ForegroundColor Green
        Start-Process -FilePath "cmd.exe" -ArgumentList "/c `"$RepoRoot\start_all.bat`"" -NoNewWindow
    }

    { $_ -in "stop", "down" } {
        Write-Host "Stopping SG Trading Platform..." -ForegroundColor Yellow
        & "$RepoRoot\stop_all.bat"
    }

    "restart" {
        Write-Host "Restarting SG Trading Platform..." -ForegroundColor Yellow
        & "$RepoRoot\stop_all.bat"
        Start-Sleep -Seconds 2
        Start-Process -FilePath "cmd.exe" -ArgumentList "/c `"$RepoRoot\start_all.bat`"" -NoNewWindow
    }

    "health" {
        if (Test-Path $PythonExe) {
            & $PythonExe "$RepoRoot\scripts\health_check.py"
        } else {
            python "$RepoRoot\scripts\health_check.py"
        }
    }

    { $_ -in "status", "ps" } {
        Write-Host "Checking SG Service listening ports..." -ForegroundColor Cyan
        $ports = @(8001..8013) + @(3000, 5000, 5432, 6379)
        foreach ($port in $ports) {
            $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
            if ($conn) {
                Write-Host "  Port $port : LISTENING (PID: $($conn.OwningProcess | Select-Object -First 1))" -ForegroundColor Green
            } else {
                Write-Host "  Port $port : OFFLINE" -ForegroundColor DarkGray
            }
        }
    }

    "secrets" {
        Write-Host "Generating local cryptographic secrets..." -ForegroundColor Cyan
        if (Test-Path $PythonExe) {
            & $PythonExe "$RepoRoot\scripts\generate_secrets.py" --patch-env
        } else {
            python "$RepoRoot\scripts\generate_secrets.py" --patch-env
        }
    }

    "db" {
        $PsqlExe = "psql.exe"
        $Candidates = @(
            "psql.exe",
            "C:\Program Files\PostgreSQL\18\bin\psql.exe",
            "C:\Program Files\PostgreSQL\17\bin\psql.exe",
            "C:\Program Files\PostgreSQL\16\bin\psql.exe",
            "C:\Program Files\PostgreSQL\15\bin\psql.exe"
        )
        foreach ($c in $Candidates) {
            if (Get-Command $c -ErrorAction SilentlyContinue) { $PsqlExe = $c; break }
            elseif (Test-Path $c) { $PsqlExe = $c; break }
        }
        Write-Host "Connecting to native PostgreSQL (localhost:5432)..." -ForegroundColor Cyan
        & $PsqlExe -h localhost -p 5432 -U sg_user -d sg_db
    }

    "redis" {
        Write-Host "Connecting to WSL2 Redis CLI (localhost:6379)..." -ForegroundColor Cyan
        wsl redis-cli -h 127.0.0.1 -p 6379
    }

    "mlflow" {
        Write-Host "Starting native MLflow tracking server on http://localhost:5000..." -ForegroundColor Green
        $MlflowExe = Join-Path $RepoRoot ".venv\Scripts\mlflow.exe"
        if (Test-Path $MlflowExe) {
            & $MlflowExe server --backend-store-uri sqlite:///mlflow.db --default-artifact-root ./mlruns --host 127.0.0.1 --port 5000
        } else {
            mlflow server --backend-store-uri sqlite:///mlflow.db --default-artifact-root ./mlruns --host 127.0.0.1 --port 5000
        }
    }

    "backup" {
        & "$RepoRoot\scripts\backup.ps1"
    }

    default {
        Show-Help
    }
}
