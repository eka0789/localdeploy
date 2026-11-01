@echo off
REM ============================================================
REM LocalDeploy - start everything after a Windows reboot
REM  1. WSL2 VM + Docker daemon (kept alive by a keeper process)
REM  2. LocalDeploy API  (http://localhost:8000)
REM  3. LocalDeploy Dashboard (http://localhost:3000)
REM ============================================================

echo [LocalDeploy] Starting WSL2 + Docker daemon...
start "LocalDeploy WSL keeper" /min wsl.exe -d Ubuntu -u root -- nohup sleep infinity
timeout /t 20 /nobreak >nul

echo [LocalDeploy] Starting API on :8000 ...
cd /d C:\Users\LENOVO\localdeploy\apps\api
set LOCALDEPLOY_DOCKER_HOST=tcp://127.0.0.1:2375
set PATH=%PATH%;C:\Users\LENOVO\localdeploy\tools\docker-cli\docker
start "LocalDeploy API" /min cmd /c ".venv\Scripts\python -m uvicorn app.main:app --port 8000 > ..\..\api.log 2>&1"

echo [LocalDeploy] Starting Dashboard on :3000 ...
cd /d C:\Users\LENOVO\localdeploy\apps\dashboard
start "LocalDeploy Dashboard" /min cmd /c "npm run start > ..\..\dashboard.log 2>&1"

echo [LocalDeploy] Done. Dashboard: http://localhost:3000  API docs: http://localhost:8000/api/docs
