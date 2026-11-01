"""Database instances (provisioned datastores), storage volumes and tunnels."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base, utcnow
from ..core.mixins import SoftDeleteMixin, TimestampMixin, UUIDPk


class DatabaseInstance(Base, UUIDPk, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "database_instances"

    name: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    engine: Mapped[str] = mapped_column(String(20))  # postgresql|mysql|mariadb|redis|mongodb
    image: Mapped[str] = mapped_column(String(200))
    version: Mapped[str] = mapped_column(String(40), default="latest")
    username: Mapped[str] = mapped_column(String(120), default="localdeploy")
    password_encrypted: Mapped[str] = mapped_column(Text)
    database_name: Mapped[str | None] = mapped_column(String(120))
    port: Mapped[int] = mapped_column(Integer)  # internal container port
    published_port: Mapped[int | None] = mapped_column(Integer)  # 127.0.0.1-only publish when set
    container_name: Mapped[str] = mapped_column(String(120), unique=True)
    volume_name: Mapped[str] = mapped_column(String(120))
    container_id: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="creating")  # creating|running|stopped|error
    last_error: Mapped[str | None] = mapped_column(Text)
    last_health_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StorageVolume(Base, UUIDPk):
    __tablename__ = "storage_volumes"

    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    driver: Mapped[str] = mapped_column(String(60), default="local")
    application_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    database_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    mountpoint: Mapped[str | None] = mapped_column(Text)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    in_use: Mapped[bool] = mapped_column(Boolean, default=False)
    labels: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TunnelConnection(Base, UUIDPk, TimestampMixin):
    __tablename__ = "tunnel_connections"

    name: Mapped[str] = mapped_column(String(120))
    token_encrypted: Mapped[str] = mapped_column(Text)
    mode: Mapped[str] = mapped_column(String(20), default="token")  # token | config
    status: Mapped[str] = mapped_column(String(20), default="stopped")  # stopped|running|error|unknown
    container_id: Mapped[str | None] = mapped_column(String(80))
    public_hostnames: Mapped[list] = mapped_column(JSON, default=list)
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)


class ServerSetting(Base, UUIDPk):
    __tablename__ = "server_settings"

    key: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    description: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
