# ==============================================================================
# SG Trading Platform - Unified Python 3.13 Environment Setup (PowerShell)
# ==============================================================================

param(
    [switch]$Recreate = $false
)

$ErrorActionPreference = "Stop"
$RepoRoot = $PSScriptRoot
Set-Location -Path $RepoRoot

Write-Host "================================================================" -ForegroundColor Cyan
Write-Host "  SG Trading Platform - Python 3.13 Environment Setup" -ForegroundColor Cyan
Write-Host "================================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Detect Python 3.13.x
Write-Host "[1/4] Checking for Python 3.13.x installation..." -ForegroundColor Yellow

$PythonCommand = $null

try {
    $pyVer = & py -3.13 --version 2>&1
    if ($LASTEXITCODE -eq 0 -and $pyVer -match "3\.13\.") {
        $PythonCommand = "py -3.13"
        Write-Host "  Found: $pyVer (via py launcher)" -ForegroundColor Green
    }
} catch {
}

if (-not $PythonCommand) {
    try {
        $stdPy = & python --version 2>&1
        if ($LASTEXITCODE -eq 0 -and $stdPy -match "3\.13\.") {
            $PythonCommand = "python"
            Write-Host "  Found: $stdPy (via python command)" -ForegroundColor Green
        }
    } catch {
    }
}

if (-not $PythonCommand) {
    Write-Host ""
    Write-Host "ERROR: Python 3.13.x was not found on your system." -ForegroundColor Red
    Write-Host "Please install Python 3.13 via winget or official installer:" -ForegroundColor Yellow
    Write-Host "  winget install Python.Python.3.13" -ForegroundColor Cyan
    Write-Host "  or visit https://www.python.org/downloads/release/python-3130/" -ForegroundColor Cyan
    Write-Host ""
    Exit 1
}

# 2. Create or reuse unified virtual environment
$VenvDir = Join-Path $RepoRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvPip = Join-Path $VenvDir "Scripts\pip.exe"

if ($Recreate -and (Test-Path $VenvDir)) {
    Write-Host "[2/4] Removing existing .venv..." -ForegroundColor Yellow
    Remove-Item -Path $VenvDir -Recurse -Force
}

if (-not (Test-Path $VenvPython)) {
    Write-Host "[2/4] Creating unified virtual environment (.venv) with Python 3.13..." -ForegroundColor Yellow
    if ($PythonCommand -eq "py -3.13") {
        & py -3.13 -m venv $VenvDir
    } else {
        & python -m venv $VenvDir
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Failed to create virtual environment." -ForegroundColor Red
        Exit 1
    }
    Write-Host "  Created virtual environment at $VenvDir" -ForegroundColor Green
} else {
    Write-Host "[2/4] Using existing virtual environment at $VenvDir" -ForegroundColor Green
}

# 3. Upgrade bootstrap tools
Write-Host "[3/4] Upgrading pip, setuptools, wheel..." -ForegroundColor Yellow
& $VenvPython -m pip install --upgrade pip setuptools wheel pytest pytest-asyncio pytest-cov

# 4. Install all packages and services into shared venv in a single unified resolver pass
Write-Host "[4/4] Installing shared packages and all 13 services (monorepo resolution)..." -ForegroundColor Yellow

$installArgs = @(
    "install",
    "-e", ".\database",
    "-e", ".\sg_security",
    "-e", ".\auth_service",
    "-e", ".\market_data_service",
    "-e", ".\broker_service",
    "-e", ".\strategy_service",
    "-e", ".\regime_detection_service",
    "-e", ".\execution_orchestrator_service",
    "-e", ".\risk_engine_service",
    "-e", ".\execution_engine_service",
    "-e", ".\portfolio_management_service",
    "-e", ".\backtesting_engine_service",
    "-e", ".\ml_platform_service",
    "-e", ".\ai_analyst_service",
    "-e", ".\signal_aggregation_service"
)

& $VenvPip @installArgs
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Monorepo package installation failed." -ForegroundColor Red
    Exit 1
}

Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host "  Setup Complete! Unified Python 3.13 environment is ready." -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""
