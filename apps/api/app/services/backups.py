"""Backup & restore for database instances and Docker volumes.

Backups run as one-off helper containers so no database client tools are
required on the host. Files land in the configured backups directory.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from ..core.config import settings
from ..core.security import decrypt_secret
from .docker_client import docker_service


def _backups_bind() -> str:
    path = Path(settings.backups_dir).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _run_helper(image: str, name: str, volumes: dict, cmd: list[str], env: dict | None = None) -> tuple[int, str]:
    client = docker_service.require()
    container = client.containers.run(
        image=image,
        name=name,
        command=cmd,
        detach=True,
        volumes=volumes,
        environment=env or {},
        labels={"io.localdeploy.managed": "true", "io.localdeploy.kind": "backup-job"},
        network=settings.deploy_network,
    )
    result = container.wait()
    output = container.logs(stdout=True, stderr=True).decode(errors="replace")
    container.remove(force=True)
    return result.get("StatusCode", 1), output


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def backup_database(instance, filename: str) -> Path:
    """Dump the database into backups_dir and return the file path."""
    password = decrypt_secret(instance.password_encrypted)
    backups = _backups_bind()
    out = Path(backups) / filename
    if out.exists():
        out.unlink()
    out.parent.mkdir(parents=True, exist_ok=True)

    engine = instance.engine
    db_volume = instance.volume_name

    if engine == "postgresql":
        cmd = ["sh", "-c",
               f"PGPASSWORD='{password}' pg_dump -U '{instance.username}' "
               f"-h 127.0.0.1 -F p /{instance.database_name or instance.username} > /backups/{filename}"]
        # pg_dump needs to reach the DB — connect over the deploy network instead
        cmd = ["sh", "-c",
               f"pg_dump -U '{instance.username}' -h '{instance.container_name}' "
               f"-F p {instance.database_name or instance.username} > /backups/{filename}"]
        code, output = _run_helper(
            instance.image, f"ld-backup-{filename[:40]}", {backups: {"bind": "/backups", "mode": "rw"}},
            cmd, {"PGPASSWORD": password},
        )
    elif engine in ("mysql", "mariadb"):
        cmd = ["sh", "-c",
               f"mysqldump -h '{instance.container_name}' -u root -p\"$MYSQL_ROOT_PASSWORD\" "
               f"--all-databases --single-transaction > /backups/{filename}"]
        code, output = _run_helper(
            instance.image, f"ld-backup-{filename[:40]}", {backups: {"bind": "/backups", "mode": "rw"}},
            cmd, {"MYSQL_ROOT_PASSWORD": password},
        )
    elif engine == "redis":
        cmd = ["sh", "-c",
               f"redis-cli -h '{instance.container_name}' -a \"$REDIS_PASSWORD\" "
               f"--rdb /backups/{filename}"]
        code, output = _run_helper(
            instance.image, f"ld-backup-{filename[:40]}", {backups: {"bind": "/backups", "mode": "rw"}},
            cmd, {"REDIS_PASSWORD": password},
        )
    elif engine == "mongodb":
        cmd = ["sh", "-c",
               f"mongodump --host '{instance.container_name}' -u root -p \"$MONGO_PASS\" "
               f"--authenticationDatabase admin --archive=/backups/{filename}"]
        code, output = _run_helper(
            instance.image, f"ld-backup-{filename[:40]}", {backups: {"bind": "/backups", "mode": "rw"}},
            cmd, {"MONGO_PASS": password},
        )
    else:
        raise ValueError(f"Backup not supported for engine {engine}")

    if code != 0 or not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f"Database backup failed: {output[-500:]}")
    return out


def restore_database(instance, backup_file: Path) -> None:
    password = decrypt_secret(instance.password_encrypted)
    backups = _backups_bind()
    filename = backup_file.name
    engine = instance.engine

    if engine == "postgresql":
        cmd = ["sh", "-c",
               f"psql -U '{instance.username}' -h '{instance.container_name}' "
               f"-d {instance.database_name or instance.username} < /backups/{filename}"]
        env = {"PGPASSWORD": password}
        image = instance.image
    elif engine in ("mysql", "mariadb"):
        cmd = ["sh", "-c",
               f"mysql -h '{instance.container_name}' -u root -p\"$MYSQL_ROOT_PASSWORD\" < /backups/{filename}"]
        env = {"MYSQL_ROOT_PASSWORD": password}
        image = instance.image
    elif engine == "mongodb":
        cmd = ["sh", "-c",
               f"mongorestore --host '{instance.container_name}' -u root -p \"$MONGO_PASS\" "
               f"--authenticationDatabase admin --archive=/backups/{filename} --drop"]
        env = {"MONGO_PASS": password}
        image = instance.image
    elif engine == "redis":
        cmd = ["sh", "-c",
               f"redis-cli -h '{instance.container_name}' -a \"$REDIS_PASSWORD\" --rdb /backups/{filename}"]
        env = {"REDIS_PASSWORD": password}
        image = instance.image
    else:
        raise ValueError(f"Restore not supported for engine {engine}")

    code, output = _run_helper(
        image, f"ld-restore-{filename[:40]}", {backups: {"bind": "/backups", "mode": "ro"}},
        cmd, env,
    )
    if code != 0:
        raise RuntimeError(f"Database restore failed: {output[-500:]}")


def backup_volume(volume_name: str, filename: str) -> Path:
    backups = _backups_bind()
    out = Path(backups) / filename
    code, output = _run_helper(
        "alpine:3.20", f"ld-vbackup-{filename[:40]}",
        {
            volume_name: {"bind": "/volume", "mode": "ro"},
            backups: {"bind": "/backups", "mode": "rw"},
        },
        ["sh", "-c", f"tar czf /backups/{filename} -C /volume ."],
    )
    if code != 0:
        raise RuntimeError(f"Volume backup failed: {output[-500:]}")
    return out


def restore_volume(volume_name: str, backup_file: Path) -> None:
    backups = _backups_bind()
    code, output = _run_helper(
        "alpine:3.20", f"ld-vrestore-{backup_file.name[:40]}",
        {
            volume_name: {"bind": "/volume", "mode": "rw"},
            backups: {"bind": "/backups", "mode": "ro"},
        },
        ["sh", "-c", f"tar xzf /backups/{backup_file.name} -C /volume"],
    )
    if code != 0:
        raise RuntimeError(f"Volume restore failed: {output[-500:]}")


def finalize_record(record, path: Path) -> None:
    record.file_size_bytes = path.stat().st_size
    record.checksum = _checksum(path)
    record.status = "success"
    from ..core.db import utcnow

    record.finished_at = utcnow()


def backup_file_path(filename: str) -> Path:
    return Path(_backups_bind()) / os.path.basename(filename)
