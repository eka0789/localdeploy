# Public networking

Your apps only become reachable from the internet through one of the two modes below. LocalDeploy **never** assumes a machine is publicly accessible by itself.

## Mode A — Public IP + port forwarding

Requirements:

1. A public IP (static preferred; use a DDNS service otherwise).
2. Router forwards **TCP 80 and 443** to your server's LAN IP.
3. DNS `A`/`AAAA` records for your domains → your public IP (the Domains page shows ready-made instructions per domain, wildcard supported).
4. Set `ACME_EMAIL` in `.env` so Traefik can register with Let's Encrypt.

Then: `docker compose up -d` — HTTP is redirected to HTTPS globally, certificates renew automatically.

> ⚠ **Never** forward Docker's port (2375/2376), database ports, or the API's raw port publicly. The stack is designed so only 80/443 are exposed.

## Mode B — Cloudflare Tunnel (no open ports)

Best for home connections behind CGNAT, or when you don't want to open ports at all.

1. Add your domain to Cloudflare.
2. Cloudflare Dashboard → **Zero Trust → Networks → Tunnels → Create tunnel** → copy the **token**.
3. LocalDeploy → **Networking → Add tunnel** → paste the token → **Start**.
4. In Cloudflare, map public hostnames to `http://<app-container-name>:<port>` — app containers are resolvable by name on the shared `localdeploy-network`.
5. Set the networking mode to `cloudflare-tunnel` on the Networking page.

Notes:

- The tunnel container joins `localdeploy-network`, so it can reach every deployed app directly; nothing needs to be published on the host.
- SSL terminates at Cloudflare's edge (choose *Full* or *Full (strict)* once origin certs are in place).
- Connection status is monitored from the cloudflared logs (`Registered tunnel connection`); auto-reconnect is built into cloudflared via its restart policy.

## SSL

- Traefik requests and renews Let's Encrypt certificates via HTTP-01 automatically for every domain with `ssl_enabled`.
- Mount Traefik's `acme.json` into the API container (see the commented line in `docker-compose.yml`) and LocalDeploy will show issuer + expiry per domain, flagging anything expiring within 14 days.
- Local development without a public domain: keep `ssl_enabled` off per domain and use plain HTTP.
