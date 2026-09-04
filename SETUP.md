# Native Windows Setup Guide (Python 3.13 + Native PostgreSQL + WSL2 Redis)

This document provides complete, copy-paste instructions for setting up and running the entire SG Trading Platform 100% natively on Windows without Docker.

---

## 1. Prerequisites

- **Windows 10/11 (64-bit)**
- **Python 3.13.x** (installed and available in PATH as `py -3.13` or `python`)
- **Node.js 20+ & npm** (for Next.js `sg-dashboard`)
- **WSL2** (for local high-performance Redis)
- **PowerShell 5.1+ or PowerShell 7+**

---

## 2. Native PostgreSQL Setup (Windows)

### Step 2.1: Install PostgreSQL 16
Install via winget in PowerShell (Admin or standard):
```powershell
winget install PostgreSQL.PostgreSQL.16
```
*(Alternatively, download and run the graphical installer from [EnterpriseDB](https://www.enterprisedb.com/downloads/postgres-postgresql-downloads)).*

### Step 2.2: Create Platform Database & Role
Open PowerShell and run `psql` (replace password prompts as needed):
```powershell
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -c "CREATE USER sg_user WITH PASSWORD '<your_secure_password>';"
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -c "CREATE DATABASE sg_db OWNER sg_user;"
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE sg_db TO sg_user;"
```

---

## 3. Redis Setup (Inside WSL2)

### Step 3.1: Install Redis inside WSL2
Open PowerShell and enter WSL:
```powershell
wsl
```
Inside the WSL bash prompt:
```bash
sudo apt-get update
sudo apt-get install -y redis-server
```

### Step 3.2: Configure Network Binding
To ensure Windows processes can connect to Redis without firewall or localhost binding restrictions:
```bash
# Allow connections from 0.0.0.0
sudo sed -i 's/^bind .*/bind 0.0.0.0/' /etc/redis/redis.conf
sudo sed -i 's/^protected-mode yes/protected-mode no/' /etc/redis/redis.conf

# Start / restart redis service
sudo service redis-server restart

# Verify Redis is listening
redis-cli ping
# Expected output: PONG
exit
```

### Step 3.3: Verify Connection from Windows
From Windows PowerShell, verify the connection:
```powershell
.\.venv\Scripts\python.exe -c "import redis; r = redis.Redis(host='localhost', port=6379); print('Redis Ping:', r.ping())"
# Expected output: Redis Ping: True
```

---

## 4. Platform Environment Setup

### Step 4.1: Build Unified Python 3.13 Virtual Environment
Run the monorepo setup script from repository root:
```powershell
powershell -ExecutionPolicy Bypass -File .\setup_env.ps1
```
This performs a single-pass installation of:
- Shared libraries: `database` (`sg_db`), `sg_security` (editable mode)
- All 13 backend microservices (editable mode)
- Heavy ML and infra wheels: `scikit-learn`, `xgboost`, `lightgbm`, `asyncpg`, `SQLAlchemy`, `pydantic`, `mlflow`, `optuna`

### Step 4.2: Generate Cryptographic Secrets & Local .env
```powershell
.\sg.ps1 secrets
```
This generates random secrets (JWT private/public keypair, secret keys) and patches `.env`.

### Step 4.2: Provision First Administrator Account
Before logging into the dashboard for the first time, provision the initial administrator account:
```powershell
.\sg.ps1 admin
```
*(Or specify custom credentials via `.\.venv\Scripts\python.exe scripts\create_admin.py --email <email> --password "<pass>"`).*

Default Credentials created:
- **Email**: `admin@sg-trading.com`
- **Password**: `<generated_during_provisioning>` (or set via `--password`)
- **Roles**: `admin`, `risk_officer`, `trader`

---

## 5. Starting the Platform

You can start the entire stack using either PowerShell CLI or Batch script:

### Using PowerShell CLI:
```powershell
# Start all services, MLflow, Redis check, and dashboard
.\sg.ps1 start

# Check real-time health across all ports (8001-8013, 3000, 5000)
.\sg.ps1 health

# Check active listening ports
.\sg.ps1 status

# Open interactive PostgreSQL shell
.\sg.ps1 db

# Open interactive Redis shell
.\sg.ps1 redis
```

### Using Windows Batch Launcher:
```cmd
start_all.bat
```

To stop all platform processes:
```powershell
.\sg.ps1 stop
# OR
stop_all.bat
```

---

## 6. Port & Service Mapping

| Service | Port | Endpoint URL | Description |
|---|:---:|---|---|
| **Next.js Dashboard** | `3000` | `http://localhost:3000` | Web UI frontend |
| **MLflow Tracking Server** | `5000` | `http://localhost:5000` | Model experiments & artifacts |
| **PostgreSQL** | `5432` | `localhost:5432` | Relational platform DB (`sg_db`) |
| **Redis** | `6379` | `localhost:6379` | Cache & pub/sub message broker |
| **Auth Service** | `8001` | `http://localhost:8001` | JWT identity, users, sessions |
| **Market Data Service** | `8002` | `http://localhost:8002` | Real-time ticks & candle aggregator |
| **Broker Service** | `8003` | `http://localhost:8003` | Zerodha Kite / Paper broker adapter |
| **Strategy Service** | `8004` | `http://localhost:8004` | Technical strategies runner & registry |
| **Regime Detection Service** | `8005` | `http://localhost:8005` | Market regime ML classifier |
| **Execution Orchestrator** | `8006` | `http://localhost:8006` | Order routing & state machine |
| **Risk Engine Service** | `8007` | `http://localhost:8007` | Pre-trade risk checks & limits |
| **Execution Engine Service** | `8008` | `http://localhost:8008` | Direct exchange order execution |
| **Portfolio Management** | `8009` | `http://localhost:8009` | Positions, MTM, and PnL ledger |
| **Backtesting Engine** | `8010` | `http://localhost:8010` | Monte Carlo & historical backtesting |
| **ML Platform Service** | `8011` | `http://localhost:8011` | XGBoost/LightGBM model training |
| **AI Analyst Service** | `8012` | `http://localhost:8012` | Claude / LLM market review |
| **Signal Aggregation Service**| `8013` | `http://localhost:8013` | Multi-strategy ensemble consensus |
| **Notification Service**      | `8014` | `http://localhost:8014` | Telegram execution alerts (outbound-only) |
