# Environment configuration reference

All variables use the `LOCALDEPLOY_` prefix and can live in a `.env` file at the repository root. Copy `.env.example` as a starting point.

## Core

| Variable | Default | Description |
|---|---|---|
| `LOCALDEPLOY_SECRET_KEY` | *(generated to `data/.secret_key` in dev)* | Signs sessions and derives the Fernet key encrypting all stored secrets (git tokens, DB passwords, tunnel tokens). Rotating it invalidates existing encrypted values and sessions. **Must be set in production.** |
| `LOCALDEPLOY_ENVIRONMENT` | `development` | `production` enables `Secure` cookies. |
| `LOCALDEPLOY_DATABASE_URL` | `sqlite:///./data/localdeploy.db` | Production: `postgresql+psycopg://user:pass@postgres:5432/localdeploy`. |
| `LOCALDEPLOY_CORS_ORIGINS` | `["http://localhost:3000"]` | JSON list of dashboard origins allowed to call the API with credentials. |

## Server

| Variable | Default | Description |
|---|---|---|
| `LOCALDEPLOY_HOST` / `LOCALDEPLOY_PORT` | `0.0.0.0` / `8000` | API bind address. |
| `LOCALDEPLOY_PUBLIC_BASE_URL` | `http://localhost:8000` | Used when generating webhook URLs shown in the UI. |
| `LOCALDEPLOY_SESSION_TTL_MINUTES` | `10080` (7 days) | Session lifetime. |

## Docker & deployment

| Variable | Default | Description |
|---|---|---|
| `LOCALDEPLOY_DOCKER_HOST` | *(empty = local)* | e.g. `unix:///var/run/docker.sock`, `npipe:////./pipe/docker_engine`, `tcp://host:2375`. |
| `LOCALDEPLOY_DEPLOY_NETWORK` | `localdeploy-network` | Docker network shared by Traefik, apps, databases and tunnels. |
| `LOCALDEPLOY_IMAGE_PREFIX` | `localdeploy` | Built images are tagged `<prefix>/<slug>:<deploy-id>`. |
| `LOCALDEPLOY_DEPLOY_TIMEOUT_SECONDS` | `1800` | Hard cap for one deployment. |
| `LOCALDEPLOY_HEALTHCHECK_TIMEOUT_SECONDS` | `120` | HTTP health check window before failing a deploy. |
| `LOCALDEPLOY_WORKSPACE_DIR` | `./data/workspace` | Git clones, uploads, generated Dockerfiles. |
| `LOCALDEPLOY_BACKUPS_DIR` | `./data/backups` | Backup files. |

## Traefik / SSL

| Variable | Default |
|---|---|
| `LOCALDEPLOY_TRAEFIK_ENTRYPOINT_HTTP` | `http` |
| `LOCALDEPLOY_TRAEFIK_ENTRYPOINT_HTTPS` | `https` |
| `LOCALDEPLOY_TRAEFIK_CERT_RESOLVER` | `letsencrypt` |
| `LOCALDEPLOY_ACME_JSON_PATH` | *(empty)* — set to Traefik's mounted `acme.json` to enable SSL expiry monitoring. |

## Bootstrap admin (first run only)

| Variable | Default |
|---|---|
| `LOCALDEPLOY_FIRST_ADMIN_USERNAME` | `admin` |
| `LOCALDEPLOY_FIRST_ADMIN_EMAIL` | `admin@localdeploy.local` |
| `LOCALDEPLOY_FIRST_ADMIN_PASSWORD` | `localdeploy123` |

> The bootstrap user is flagged `must_change_password`; the dashboard nags until the password is changed. Only created when the users table is empty.

## Metrics

| Variable | Default |
|---|---|
| `LOCALDEPLOY_METRICS_SAMPLE_SECONDS` | `15` |
| `LOCALDEPLOY_METRICS_RETENTION_HOURS` | `48` |

## Docker Compose (production) extras

| Variable | Description |
|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | Platform database credentials (also referenced by the API service). |
| `LOCALDEPLOY_HOSTNAME` | Domain that routes to the dashboard through Traefik. |
| `ACME_EMAIL` | Let's Encrypt account email (Traefik). |
| `NEXT_PUBLIC_API_URL` | Baked into the dashboard build; the URL browsers use to reach the API. |
