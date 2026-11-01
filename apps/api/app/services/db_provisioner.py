"""Database instance provisioning on the local Docker Engine.

Databases are provisioned as managed containers on the private deploy network.
Ports are NOT published publicly by default — an optional loopback-only port
can be enabled for local tooling.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass

from ..core.config import settings
from .docker_client import DockerUnavailableError, docker_service


@dataclass
class EngineSpec:
    image: str
    port: int
    volume_mount: str
    username: str
    env: list[str]
    cmd: list[str] | None = None
    health_cmd: str | None = None
    default_database: str | None = None
    connection_url: str = ""


def engine_spec(engine: str, version: str, password: str, username: str, database: str) -> EngineSpec:
    images = {
        "postgresql": f"postgres:{version or '16-alpine'}",
        "mysql": f"mysql:{version or '8.0'}",
        "mariadb": f"mariadb:{version or '11'}",
        "redis": f"redis:{version or '7-alpine'}",
        "mongodb": f"mongo:{version or '7'}",
    }
    if engine not in images:
        raise ValueError(f"Unsupported database engine: {engine}")
    image = images[engine]

    if engine == "postgresql":
        return EngineSpec(
            image=image, port=5432, volume_mount="/var/lib/postgresql/data",
            username=username or "localdeploy",
            env=[f"POSTGRES_PASSWORD={password}", f"POSTGRES_USER={username or 'localdeploy'}",
                 f"POSTGRES_DB={database or (username or 'localdeploy')}"],
            health_cmd="pg_isready -U " + (username or "localdeploy"),
            default_database=database or (username or "localdeploy"),
        )
    if engine == "mysql":
        return EngineSpec(
            image=image, port=3306, volume_mount="/var/lib/mysql",
            username="root",
            env=[f"MYSQL_ROOT_PASSWORD={password}", f"MYSQL_DATABASE={database or 'app'}"],
            health_cmd="mysqladmin ping -u root -p$MYSQL_ROOT_PASSWORD --silent",
            default_database=database or "app",
        )
    if engine == "mariadb":
        return EngineSpec(
            image=image, port=3306, volume_mount="/var/lib/mysql",
            username="root",
            env=[f"MARIADB_ROOT_PASSWORD={password}", f"MARIADB_DATABASE={database or 'app'}"],
            health_cmd="healthcheck.sh --connect --innodb_initialized",
            default_database=database or "app",
        )
    if engine == "redis":
        return EngineSpec(
            image=image, port=6379, volume_mount="/data",
            username="default",
            env=[f"REDIS_PASSWORD={password}"],
            cmd=["redis-server", "--requirepass", password, "--appendonly", "yes"],
            health_cmd=f"redis-cli -a '{password}' ping | grep PONG",
        )
    # mongodb
    return EngineSpec(
        image=image, port=27017, volume_mount="/data/db",
        username="root",
        env=[f"MONGO_INITDB_ROOT_USERNAME=root", f"MONGO_INITDB_ROOT_PASSWORD={password}"],
        health_cmd="mongosh --quiet --eval 'db.runCommand({ping:1}).ok' --norc",
    )


def provision(instance) -> dict:
    """Create + start the database container. Returns {'container_id': ...}."""
    spec = engine_spec(
        instance.engine, instance.version, _dec(instance.password_encrypted),
        instance.username, instance.database_name or "",
    )
    client = docker_service.require()
    docker_service.ensure_network(settings.deploy_network)

    try:
        client.images.pull(spec.image)
    except Exception as exc:
        raise DockerUnavailableError(f"Failed to pull {spec.image}: {exc}") from exc

    ports = {}
    if instance.published_port:
        ports[f"{spec.port}/tcp"] = ("127.0.0.1", instance.published_port)

    container = client.containers.run(
        image=spec.image,
        name=instance.container_name,
        detach=True,
        environment=spec.env,
        command=spec.cmd,
        ports=ports,
        volumes={instance.volume_name: {"bind": spec.volume_mount, "mode": "rw"}},
        network=settings.deploy_network,
        labels={
            "io.localdeploy.managed": "true",
            "io.localdeploy.database": str(instance.id),
            "io.localdeploy.kind": "database",
        },
        restart_policy={"Name": "unless-stopped"},
    )
    instance.container_id = container.id
    return {"container_id": container.id}


def wait_healthy(instance, timeout_seconds: int = 90) -> bool:
    spec = engine_spec(instance.engine, instance.version, _dec(instance.password_encrypted),
                       instance.username, instance.database_name or "")
    client = docker_service.require()
    import time

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            container = client.containers.get(instance.container_name)
            container.reload()
            if container.status == "exited":
                return False
            if spec.health_cmd:
                code, _ = container.exec_run(["sh", "-c", spec.health_cmd])
                if code == 0:
                    return True
            elif container.status == "running":
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def action(instance, action_name: str) -> None:
    client = docker_service.require()
    container = docker_service.get_container(instance.container_name)
    if container is None:
        if action_name == "start":
            provision(instance)
            return
        raise DockerUnavailableError("Database container not found")
    getattr(container, action_name)()


def remove(instance, remove_volume: bool = False) -> None:
    client = docker_service.require()
    container = docker_service.get_container(instance.container_name)
    if container:
        container.remove(force=True)
    if remove_volume:
        try:
            volume = client.volumes.get(instance.volume_name)
            volume.remove(force=True)
        except Exception:
            pass


def connection_info(instance) -> dict:
    from ..core.security import decrypt_secret

    spec = engine_spec(instance.engine, instance.version, "", instance.username, instance.database_name or "")
    password = decrypt_secret(instance.password_encrypted)
    host = instance.container_name  # reachable on the deploy network by name
    base = {
        "engine": instance.engine,
        "internal_host": host,
        "internal_port": spec.port,
        "username": instance.username,
        "password": password,
        "database": instance.database_name or instance.username,
        "published_port": instance.published_port,
        "network": settings.deploy_network,
        "volume": instance.volume_name,
    }
    urls = {
        "postgresql": f"postgresql://{instance.username}:{password}@{host}:{spec.port}/{base['database']}",
        "mysql": f"mysql://{instance.username}:{password}@{host}:{spec.port}/{base['database']}",
        "mariadb": f"mysql://{instance.username}:{password}@{host}:{spec.port}/{base['database']}",
        "mongodb": f"mongodb://root:{password}@{host}:{spec.port}/",
        "redis": f"redis://:{password}@{host}:{spec.port}/0",
    }
    base["connection_url"] = urls.get(instance.engine, "")
    base["env_line"] = f"DATABASE_URL={base['connection_url']}"
    return base


def generate_password() -> str:
    return secrets.token_urlsafe(18)


def _dec(value: str) -> str:
    from ..core.security import decrypt_secret

    return decrypt_secret(value)
