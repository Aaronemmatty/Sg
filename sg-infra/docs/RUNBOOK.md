# SG Trading Platform — Operations Runbook

> **Audience:** You (the owner). Written for someone running this alone on a laptop.
> **Last updated:** See git history.

---

## Table of Contents

1. [First-Time Setup](#1-first-time-setup)
2. [Daily Operations](#2-daily-operations)
3. [Deploying Changes](#3-deploying-changes)
4. [GitHub + Self-Hosted Runner Setup](#4-github--self-hosted-runner-setup)
5. [Rollback Procedures](#5-rollback-procedures)
6. [Disaster Recovery](#6-disaster-recovery)
7. [Kite Token Refresh (Daily)](#7-kite-token-refresh-daily)
8. [Upgrading to k3s](#8-upgrading-to-k3s)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. First-Time Setup

### Prerequisites

```bash
# Install Docker Desktop (Mac/Windows) or Docker Engine (Linux)
# https://docs.docker.com/get-docker/

# Verify
docker --version          # Docker 25+
docker compose version    # v2.24+
python3 --version         # 3.12+
git --version
```

### Clone and configure

```bash
# Clone your private repo (after you've pushed to GitHub)
git clone git@github.com:YOUR_USERNAME/sg-trading.git
cd sg-trading/sg-infra

# Make scripts executable
chmod +x sg scripts/*.sh

# Generate all secrets (JWT keypair + random passwords)
pip install cryptography
python3 scripts/generate_secrets.py --patch-env

# Edit .env and add your Kite + Anthropic credentials
nano .env
# Fill in:
#   KITE_API_KEY=
#   KITE_API_SECRET=
#   KITE_ACCESS_TOKEN=
#   ANTHROPIC_API_KEY=
```

### Start the platform

```bash
# First time — build all images (takes 5-10 minutes)
./sg build

# Start everything
./sg up

# Verify all 13 services are healthy
./sg health
```

**Expected output:**
```
  Infrastructure
    ● Postgres
    ● Redis

  Platform Services
    ● Auth Service              42ms
    ● Market Data               38ms
    ● Broker Service            45ms
    ... (all green)

  All services healthy
```

**Access points:**
- Dashboard: http://localhost
- Grafana:   http://localhost/grafana  (admin / your GRAFANA_PASSWORD)
- MLflow:    http://localhost:5000

---

## 2. Daily Operations

### Start your trading day

```bash
# 1. Start platform (if not already running)
./sg up

# 2. Refresh Kite access token (expires daily)
bash scripts/refresh_kite_token.sh

# 3. Check health
./sg health

# 4. Watch live logs
./sg logs market_data_service
```

### Useful commands

```bash
./sg ps                          # container status + uptime
./sg logs strategy_service       # tail one service
./sg logs                        # tail all (noisy)
./sg health --watch              # continuous health monitor
./sg shell ml_platform_service   # open shell inside container
./sg db                          # PostgreSQL console
./sg redis                       # Redis CLI
```

### End of day

```bash
# Run backup before stopping (optional — backup also runs automatically at 2AM)
./sg backup

# Stop platform (data is preserved in Docker volumes)
./sg down
```

---

## 3. Deploying Changes

### Automatic (recommended) — push to GitHub

```bash
# Make your changes
nano auth_service/app/main.py

# Commit and push
git add -A
git commit -m "fix: rate limit on login endpoint"
git push origin main

# GitHub Actions automatically:
#   1. Runs tests for changed services
#   2. Builds Docker images on your laptop (self-hosted runner)
#   3. Blue-green deploys with health checks
#   4. Rolls back automatically if health checks fail
```

### Manual deploy — single service

```bash
# Deploy only what changed (faster)
./sg deploy auth_service

# Deploy all
./sg deploy
```

### Check deployment status

```bash
./sg status
# Output:
#   Live slot:     green (project: sg_green)
#   Standby slot:  blue  (project: sg_blue)
```

---

## 4. GitHub + Self-Hosted Runner Setup

The self-hosted runner is what makes GitHub Actions deploy **to your laptop** instead of a cloud server.

### Step 1: Create GitHub repository

```
1. Go to https://github.com/new
2. Name: sg-trading (Private)
3. Do NOT initialize with README (you have existing code)
4. Click "Create repository"
```

### Step 2: Push code to GitHub

```bash
cd /path/to/sg-trading
git init
git add -A
git commit -m "initial: SG Trading Platform"
git remote add origin git@github.com:YOUR_USERNAME/sg-trading.git
git push -u origin main
```

### Step 3: Install self-hosted runner on your laptop

```
1. Go to: https://github.com/YOUR_USERNAME/sg-trading/settings/actions/runners
2. Click "New self-hosted runner"
3. Select: macOS or Linux (match your laptop)
4. Follow the exact commands GitHub shows (they include a unique token)
```

Example (Linux):
```bash
mkdir -p ~/actions-runner && cd ~/actions-runner
curl -o actions-runner-linux-x64.tar.gz -L \
  https://github.com/actions/runner/releases/download/v2.321.0/actions-runner-linux-x64-2.321.0.tar.gz
tar xzf ./actions-runner-linux-x64.tar.gz
./config.sh --url https://github.com/YOUR_USERNAME/sg-trading --token <YOUR_TOKEN>
./run.sh  # or: sudo ./svc.sh install && sudo ./svc.sh start
```

### Step 4: Add GitHub Secrets

```
Go to: https://github.com/YOUR_USERNAME/sg-trading/settings/secrets/actions
Add these secrets (copy values from your .env):
```

| Secret Name | Value from .env |
|-------------|-----------------|
| `POSTGRES_PASSWORD` | your POSTGRES_PASSWORD |
| `REDIS_PASSWORD` | your REDIS_PASSWORD |
| `JWT_PRIVATE_KEY` | your JWT_PRIVATE_KEY |
| `JWT_PUBLIC_KEY` | your JWT_PUBLIC_KEY |
| `SESSION_SECRET` | your SESSION_SECRET |
| `KITE_API_KEY` | your KITE_API_KEY |
| `KITE_API_SECRET` | your KITE_API_SECRET |
| `ANTHROPIC_API_KEY` | your ANTHROPIC_API_KEY |
| `GRAFANA_PASSWORD` | your GRAFANA_PASSWORD |

### Step 5: Copy workflow files

```bash
# Copy GitHub Actions workflows into your repo root
cp -r sg-infra/github-actions/.github .github
git add .github
git commit -m "ci: add GitHub Actions pipelines"
git push
```

**After this, every `git push` to `main` automatically tests + deploys.**

---

## 5. Rollback Procedures

### Immediate rollback (within 60 seconds of deploy)

```bash
./sg deploy --rollback
# Switches nginx back to previous slot instantly
# Takes < 5 seconds
```

### Rollback to specific version

```bash
# Find the version you want
git log --oneline

# Check out that commit
git checkout <SHA>

# Deploy that version
./sg deploy

# Return to latest
git checkout main
```

### Database rollback

Only needed if a migration broke something:

```bash
# List available backups
ls -lah backups/

# Restore from a specific backup
./sg backup --restore backups/2025-01-15_020000
# This will prompt "Type YES to confirm"
```

---

## 6. Disaster Recovery

### Scenario A: Docker volumes corrupted

```bash
# Stop platform
./sg down

# Restore from latest backup
LATEST=$(ls -td backups/*/ | head -1)
./sg backup --restore "$LATEST"

# Restart
./sg up
```

### Scenario B: Laptop died / fresh machine

```bash
# 1. Install Docker
# 2. Clone repo
git clone git@github.com:YOUR_USERNAME/sg-trading.git
cd sg-trading/sg-infra

# 3. Restore secrets
# Copy your .env file from secure backup (password manager / encrypted drive)
# OR regenerate secrets and lose session state (users must re-login)

# 4. Start platform (fresh DB)
./sg build
./sg up

# 5. Restore data from backup (if you have one)
# Copy backup directory from your backup drive
./sg backup --restore /path/to/backup/2025-01-15_020000
```

### Scenario C: Single service crashed and won't restart

```bash
# Check logs
./sg logs risk_engine_service

# Force restart
docker compose -p sg_blue restart risk_engine_service

# If still failing — rebuild just that service
./sg deploy risk_engine_service

# If still failing — check for DB migration issues
./sg db
# In psql: check recent migrations, look for schema errors
```

### Backup schedule

| Type | When | Location | Retention |
|------|------|----------|-----------|
| Automatic daily | 2:00 AM | `backups/` | 7 days |
| Manual | `./sg backup` | `backups/` | Manual cleanup |

**Keep an encrypted copy of at least one backup on an external drive or cloud storage.**

---

## 7. Kite Token Refresh (Daily)

Zerodha Kite access tokens expire at 6 AM every day. You must refresh before trading.

```bash
bash scripts/refresh_kite_token.sh
```

**To automate this** (add to crontab):
```bash
crontab -e
# Add:
0 6 * * * /path/to/sg-trading/sg-infra/scripts/refresh_kite_token.sh >> /tmp/kite_token.log 2>&1
```

The script:
1. Uses your `KITE_API_KEY` + `KITE_API_SECRET` to get a new access token
2. Writes `KITE_ACCESS_TOKEN` into `.env`
3. Restarts `market_data_service` and `broker_service` to pick up the new token

---

## 8. Upgrading to k3s (Tier 2)

When you want auto-healing, better resource management, or to run on multiple machines:

```bash
# Install k3s (single command)
curl -sfL https://get.k3s.io | sh -

# Verify
kubectl get nodes

# Build images and import into k3s
./sg build
for svc in auth_service market_data_service broker_service strategy_service \
           regime_detection_service execution_orchestrator_service \
           risk_engine_service execution_engine_service portfolio_management_service \
           backtesting_engine ml_platform_service ai_analyst_service dashboard; do
  docker save "sg/${svc}:latest" | sudo k3s ctr images import -
done

# Create secrets
kubectl create secret generic platform-secrets \
  --from-env-file=.env \
  -n sg-trading

# Deploy
kubectl apply -k k8s/overlays/dev

# Check pods
kubectl get pods -n sg-trading
```

---

## 9. Troubleshooting

### Service won't start

```bash
./sg logs <service_name>   # check error message
./sg health                # see which services are down
```

**Common causes:**
- `DATABASE_URL` wrong → check `.env` postgres credentials
- Port conflict → `lsof -i :8001` to find what's using the port
- Image not built → `./sg build`

### Redis connection refused

```bash
docker exec sg_redis redis-cli -a "$REDIS_PASSWORD" ping
# Should return: PONG
# If not: docker restart sg_redis
```

### PostgreSQL out of connections

```bash
./sg db
# In psql:
SELECT count(*), state FROM pg_stat_activity GROUP BY state;
SELECT pg_terminate_backend(pid)
  FROM pg_stat_activity
  WHERE state = 'idle'
  AND query_start < now() - interval '10 minutes';
```

### ML training jobs stuck

```bash
./sg logs ml_platform_service | grep -i "job\|error\|training"
# Check MLflow at http://localhost:5000 for run status
```

### Circuit breaker won't reset

```bash
# Via admin panel: http://localhost/admin → System Controls → Reset Circuit Breaker
# Or directly:
curl -X POST http://localhost:8007/api/v1/risk/circuit-breaker/reset \
  -H "Authorization: Bearer <your_token>"
```

### Logs too noisy — silence a service

```bash
# Temporarily stop a non-critical service
docker compose -p sg_blue stop backtesting_engine
# Restart when needed
docker compose -p sg_blue start backtesting_engine
```

---

## Quick Reference

```
./sg up              Start everything
./sg down            Stop (data safe)
./sg health          Check all 13 services
./sg deploy          Blue-green deploy all
./sg deploy <svc>    Deploy one service
./sg deploy --rollback   Instant rollback
./sg backup          Full backup
./sg logs <svc>      Tail service logs
./sg db              PostgreSQL shell
./sg status          Show blue/green state
```
