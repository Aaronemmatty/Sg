# SG Platform Native Database & Cache Backup Script
param (
    [string]$OutputDir = "$PSScriptRoot\..\backups",
    [string]$PostgresUser = "sg_user",
    [string]$PostgresDb = "sg_db",
    [string]$PostgresHost = "localhost",
    [int]$PostgresPort = 5432
)

$ErrorActionPreference = "Continue"

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$TargetDir = Join-Path $OutputDir $Timestamp

if (-not (Test-Path $TargetDir)) {
    New-Item -ItemType Directory -Path $TargetDir -Force | Out-Null
}

Write-Host "=================================================" -ForegroundColor Cyan
Write-Host "  SG Platform Backup - $Timestamp" -ForegroundColor Cyan
Write-Host "=================================================" -ForegroundColor Cyan

# 1. Backup Native PostgreSQL
Write-Host "[1/2] Backing up PostgreSQL database: $PostgresDb..." -ForegroundColor Yellow
$PgDumpExe = $null
$PgPaths = @(
    "pg_dump.exe",
    "C:\Program Files\PostgreSQL\16\bin\pg_dump.exe",
    "C:\Program Files\PostgreSQL\17\bin\pg_dump.exe",
    "C:\Program Files\PostgreSQL\15\bin\pg_dump.exe"
)

foreach ($p in $PgPaths) {
    if (Get-Command $p -ErrorAction SilentlyContinue) {
        $PgDumpExe = $p
        break
    } elseif (Test-Path $p) {
        $PgDumpExe = $p
        break
    }
}

if ($PgDumpExe) {
    $PgOutFile = Join-Path $TargetDir "postgres_${PostgresDb}_${Timestamp}.sql"
    & $PgDumpExe -h $PostgresHost -p $PostgresPort -U $PostgresUser -d $PostgresDb -F p -f $PgOutFile
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK] PostgreSQL dump saved to: $PgOutFile" -ForegroundColor Green
    } else {
        Write-Host "  [WARN] PostgreSQL pg_dump exited with code $LASTEXITCODE" -ForegroundColor Red
    }
} else {
    Write-Host "  [WARN] pg_dump.exe not found in PATH or standard Program Files directories." -ForegroundColor Red
}

# 2. Trigger Redis Snapshot in WSL2
Write-Host "[2/2] Triggering Redis BGSAVE in WSL2..." -ForegroundColor Yellow
if (Get-Command "wsl.exe" -ErrorAction SilentlyContinue) {
    wsl redis-cli bgsave
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  [OK] Redis BGSAVE triggered successfully in WSL2." -ForegroundColor Green
    } else {
        Write-Host "  [WARN] WSL2 Redis BGSAVE failed or Redis is not running." -ForegroundColor Red
    }
} else {
    Write-Host "  [WARN] wsl.exe not found on system." -ForegroundColor Red
}

Write-Host "=================================================" -ForegroundColor Cyan
Write-Host "  Backup completed. Target directory: $TargetDir" -ForegroundColor Cyan
Write-Host "=================================================" -ForegroundColor Cyan
