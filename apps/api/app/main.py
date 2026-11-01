"""LocalDeploy API — application assembly and lifecycle."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .api.deps import record_metrics
from .api.routes import (applications, auth, backups, databases, db_connections, deployments,
                         domains, docker, logs, monitoring, networking, projects, storage,
                         users, webhooks)
from .api.routes import settings as settings_routes
from .core.config import settings
from .core.db import bootstrap
from .services.log_hub import log_hub
from .services.worker import metrics_sampler, session_cleaner, worker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("localdeploy")

DESCRIPTION = """
LocalDeploy API — self-hosted deployment & application hosting platform.

Transforms a local machine into a PaaS-style hosting platform with real Docker
integration, Git-based deployments, Traefik routing, SSL, monitoring, and
Cloudflare Tunnel support.
"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    from .core.db import SessionLocal

    db = SessionLocal()
    try:
        bootstrap(db)
    finally:
        db.close()

    await worker.start()
    import asyncio

    metrics_task = asyncio.create_task(metrics_sampler())
    session_task = asyncio.create_task(session_cleaner())

    await log_hub.publish("system", {
        "type": "platform", "level": "info",
        "message": f"LocalDeploy API started (v{settings.version})",
    })
    logger.info("LocalDeploy API started — workspace=%s backups=%s", settings.workspace_dir, settings.backups_dir)
    yield
    metrics_task.cancel()
    session_task.cancel()
    await worker.stop()
    logger.info("LocalDeploy API stopped")


app = FastAPI(
    title="LocalDeploy API",
    description=DESCRIPTION,
    version=settings.version,
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-CSRF-Token"],
)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    response = await call_next(request)
    route = request.scope.get("route")
    template = getattr(route, "path", request.url.path)
    if template.startswith("/api") or template == "/metrics":
        record_metrics(template, response.status_code)
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.get("/api/health", tags=["health"])
def health():
    from .services.docker_client import docker_service

    return {
        "status": "ok",
        "version": settings.version,
        "docker_available": docker_service.available,
    }


@app.get("/metrics", include_in_schema=False)
def prometheus_endpoint():
    """Prometheus scrape endpoint (plain text)."""
    from fastapi import Response as FastAPIResponse

    from .core.db import SessionLocal
    from .services.prometheus import render_metrics

    db = SessionLocal()
    try:
        return FastAPIResponse(content=render_metrics(db), media_type="text/plain; version=0.0.4")
    finally:
        db.close()


# Routers
for router in (
    auth.router, users.router, projects.router, applications.router, deployments.router,
    domains.router, webhooks.router, docker.router, storage.router, databases.router,
    backups.router, monitoring.router, logs.router, networking.router, settings_routes.router,
    db_connections.router,
):
    app.include_router(router)
