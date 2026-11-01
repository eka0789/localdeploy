# Architecture

## Modules

| Module | Location | Responsibility |
|---|---|---|
| Web Dashboard | `apps/dashboard` | Next.js App Router SPA. Talks to the API with cookie sessions + CSRF header. WebSocket clients for live logs. |
| Backend API | `apps/api/app/main.py` | FastAPI. All routes under `/api`, OpenAPI at `/api/docs`, Prometheus at `/metrics`. |
| Deployment Worker | `apps/api/app/services/worker.py` | In-process asyncio queue (concurrency 2). Heavy work runs in threads; HTTP requests never block on builds. |
| Deployment Engine | `apps/api/app/services/deployer.py` | The 15-step lifecycle: validate → source → detect → Dockerfile → build → network → container → health check → switch → cleanup. |
| Docker Engine | `apps/api/app/services/docker_client.py` | Single lazy client with ping, availability probing and graceful degradation. |
| Reverse Proxy Manager | `apps/api/app/services/traefik.py` | Generates Traefik router/service labels per domain (HTTP→HTTPS redirect, cert resolver). |
| Domain Management | `apps/api/app/api/routes/domains.py` | CRUD + DNS instructions + verification. Label changes are applied by recreating the running container (health-checked, no downtime if the new one is healthy). |
| SSL Management | `apps/api/app/services/ssl.py` | Parses Traefik `acme.json` (when mounted), tracks issuer + expiry per domain, flags `expiring` under 14 days. |
| Tunnel Manager | `apps/api/app/services/tunnel.py` | Runs/stops `cloudflared` containers, tracks edge registration from logs. |
| Database Provisioning | `apps/api/app/services/db_provisioner.py` | Managed containers for 5 engines with volumes, loopback-only optional publishing, exec-based health checks. |
| Backup/Restore | `apps/api/app/services/backups.py` | One-off helper containers run dumps/archives into the backups dir with SHA-256 checksums. |
| Monitoring | `apps/api/app/services/monitor.py` | psutil host snapshot + Docker stats sampling → `server_metrics` / `application_metrics` (48h retention). |
| Logging | `apps/api/app/services/log_hub.py` | Async pub/sub hub: `deploy:{id}`, `applogs:{app_id}`, `system`, `metrics` channels + system ring buffer. |
| Auth | `apps/api/app/core/security.py`, `app/api/deps.py` | Argon2id, DB-backed sessions (token stored hashed), double-submit CSRF, rate limiting, RBAC via role→permission keys. |

## Deployment lifecycle (deployer.py)

1. Mark deployment `running`, stream logs to WS + `deployment_logs`.
2. Acquire source: `git clone --depth 1` (credentials injected into URL, redacted from logs), uploaded archive extraction, or image pull.
3. Detect runtime from the file tree (`runtime_detect.py`) — no framework is hardcoded in the deployer; each runtime maps to a buildpack template (`buildpacks.py`) that emits a multi-stage Dockerfile. An existing project Dockerfile always wins.
4. Build with the low-level Docker API streaming output line-by-line (cancellation checked between chunks).
5. Rename the old container to `ld-<slug>-old-<deploy>` (traffic keeps flowing).
6. Start the new container on `localdeploy-network` with Traefik labels, decrypted env vars, resource limits and a random 127.0.0.1 health-check port.
7. Health check: HTTP probe until success or timeout; failure → remove new container, rename the old one back.
8. Success → remove old container, mark app `running`, record duration.

Rollback re-runs step 5-8 against a previous deployment's immutable image tag — no rebuild.

## Data model (19 tables)

`users, roles, permissions, role_permissions, user_sessions, audit_logs, projects, applications, application_domains, environment_variables, webhook_integrations, deployments, deployment_logs, backup_records, database_instances, storage_volumes, tunnel_connections, server_settings, server_metrics, application_metrics`

All primary keys are UUIDs. Timestamps are naive UTC. Soft delete for users, projects, applications, databases.

## Why these choices

- **Sync SQLAlchemy + thread offloading** rather than async ORM: the Docker SDK is synchronous; mixing one async path would complicate the hot deployment path for little gain. FastAPI runs blocking work in worker threads.
- **Traefik labels** rather than file-based dynamic config: deployments become atomic (labels ship with the container), and Traefik reacts automatically.
- **Immutable image tags per deployment** enable honest rollback and safe blue/green switching.
- **In-process worker** keeps the install to a single container; the queue + cooperative cancellation model matches real usage on a personal server. (A Redis-backed out-of-process worker is a drop-in upgrade path if heavier throughput is needed.)
