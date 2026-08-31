# SG Trading Platform — Operations Runbook (Native Windows)

> **Audience:** Platform Operator / Developer running natively on Windows.

---

## 1. Daily Operations

### Starting the Platform
```powershell
.\sg.ps1 start
```
This launches:
1. WSL2 Redis service check/start (`service redis-server start`)
2. MLflow tracking server on `http://localhost:5000`
3. 13 FastAPI backend microservices (ports 8001–8013)
4. Next.js Dashboard on `http://localhost:3000`

### Checking Platform Health
```powershell
.\sg.ps1 health
```
Runs `scripts/health_check.py` and returns latencies and HTTP status codes across all ports.

### Viewing Active Listening Ports
```powershell
.\sg.ps1 status
```

### Stopping the Platform
```powershell
.\sg.ps1 stop
# OR
stop_all.bat
```

---

## 2. Interactive CLI Shells

### PostgreSQL Shell (Native Windows)
```powershell
.\sg.ps1 db
```
Connects `psql` to `localhost:5432` database `sg_db` as user `sg_user`.

### Redis Shell (WSL2)
```powershell
.\sg.ps1 redis
```
Connects `redis-cli` to `localhost:6379`.

---

## 3. Backups

```powershell
.\sg.ps1 backup
```
Executes `scripts/backup.ps1` which:
1. Generates a PostgreSQL SQL dump file using `pg_dump`
2. Triggers an asynchronous Redis snapshot (`bgsave`) in WSL2
3. Saves backups to `backups/YYYYMMDD_HHMMSS/`

---

## 4. Troubleshooting & FAQ

### Port Already in Use (e.g. 8001, 8002...)
Run:
```powershell
.\sg.ps1 stop
```
Or force kill the specific port via PowerShell:
```powershell
Get-NetTCPConnection -LocalPort 8001 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

### Redis Not Reachable on `localhost:6379`
1. Open WSL2: `wsl`
2. Ensure `bind 0.0.0.0` is present in `/etc/redis/redis.conf`
3. Restart Redis: `sudo service redis-server restart`
4. Exit WSL and verify from Windows:
   ```powershell
   .\.venv\Scripts\python.exe -c "import redis; print(redis.Redis().ping())"
   ```

### PostgreSQL Connection Refused on `localhost:5432`
1. Ensure the PostgreSQL Windows Service is running:
   ```powershell
   Get-Service postgresql* | Start-Service
   ```
2. Verify connection:
   ```powershell
   & "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U sg_user -d sg_db -c "SELECT 1;"
   ```
