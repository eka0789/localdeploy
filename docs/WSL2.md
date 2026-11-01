# Windows development with WSL2 + Docker

LocalDeploy targets Linux in production. On Windows, develop inside WSL2 so the Docker paths, health checks and Traefik networking behave exactly like a real server.

## 1. Install WSL2

```powershell
wsl --install            # installs Ubuntu by default
# reboot, then open Ubuntu and create your user
```

## 2. Install Docker inside WSL2 (recommended) or Docker Desktop

**Option A — Docker Engine inside WSL2 (recommended, lighter):**

```bash
# inside WSL2 Ubuntu
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker
docker run --rm hello-world
```

**Option B — Docker Desktop:** install it, enable *WSL2 integration* for your distro, and keep the engine running.

## 3. Clone and run the stack

```bash
cd ~
git clone <this-repo> localdeploy && cd localdeploy
cp .env.example .env
docker compose up -d --build
```

## 4. Or run in dev mode (no platform containers)

```bash
# terminal 1 — API (inside WSL2 so Docker is reachable)
cd apps/api
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m alembic upgrade head
uvicorn app.main:app --port 8000 --reload

# terminal 2 — dashboard
cd apps/dashboard
npm install
echo 'NEXT_PUBLIC_API_URL=http://localhost:8000' > .env.local
npm run dev
```

## Notes & gotchas

- **Docker Desktop on Windows + native Python (no WSL2):** the API can reach Docker via the named pipe using `LOCALDEPLOY_DOCKER_HOST=npipe:////./pipe/docker_engine`. This works for testing but the deployment engine (git clones, shell semantics) is happiest under WSL2/Linux.
- **File performance:** keep the repository **inside** the WSL2 filesystem (`~/localdeploy`), not `/mnt/c/...` — builds are 5-10× faster.
- **Ports:** Windows forwards `localhost:3000`/`localhost:8000` to WSL2 automatically.
- **Health checks from the API to containers** use a random loopback port; under WSL2 the API runs on the same network namespace as Docker, so this works out of the box.
