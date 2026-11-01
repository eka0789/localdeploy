#!/usr/bin/env python3
"""LocalDeploy Agent — runs on a remote Docker host and executes commands
dispatched by your LocalDeploy API.

The agent dials OUT to the API (no inbound ports needed on this machine):

    export LOCALDEPLOY_API_URL="http://your-localdeploy-host:8000"
    export LOCALDEPLOY_SERVER_TOKEN="lds_..."      # from Dashboard → Servers
    python agent.py

Requires: Python 3.11+, Docker Engine reachable locally, `docker` SDK
    pip install docker requests
(it intentionally has no other dependencies; buildpack templates are bundled)
"""
from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

import docker
import requests

API_URL = (os.environ.get("LOCALDEPLOY_API_URL") or "").rstrip("/")
TOKEN = os.environ.get("LOCALDEPLOY_SERVER_TOKEN") or ""
AGENT_VERSION = "1.0.0"
HEARTBEAT_SECONDS = 3
POLL_TIMEOUT = 25  # seconds the API may hold the hello request open (unused in v1 simple polling)
WORKSPACE = Path(os.environ.get("LOCALDEPLOY_AGENT_WORKSPACE", Path.home() / ".localdeploy-agent"))

SKIP_DIRS = {".git", "node_modules", "vendor", "__pycache__", ".next", "dist", "build", ".venv"}


def log(message: str) -> None:
    print(f"[agent] {message}", flush=True)


# ---------------------------------------------------------------------------
# API transport
# ---------------------------------------------------------------------------

def api_post(path: str, body: dict, timeout: int = 30) -> dict:
    response = requests.post(
        f"{API_URL}{path}", json=body,
        headers={"Authorization": f"Bearer {TOKEN}"}, timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def send_logs(deployment_id: str, lines: list[dict]) -> None:
    try:
        api_post("/api/agent/logs", {"deployment_id": deployment_id, "lines": lines}, timeout=15)
    except Exception as exc:
        log(f"failed to send logs: {exc}")


# ---------------------------------------------------------------------------
# stats + heartbeat loop
# ---------------------------------------------------------------------------

def collect_stats() -> dict:
    stats: dict = {"agent_version": AGENT_VERSION}
    try:
        import psutil  # optional

        stats["cpu_percent"] = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        stats["memory_used_mb"] = round((mem.total - mem.available) / 1024 / 1024, 1)
        stats["memory_total_mb"] = round(mem.total / 1024 / 1024, 1)
    except ImportError:
        stats["cpu_percent"] = 0
        stats["memory_used_mb"] = 0
        stats["memory_total_mb"] = 0
    client = docker.from_env()
    containers = client.containers.list(all=True)
    stats["container_count"] = len(containers)
    stats["running_count"] = len([c for c in containers if c.status == "running"])
    return stats


def container_action(payload: dict) -> dict:
    client = docker.from_env()
    slug = payload["slug"]
    action = payload["action"]
    acted = 0
    for index in range(1, 11):
        name = f"ld-{slug}" if index == 1 else f"ld-{slug}-r{index}"
        try:
            container = client.containers.get(name)
        except docker.errors.NotFound:
            if index > 1:
                break
            continue
        getattr(container, action if action != "restart" else "restart")(timeout=30) \
            if action in ("stop", "restart") else container.start()
        acted += 1
    return {"acted": acted}


# ---------------------------------------------------------------------------
# deployments (self-contained mini buildpack pipeline)
# ---------------------------------------------------------------------------

def build_dockerfile(payload: dict, workdir: Path) -> Path | None:
    """Return the Dockerfile path to build: project's own, or a generated one."""
    explicit = workdir / (payload.get("dockerfile_path") or "Dockerfile")
    runtime = detect_runtime(workdir)
    if explicit.exists() or runtime == "dockerfile":
        return explicit
    compose = workdir / (payload.get("docker_compose_path") or "docker-compose.yml")
    if runtime == "compose" or compose.exists():
        return compose  # handled by compose path in run_deployment
    generated = workdir / "Dockerfile"
    generated.write_text(generate_dockerfile(runtime, payload), encoding="utf-8")
    return generated


def detect_runtime(workdir: Path) -> str:
    files = [p.relative_to(workdir).as_posix() for p in workdir.rglob("*")
             if p.is_file() and not any(part in SKIP_DIRS for part in p.relative_to(workdir).parts)]
    names = {f.lower() for f in files}

    def read(path: str) -> str:
        try:
            return (workdir / path).read_text(encoding="utf-8", errors="replace")[:200_000]
        except OSError:
            return ""

    if any(n in names for n in ("docker-compose.yml", "docker-compose.yaml", "compose.yml")):
        return "compose"
    if "dockerfile" in names:
        return "dockerfile"
    if "composer.json" in names:
        return "laravel" if "laravel/framework" in read("composer.json") else "php"
    if "package.json" in names:
        pkg = read("package.json")
        if '"next"' in pkg:
            return "nextjs"
        if "@angular/core" in pkg:
            return "angular"
        if '"nuxt"' in pkg:
            return "nuxt"
        if "@nestjs/core" in pkg:
            return "nestjs"
        if '"react"' in pkg:
            return "react"
        if '"vue"' in pkg:
            return "vue"
        if "express" in pkg:
            return "express"
        return "node"
    if "go.mod" in names:
        return "go"
    if "pom.xml" in names or "build.gradle" in names:
        return "java"
    if "requirements.txt" in names or "pyproject.toml" in names or "manage.py" in names:
        if "django" in read("requirements.txt") or "manage.py" in names:
            return "django"
        if "fastapi" in read("requirements.txt"):
            return "fastapi"
        if "flask" in read("requirements.txt"):
            return "flask"
        return "python"
    if "gemfile" in names:
        return "ruby"
    if any(f.endswith(".html") for f in names):
        return "static"
    return "unknown"


def generate_dockerfile(runtime: str, payload: dict) -> str:
    port = payload.get("container_port", 80)
    if runtime in ("nextjs", "node", "express", "nestjs", "nodejs"):
        return f"""FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci || npm install
COPY . .
RUN npm run build || true

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app ./
EXPOSE {port}
CMD ["sh", "-c", "{payload.get('start_command') or 'npm run start'}"]
"""
    if runtime in ("react", "vue", "angular", "nuxt"):
        out = {"react": "build", "vue": "dist", "angular": "dist", "nuxt": ".output/public"}[runtime]
        return f"""FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci || npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/{out} /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
"""
    if runtime in ("laravel", "php"):
        return """FROM php:8.3-apache
WORKDIR /var/www/html
RUN apt-get update && apt-get install -y --no-install-recommends libzip-dev unzip \\
    && docker-php-ext-install zip pdo_mysql && rm -rf /var/lib/apt/lists/*
COPY --from=composer:2 /usr/bin/composer /usr/bin/composer
COPY composer.json composer.lock* ./
RUN composer install --no-dev --no-scripts --no-autoloader || composer install --no-scripts
COPY . .
RUN composer dump-autoload --optimize
ENV APACHE_DOCUMENT_ROOT=/var/www/html/public
RUN sed -ri -e 's!/var/www/html!${APACHE_DOCUMENT_ROOT}!g' /etc/apache2/sites-available/*.conf /etc/apache2/apache2.conf && a2enmod rewrite headers
EXPOSE 80
CMD ["apache2-foreground"]
"""
    if runtime in ("fastapi", "django", "flask", "python"):
        start = payload.get("start_command") or {
            "fastapi": f"uvicorn main:app --host 0.0.0.0 --port {port}",
            "django": f"python manage.py runserver 0.0.0.0:{port}",
            "flask": f"flask run --host=0.0.0.0 --port={port}",
            "python": "python main.py",
        }[runtime]
        return f"""FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt* ./
RUN pip install --no-cache-dir -r requirements.txt || pip install --no-cache-dir .
COPY . .
EXPOSE {port}
CMD ["sh", "-c", "{start}"]
"""
    if runtime == "go":
        return f"""FROM golang:1.22-alpine AS build
WORKDIR /app
COPY go.mod go.sum* ./
RUN go mod download
COPY . .
RUN go build -o /bin/app ./...

FROM alpine:3.20
COPY --from=build /bin/app /bin/app
EXPOSE {port}
CMD ["/bin/app"]
"""
    if runtime == "java":
        return f"""FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /app
COPY pom.xml ./
RUN mvn -B dependency:go-offline || true
COPY . .
RUN mvn -B clean package -DskipTests

FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
COPY --from=build /app/target/*.jar app.jar
EXPOSE {port}
CMD ["java", "-jar", "app.jar"]
"""
    if runtime == "ruby":
        return f"""FROM ruby:3.3-alpine
WORKDIR /app
RUN apk add --no-cache build-base postgresql-dev tzdata
COPY Gemfile Gemfile.lock* ./
RUN bundle install || bundle install --without development test
COPY . .
EXPOSE {port}
CMD ["sh", "-c", "{payload.get('start_command') or 'bundle exec puma -p ' + str(port)}"]
"""
    if runtime == "static":
        return f"""FROM nginx:alpine
COPY . /usr/share/nginx/html
EXPOSE {port}
CMD ["nginx", "-g", "daemon off;"]
"""
    raise RuntimeError(f"No buildpack for runtime {runtime!r}")


def run_deployment(payload: dict, send) -> dict:
    """Full deployment pipeline on this host. `send(lines)` streams build logs."""
    slug = payload["slug"]
    deployment_id = payload["deployment_id"]
    network = payload.get("network", "localdeploy-network")
    port = int(payload.get("container_port", 80))
    buffer: list[dict] = []

    def emit(message: str, stream: str = "stdout") -> None:
        buffer.append({"message": message, "stream": stream})
        if len(buffer) >= 8:
            send(list(buffer))
            buffer.clear()

    def flush() -> None:
        if buffer:
            send(list(buffer))
            buffer.clear()

    client = docker.from_env()
    # network
    try:
        client.networks.get(network)
    except docker.errors.NotFound:
        client.networks.create(network, driver="bridge")
    # ensure platform-owned infra (traefik) exists for routing
    if client.containers.list(all=True, filters={"name": "localdeploy-traefik"}) == []:
        emit("→ Booting Traefik for routing on this host")
        client.containers.run(
            "traefik:v3.2", name="localdeploy-traefik", detach=True,
            ports={"80/tcp": 80, "443/tcp": 443},
            command=["--providers.docker", "--providers.docker.exposedbydefault=false",
                     f"--providers.docker.network={network}",
                     "--entrypoints.http.address=:80", "--entrypoints.https.address=:443"],
            volumes={"/var/run/docker.sock": {"bind": "/var/run/docker.sock", "mode": "ro"}},
            network=network, restart_policy={"Name": "unless-stopped"},
        )

    workdir = WORKSPACE / slug / deployment_id[:8]
    workdir.parent.mkdir(parents=True, exist_ok=True)

    image_tag = payload.get("rollback_image") or f"localdeploy/{slug}:{deployment_id[:12]}"
    source_type = payload.get("source_type", "git")

    if payload.get("rollback_image"):
        emit(f"⟲ Rolling back to {image_tag}")
    elif source_type == "image":
        emit(f"→ Pulling {payload.get('docker_image')}")
        client.images.pull(payload["docker_image"])
        image_tag = payload["docker_image"]
    else:
        # clone
        url = payload.get("git_url") or ""
        if not url:
            raise RuntimeError("No git_url in deployment payload")
        if workdir.exists():
            shutil_rmtree(workdir)
        workdir.parent.mkdir(parents=True, exist_ok=True)
        authed = url
        if payload.get("git_username") or payload.get("git_password"):
            authed = re.sub(r"(https?://)", r"\1", url)
            authed = url.replace("https://", f"https://{payload.get('git_username') or ''}:{payload.get('git_password') or ''}@")
        emit(f"→ Cloning {url} (branch: {payload.get('git_branch')})")
        subprocess.run(
            ["git", "clone", "--quiet", "--depth", "1", "--single-branch",
             "--branch", payload.get("git_branch") or "main", authed, str(workdir)],
            check=True, capture_output=True, timeout=600,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        commit = subprocess.run(["git", "-C", str(workdir), "rev-parse", "HEAD"],
                                capture_output=True, text=True).stdout.strip()
        emit(f"✓ Cloned {commit[:8]}")

        dockerfile = build_dockerfile(payload, workdir)
        if dockerfile is None:
            raise RuntimeError("No Dockerfile and no buildpack for this project")
        if dockerfile.name != "Dockerfile" or dockerfile == workdir / "docker-compose.yml":
            pass
        emit(f"→ Building {image_tag} (runtime: {detect_runtime(workdir)})")
        build_stream = client.api.build(
            path=str(workdir), dockerfile=dockerfile.name, tag=image_tag, rm=True, decode=True,
            labels={"io.localdeploy.managed": "true"},
        )
        for chunk in build_stream:
            if "stream" in chunk:
                for line in chunk["stream"].splitlines():
                    if line.strip():
                        emit(line.strip())
            if "errorDetail" in chunk:
                raise RuntimeError(chunk["errorDetail"].get("message", "build failed"))

    # run / compose
    if source_type == "compose" and (workdir / "docker-compose.yml").exists():
        emit("→ docker compose up -d")
        subprocess.run(
            ["docker", "compose", "-p", f"ld-{slug}", "-f", str(workdir / "docker-compose.yml"),
             "up", "-d", "--build", "--remove-orphans"],
            cwd=str(workdir), check=True, capture_output=True, timeout=1800,
            env={**os.environ, **(payload.get("env") or {})},
        )
        containers = client.containers.list(filters={"label": f"com.docker.compose.project=ld-{slug}"})
        primary = containers[0] if containers else None
    else:
        old = None
        try:
            old = client.containers.get(f"ld-{slug}")
            old.rename(f"ld-{slug}-old-{deployment_id[:8]}")
        except docker.errors.NotFound:
            old = None
        replicas = max(1, int(payload.get("replicas", 1)))
        env_map = payload.get("env") or {}
        labels = {"io.localdeploy.managed": "true", **(payload.get("labels_extra") or {}),
                  **(payload.get("traefik_labels") or {})}
        health_port = free_port()
        primary = client.containers.run(
            image=image_tag, name=f"ld-{slug}", detach=True,
            environment=env_map, labels=labels, network=network,
            ports={f"{port}/tcp": ("127.0.0.1", health_port)},
            mem_limit=f"{payload['memory_limit_mb']}m" if payload.get("memory_limit_mb") else None,
            nano_cpus=int((payload.get("cpu_limit") or 0) * 1e9) or None,
            restart_policy={"Name": "unless-stopped"},
        )
        emit(f"→ Health checking port {port} (up to 120s)")
        healthy = False
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            primary.reload()
            if primary.status not in ("running", "created", "restarting"):
                raise RuntimeError(f"container is {primary.status}")
            try:
                import http.client

                conn = http.client.HTTPConnection("127.0.0.1", health_port, timeout=3)
                conn.request("GET", payload.get("health_check_path") or "/")
                if conn.getresponse().status < 500:
                    healthy = True
                    conn.close()
                    break
                conn.close()
            except OSError:
                time.sleep(2)
        if not healthy:
            primary.remove(force=True)
            if old:
                old.rename(f"ld-{slug}")
            raise RuntimeError("Health check failed")
        emit("✓ Health check passed")
        if old:
            old.remove(force=True)
        # extra replicas
        for index in range(2, replicas + 1):
            try:
                client.containers.run(
                    image=image_tag, name=f"ld-{slug}-r{index}", detach=True,
                    environment=env_map, labels=labels, network=network,
                    mem_limit=f"{payload['memory_limit_mb']}m" if payload.get("memory_limit_mb") else None,
                    nano_cpus=int((payload.get("cpu_limit") or 0) * 1e9) or None,
                    restart_policy={"Name": "unless-stopped"},
                )
            except Exception as exc:
                emit(f"⚠ replica {index} failed: {exc}", stream="stderr")
        emit(f"→ Running {replicas} replica(s)")

    flush()
    primary.reload()
    return {
        "ok": True,
        "image_tag": image_tag,
        "container_id": primary.id,
        "container_name": primary.name,
    }


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def shutil_rmtree(path: Path) -> None:
    import shutil

    shutil.rmtree(path, ignore_errors=True)


# ---------------------------------------------------------------------------
# main loop
# ---------------------------------------------------------------------------

def handle_command(command: dict, client) -> None:
    command_id = command["command_id"]
    ctype = command["type"]
    payload = command.get("payload") or {}
    log(f"command {ctype} received")
    try:
        if ctype == "deploy":
            def send(lines):
                send_logs(payload["deployment_id"], lines)

            result = run_deployment(payload, send)
            api_post("/api/agent/result", {"command_id": command_id, "ok": True, "result": result})
            log(f"deploy {payload.get('slug')} finished OK")
        elif ctype == "container_action":
            result = container_action(payload)
            api_post("/api/agent/result", {"command_id": command_id, "ok": True, "result": result})
        else:
            api_post("/api/agent/result", {"command_id": command_id, "ok": False,
                                           "error": f"unknown command type {ctype}"})
    except Exception as exc:
        traceback.print_exc()
        try:
            if ctype == "deploy":
                send_logs(payload.get("deployment_id", ""),
                          [{"message": f"✖ Agent error: {exc}", "stream": "stderr"}])
            api_post("/api/agent/result", {"command_id": command_id, "ok": False,
                                           "error": f"{type(exc).__name__}: {exc}"[:1000]})
        except Exception:
            pass


def main() -> None:
    if not API_URL or not TOKEN:
        print("Set LOCALDEPLOY_API_URL and LOCALDEPLOY_SERVER_TOKEN first.", file=sys.stderr)
        sys.exit(1)
    log(f"agent {AGENT_VERSION} → {API_URL}")
    docker.from_env().ping()
    log("docker OK")
    while True:
        try:
            response = api_post("/api/agent/hello", collect_stats(), timeout=40)
            for command in response.get("commands", []):
                handle_command(command, None)
        except requests.HTTPError as exc:
            log(f"hello failed: {exc.response.status_code if exc.response is not None else '?'} — check token")
        except Exception as exc:
            log(f"heartbeat error: {exc}")
        time.sleep(HEARTBEAT_SECONDS)


if __name__ == "__main__":
    main()
