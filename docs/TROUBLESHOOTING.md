# Troubleshooting

## Docker shows *offline* in the dashboard

- Is the engine running? `docker info` on the host.
- API container can't see the socket? Ensure `/var/run/docker.sock` is mounted (production compose does this) and the socket has correct permissions (`sudo chmod 666 /var/run/docker.sock` or run the API with `group_add: ["999"]` matching the docker GID).
- Windows without WSL2: set `LOCALDEPLOY_DOCKER_HOST=npipe:////./pipe/docker_engine`.
- The platform keeps working read-only when Docker is offline — deployments will fail with a clear error instead of hanging.

## Deployment fails at `git clone`

- Public repo? Check the URL in a browser. Private repo? Set **Git username** (`oauth2` or `x-token-auth` for GitLab) + **token** as the password; it's stored encrypted and redacted from all logs.
- Corporate proxy: configure git on the host; the engine shells out to the system git.
- Timeouts: raise `LOCALDEPLOY_GIT_CLONE_TIMEOUT_SECONDS` for monorepos.

## Build fails, but it works on my machine

- Read the build log (Deployments tab shows every line). The generated Dockerfile is printed into the log — verify the detected runtime is correct.
- Set **install/build/start command overrides** in the application Settings tab.
- Add a real `Dockerfile` to the repo for full control; it always takes precedence over the buildpack.
- Health check timeout (container builds fine, deploy fails at the end): your app must listen on `0.0.0.0` (not `127.0.0.1`) and on the configured container port; adjust *Health check path* if `/` 404s.

## Domain doesn't resolve / SSL pending

- The Domains page → **Verify** checks public DNS resolution. DNS can take up to 48h.
- SSL stays `pending` while the domain doesn't point at the server — Let's Encrypt HTTP-01 requires a reachable port 80.
- Rate-limited by Let's Encrypt while testing? Switch the Traefik CA to the staging URL (comment in `infrastructure/traefik/traefik.yml`).

## Database instance shows `error`

- Port already published? Each instance's optional loopback port must be unique on the host.
- Read `last_error` on the instance row; provisioning failures (e.g. image pull blocked) are recorded there.
- First start can take ~30-60s for MySQL/MongoDB init — the status flips to `running` automatically after the health check passes.

## Login gives 429

- Rate limit: 10 attempts / 5 min per IP+username (in-memory). Wait or restart the API.

## CSRF errors (403) from the dashboard

- The dashboard fetches `/api/auth/csrf` automatically. If you're scripting the API: `GET /api/auth/csrf` first, then send the token from the response (it's also in the `ld_csrf` cookie) as the `X-CSRF-Token` header on every mutating request, with the session cookie.

## Backups fail with "helper container" errors

- Backups run one-off containers; the engine image must be pullable. Ensure `docker pull alpine:3.20` works (volume backups) and the database image exists locally.

## Reset everything (dev)

```bash
docker compose down -v          # production stack: destroys volumes too!
rm -rf apps/api/data            # dev SQLite + workspace + secrets key
```
