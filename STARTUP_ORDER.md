# Startup Order & Architecture — SG Trading Platform (Native Windows)

This document describes the process startup sequence, inter-service dependencies, and health verification for native Windows operation.

---

## 1. Dependency Graph & Startup Order

```
[Level 0: Core Infrastructure]
   PostgreSQL (Windows Service :5432)
   Redis (WSL2 Service :6379)
   MLflow Tracking Server (:5000)
       │
       ▼
[Level 1: Authentication & Identity]
   Auth Service (:8001)  <-- waits on PostgreSQL + Redis
       │
       ├──────────────────────────────────────────────┐
       ▼                                              ▼
[Level 2: Data & Market Ingestion]         [Level 2: Frontend]
   Market Data Service (:8002)                Next.js Dashboard (:3000)
   Broker Service (:8003)
       │
       ▼
[Level 3: Intelligence & Signal Generation]
   Regime Detection Service (:8005)
   Signal Aggregation Service (:8013)
   Strategy Service (:8004)
   ML Platform Service (:8011)  <-- connects to MLflow (:5000)
   AI Analyst Service (:8012)
       │
       ▼
[Level 4: Execution & Risk Management]
   Risk Engine Service (:8007)
   Execution Orchestrator Service (:8006)
   Execution Engine Service (:8008)
   Portfolio Management Service (:8009)
   Backtesting Engine Service (:8010)
```

---

## 2. Boot Times & Port Allocations

| Service | Port | Boot Time | Health Endpoint |
|---|:---:|:---:|---|
| **PostgreSQL** | `5432` | Instant (Service) | TCP `localhost:5432` |
| **Redis** | `6379` | Instant (WSL2) | TCP `localhost:6379` |
| **MLflow Server** | `5000` | 2–5s | `http://localhost:5000/health` |
| **Auth Service** | `8001` | 3–6s | `http://localhost:8001/health` |
| **Market Data Service** | `8002` | 2–4s | `http://localhost:8002/health` |
| **Broker Service** | `8003` | 2–4s | `http://localhost:8003/health` |
| **Regime Detection** | `8005` | 4–8s (loads models) | `http://localhost:8005/health` |
| **Signal Aggregation** | `8013` | 2–4s | `http://localhost:8013/health` |
| **Strategy Service** | `8004` | 3–6s | `http://localhost:8004/health` |
| **ML Platform Service** | `8011` | 5–10s | `http://localhost:8011/health` |
| **AI Analyst Service** | `8012` | 3–5s | `http://localhost:8012/health` |
| **Risk Engine Service** | `8007` | 2–4s | `http://localhost:8007/health` |
| **Execution Orchestrator** | `8006` | 3–5s | `http://localhost:8006/health` |
| **Execution Engine** | `8008` | 2–4s | `http://localhost:8008/health` |
| **Portfolio Management**| `8009` | 3–5s | `http://localhost:8009/health` |
| **Backtesting Engine** | `8010` | 4–8s | `http://localhost:8010/health` |
| **Next.js Dashboard** | `3000` | 3–6s | `http://localhost:3000` |

---

## 3. Controlling the Stack

### Launching Stack:
```powershell
.\sg.ps1 start
# OR
start_all.bat
```

### Checking Status & Health:
```powershell
.\sg.ps1 health
```

### Stopping Stack:
```powershell
.\sg.ps1 stop
# OR
stop_all.bat
```
