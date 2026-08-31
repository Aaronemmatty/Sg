# SG Trading Platform — Native Architecture & Deployment Notes

This document describes the native Windows operational architecture, port allocations, and runtime infrastructure for the SG Trading Platform (Python 3.13 + Next.js).

---

## 1. Native Execution Architecture

The platform runs 100% natively on Windows:
- **Python Runtime**: Python 3.13 unified virtual environment (`.venv`) at repository root.
- **Relational Storage**: Native PostgreSQL 16 (Windows service listening on `localhost:5432`).
- **Cache & Pub/Sub**: Redis Server running inside WSL2 (listening on `localhost:6379`).
- **ML Experiment Tracking**: Native MLflow tracking server (SQLite backend, listening on `http://localhost:5000`).
- **Backend Microservices**: 13 FastAPI services (ports 8001–8013).
- **Web Frontend**: Next.js Dashboard (`sg-dashboard`, port 3000).

---

## 2. Port & Service Mapping

| Service | Port | Endpoint URL | Database / Broker Dependency |
|---|:---:|---|---|
| **Next.js Dashboard** | `3000` | `http://localhost:3000` | Auth Service (`:8001`) |
| **MLflow Tracking Server** | `5000` | `http://localhost:5000` | SQLite (`mlflow.db`) |
| **PostgreSQL** | `5432` | `localhost:5432` | Relational Storage (`sg_db`) |
| **Redis (WSL2)** | `6379` | `localhost:6379` | Cache / Event PubSub |
| **Auth Service** | `8001` | `http://localhost:8001` | PostgreSQL + Redis |
| **Market Data Service** | `8002` | `http://localhost:8002` | Redis |
| **Broker Service** | `8003` | `http://localhost:8003` | PostgreSQL |
| **Strategy Service** | `8004` | `http://localhost:8004` | Redis |
| **Regime Detection Service** | `8005` | `http://localhost:8005` | PostgreSQL + Redis |
| **Execution Orchestrator** | `8006` | `http://localhost:8006` | PostgreSQL + Redis |
| **Risk Engine Service** | `8007` | `http://localhost:8007` | PostgreSQL |
| **Execution Engine Service** | `8008` | `http://localhost:8008` | PostgreSQL |
| **Portfolio Management** | `8009` | `http://localhost:8009` | PostgreSQL |
| **Backtesting Engine** | `8010` | `http://localhost:8010` | PostgreSQL |
| **ML Platform Service** | `8011` | `http://localhost:8011` | PostgreSQL + MLflow (`:5000`) |
| **AI Analyst Service** | `8012` | `http://localhost:8012` | Redis + Anthropic API |
| **Signal Aggregation Service**| `8013` | `http://localhost:8013` | Redis |

---

## 3. Database Migrations

- Shared core schema migrations are located in `database/sg_db/`.
- Individual services maintain their specific schemas and alembic migration versions:
  - `auth_service/alembic`
  - `portfolio_management_service/migrations`
  - `regime_detection_service/app/db/migrations`
  - `signal_aggregation_service/app/db/migrations`

---

## 4. Process Control & Health Monitoring

Use the unified PowerShell management CLI at the repo root:
```powershell
# Start all components
.\sg.ps1 start

# Check operational health
.\sg.ps1 health

# Check active ports
.\sg.ps1 status

# Stop all components
.\sg.ps1 stop
```
