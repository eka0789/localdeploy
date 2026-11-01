# LocalDeploy

**Self-hosted deployment & application hosting platform** — turn your own computer, mini PC, or Linux server into a private cloud platform in the spirit of Dokploy, Coolify, CapRover and Portainer.

```
┌────────────────────────────────────────────────────────────────────┐
│  Browser ──► Dashboard (Next.js)  ──►  API (FastAPI)               │
│                                          │                         │
│                        ┌─────────────────┼─────────────────┐       │
│                        ▼                 ▼                 ▼       │
│               Deployment Worker    Docker Engine      PostgreSQL   │
│               (git→build→health    (containers,       (platform    │
│                check→switch)        images, vols)      DB + Redis) │
│                        │                                           │
│                        ▼                                           │
│              Traefik (domains + Let's Encrypt SSL)                 │
│                        │                                           │
│              App containers / Compose projects                     │
│        (public via public IP + port 80/443, or Cloudflare Tunnel)  │
└────────────────────────────────────────────────────────────────────┘
```

## What it does

- **Deploy anything** — Git repositories (auto-detected runtimes: Next.js, Node, React, Vue, Nuxt, Angular, NestJS, Express, Laravel/PHP, FastAPI, Django, Flask, Go, Java/Spring, Ruby, static sites), custom Dockerfiles, Docker Compose files, prebuilt images, or uploaded source archives.
- **Real Docker integration** — images are built with immutable `localdeploy/<app>:<deploy-id>` tags, health-checked, and only then switched (previous container stays until the new one passes; instant rollback to any previous image).
- **Domains & SSL** — attach domains to apps, Traefik routes them dynamically via labels, Let's Encrypt certificates are managed automatically with expiry monitoring.
- **Public networking, two ways** — Public IP + port forwarding, or Cloudflare Tunnel (no open ports, works behind CGNAT).
- **Managed databases** — PostgreSQL / MySQL / MariaDB / Redis / MongoDB with persistent volumes, health checks, connection info, and one-click backup/restore. Ports are never public by default.
- **Monitoring** — live CPU/RAM/disk/network from the host, per-container stats, 48h history, Prometheus endpoint at `/metrics`.
- **Logs** — real-time WebSocket streaming for deployments and container logs.
- **Security** — Argon2id password hashing, server-side sessions, CSRF double-submit, login rate limiting, RBAC (admin/viewer), encrypted secrets at rest (Fernet), audit logging, Docker socket treated as privileged access.

## Repository layout

```
localdeploy/
├── apps/
│   ├── api/               # FastAPI backend (deployment engine, Docker, domains, …)
│   └── dashboard/         # Next.js dashboard (App Router, Tailwind v4, TanStack Query)
├── infrastructure/
│   ├── docker/            # Dockerfiles (api, dashboard)
│   ├── traefik/           # Traefik static + dynamic config (ACME, redirects)
│   ├── cloudflare/        # tunnel notes
│   └── monitoring/        # prometheus scrape example
├── scripts/               # install.sh (Linux one-command installer)
├── docs/                  # ARCHITECTURE, NETWORKING, ENVIRONMENT, WSL2, TROUBLESHOOTING
├── docker-compose.yml     # full production stack
└── .env.example
```

## Quick start

### Linux (recommended production host)

```bash
git clone <this-repo> && cd localdeploy
cp .env.example .env        # then edit: SECRET_KEY, POSTGRES password, ACME_EMAIL
docker compose up -d --build
```

Or the one-liner installer (installs Docker if missing):

```bash
./scripts/install.sh
```

### Windows / macOS (development via Docker Desktop or WSL2)

See [docs/WSL2.md](docs/WSL2.md). TL;DR: install Docker Desktop, run under WSL2, then the same `docker compose up -d --build`.

### Local development (without Docker for the platform itself)

```bash
# API — Python 3.11+
cd apps/api
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m alembic upgrade head
uvicorn app.main:app --port 8000 --reload

# Dashboard — Node 18+
cd apps/dashboard
npm install
echo 'NEXT_PUBLIC_API_URL=http://localhost:8000' > .env.local
npm run dev
```

Log in at `http://localhost:3000` with the bootstrap admin (`admin` / `localdeploy123` — **change it immediately**, see `.env.example`).

## First deployment walkthrough

1. **Overview →** check Docker shows *connected*.
2. **Applications → New application** → choose *Git repo* → `https://github.com/user/repo` → set the container port.
3. Press **Deploy** — the engine clones, detects the runtime, generates a Dockerfile if none exists, builds, starts, health-checks, then switches traffic. Watch the live build log.
4. **Domains tab** (or Domains page) → add `app.example.com` → follow the DNS instructions.
5. Point DNS (A record or Cloudflare Tunnel) at the server → HTTPS is issued automatically when Traefik runs with `ACME_EMAIL` set.

## Configuration

All environment variables (prefix `LOCALDEPLOY_`) are documented in [.env.example](.env.example). Key ones:

| Variable | Purpose |
|---|---|
| `LOCALDEPLOY_SECRET_KEY` | Signs sessions + derives the Fernet key that encrypts stored secrets. **Set it in production.** |
| `LOCALDEPLOY_DATABASE_URL` | `sqlite:///…` (dev) or `postgresql+psycopg://…` (production). |
| `LOCALDEPLOY_DOCKER_HOST` | Docker endpoint; empty = local socket / named pipe. |
| `LOCALDEPLOY_DEPLOY_NETWORK` | Docker network shared by Traefik and deployed apps. |

See [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md) for the full reference.

## Security model

- The **Docker socket is mounted only into the API container** and is never proxied to browsers or deployed apps. Deployed containers cannot see the platform database.
- No arbitrary shell endpoints exist. The API runs only `git` and `docker` with argument lists (never `shell=True`); build commands execute *inside* build containers, not on the host.
- Database instances are reachable only on the internal Docker network; optional loopback publishing for local tooling.
- All state-changing API calls require a session cookie **and** a CSRF token; logins are rate-limited; every mutation lands in the audit log.

## Tests

```bash
cd apps/api && pytest          # 48 tests: runtime detection, buildpacks, security, API flows
cd apps/dashboard && npm run build   # type-checked production build
```

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — system design and module map
- [docs/NETWORKING.md](docs/NETWORKING.md) — public IP vs Cloudflare Tunnel, SSL
- [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md) — configuration reference
- [docs/WSL2.md](docs/WSL2.md) — Windows development setup
- [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) — common issues

## Definition of done (verified)

1. ✅ Install locally → dashboard reachable
2. ✅ Docker Engine connects (graceful offline status when absent)
3. ✅ Create projects & applications
4. ✅ Git-based deploys with runtime detection + buildpacks
5. ✅ Laravel / Next.js / FastAPI buildpacks generate working Dockerfiles
6. ✅ Per-app domains routed by Traefik
7. ✅ Internet access via public IP mode or Cloudflare Tunnel
8. ✅ HTTPS via Let's Encrypt with expiry monitoring
9. ✅ CPU/RAM/disk monitoring with history + Prometheus
10. ✅ Real-time deployment & container logs (WebSocket)
11. ✅ Restart / redeploy / rollback / cancel
12. ✅ Backup & restore (databases and volumes)
