"""Docker Engine access layer.

All Docker access goes through this module. The Docker socket is treated as
privileged host-level access: it is never exposed to browsers or to deployed
applications. When the engine is unreachable, the service degrades gracefully
(`available() -> False`) instead of crashing endpoints.
"""
from __future__ import annotations

import threading
from typing import Any

import docker
from docker.errors import DockerException, NotFound

from ..core.config import settings


class DockerService:
    """Thread-safe lazy Docker client with availability probing."""

    def __init__(self) -> None:
        self._client: docker.DockerClient | None = None
        self._lock = threading.Lock()
        self._last_error: str | None = None
        self._unavailable = bool(settings.docker_disabled)

    def _create(self) -> docker.DockerClient | None:
        try:
            kwargs: dict[str, Any] = {}
            if settings.docker_host:
                kwargs["base_url"] = settings.docker_host
            client = docker.DockerClient(**kwargs)
            client.ping()
            self._last_error = None
            return client
        except DockerException as exc:
            self._last_error = str(exc)
            return None
        except Exception as exc:  # pragma: no cover - platform-specific errors
            self._last_error = f"{type(exc).__name__}: {exc}"
            return None

    def client(self) -> docker.DockerClient | None:
        if self._unavailable:
            return None
        if self._client is not None:
            try:
                self._client.ping()
                return self._client
            except Exception:
                with self._lock:
                    self._client = None
        with self._lock:
            if self._client is None:
                self._client = self._create()
            return self._client

    @property
    def available(self) -> bool:
        return self.client() is not None

    @property
    def last_error(self) -> str | None:
        return self._last_error

    def require(self) -> docker.DockerClient:
        client = self.client()
        if client is None:
            raise DockerUnavailableError(self._last_error or "Docker Engine is not reachable")
        return client

    def engine_info(self) -> dict[str, Any]:
        """Engine metadata for the dashboard Docker status card."""
        client = self.client()
        if client is None:
            return {
                "available": False,
                "error": self._last_error or "Docker Engine is not reachable",
                "hint": _unavailable_hint(),
            }
        try:
            version = client.version()
            info = client.info()
            return {
                "available": True,
                "version": version.get("Version"),
                "api_version": version.get("ApiVersion"),
                "os": info.get("OperatingSystem"),
                "architecture": info.get("Architecture"),
                "cpus": info.get("NCPU"),
                "total_memory_mb": round((info.get("MemTotal") or 0) / 1024 / 1024),
                "containers": info.get("Containers"),
                "containers_running": info.get("ContainersRunning"),
                "containers_paused": info.get("ContainersPaused"),
                "containers_stopped": info.get("ContainersStopped"),
                "images": info.get("Images"),
                "server_version": info.get("ServerVersion"),
            }
        except Exception as exc:
            return {"available": False, "error": str(exc), "hint": _unavailable_hint()}

    # -- helpers shared by services -------------------------------------

    def ensure_network(self, name: str) -> Any:
        client = self.require()
        try:
            return client.networks.get(name)
        except NotFound:
            return client.networks.create(
                name, driver="bridge", labels={"io.localdeploy.managed": "true"}
            )

    def get_container(self, ref: str) -> Any | None:
        try:
            return self.require().containers.get(ref)
        except NotFound:
            return None

    def list_managed_containers(self, all: bool = True) -> list[Any]:
        return self.require().containers.list(
            all=all, filters={"label": "io.localdeploy.managed=true"}
        )


class DockerUnavailableError(RuntimeError):
    pass


def _unavailable_hint() -> str:
    import platform

    if platform.system() == "Windows":
        return (
            "Install Docker Desktop for Windows and make sure it is running "
            "(or use WSL2 with Docker Engine). See docs/WSL2.md."
        )
    return "Install Docker Engine and ensure the current user can access /var/run/docker.sock."


docker_service = DockerService()
