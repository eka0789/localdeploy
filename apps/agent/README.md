# LocalDeploy Agent

Runs on a **remote Docker host** so your LocalDeploy dashboard can deploy
applications there — without opening any inbound port on the remote machine
(the agent dials out to the API).

## Setup

On the remote host (Linux/WSL2, needs Docker Engine + Python 3.11+):

```bash
pip install docker requests psutil
# copy agent.py (or git clone the repo)
export LOCALDEPLOY_API_URL="http://<your-localdeploy-host>:8000"
export LOCALDEPLOY_SERVER_TOKEN="lds_..."   # Dashboard → Settings → Servers → Add server
python agent.py
```

Run it under systemd/tmux for persistence:

```ini
# /etc/systemd/system/localdeploy-agent.service
[Unit]
Description=LocalDeploy Agent
After=network.target docker.service

[Service]
Environment=LOCALDEPLOY_API_URL=http://your-host:8000
Environment=LOCALDEPLOY_SERVER_TOKEN=lds_...
ExecStart=/usr/bin/python3 /opt/localdeploy/agent.py
Restart=always

[Install]
WantedBy=multi-user.target
```

## What it can do

| Command | Behaviour |
|---|---|
| `deploy` | Clone repo → detect runtime → buildpack/Dockerfile build → run container(s) with Traefik labels → health check → report logs + result back |
| `container_action` | start / stop / restart the app's containers |

The agent auto-boots a Traefik container (`localdeploy-traefik`) on first
deployment so domains route on the remote host too. Build logs stream back to
the dashboard in real time and appear in the same deployment log view.

## Security notes

- The agent token (`lds_…`) is created in the dashboard, stored hashed, and
  can be regenerated/revoked at any time.
- Deployment payloads include decrypted environment variables over the
  API connection — always use HTTPS or a trusted/private network between the
  API and agents.
- The agent never exposes its Docker socket to the network.
