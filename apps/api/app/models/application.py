"""Projects, applications, domains and environment variables."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Float, Index, Integer, String, Text, Uuid, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db import Base
from ..core.mixins import SoftDeleteMixin, TimestampMixin, UUIDPk
from .user import gen_uuid


class Project(Base, UUIDPk, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "projects"

    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)

    applications: Mapped[list["Application"]] = relationship(back_populates="project")


class Application(Base, UUIDPk, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("slug", name="uq_applications_slug"),)

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("projects.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str] = mapped_column(String(80), index=True)
    description: Mapped[str | None] = mapped_column(Text)

    # Source configuration: git | dockerfile | compose | image | upload
    source_type: Mapped[str] = mapped_column(String(20), default="git")
    project_type: Mapped[str | None] = mapped_column(String(40))  # detected runtime

    # Git source
    git_url: Mapped[str | None] = mapped_column(String(500))
    git_branch: Mapped[str | None] = mapped_column(String(255), default="main")
    git_username: Mapped[str | None] = mapped_column(String(255))
    git_password_encrypted: Mapped[str | None] = mapped_column(Text)
    git_commit_sha: Mapped[str | None] = mapped_column(String(64))

    # Docker sources
    dockerfile_path: Mapped[str | None] = mapped_column(String(255), default="Dockerfile")
    docker_compose_path: Mapped[str | None] = mapped_column(String(255), default="docker-compose.yml")
    docker_image: Mapped[str | None] = mapped_column(String(500))

    # Build & run
    install_command: Mapped[str | None] = mapped_column(String(500))
    build_command: Mapped[str | None] = mapped_column(String(500))
    start_command: Mapped[str | None] = mapped_column(String(500))
    container_port: Mapped[int] = mapped_column(Integer, default=80)
    health_check_path: Mapped[str | None] = mapped_column(String(255), default="/")

    # Runtime
    status: Mapped[str] = mapped_column(String(20), default="idle", index=True)
    container_name: Mapped[str | None] = mapped_column(String(255))
    container_id: Mapped[str | None] = mapped_column(String(80))
    auto_deploy: Mapped[bool] = mapped_column(Boolean, default=True)
    last_deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Resource limits
    cpu_limit: Mapped[float | None] = mapped_column(Float)  # vCPUs
    memory_limit_mb: Mapped[int | None] = mapped_column(Integer)

    # Extra docker-compose env passthrough (JSON map) for compose sources
    extra_config: Mapped[dict] = mapped_column(JSON, default=dict)

    project: Mapped[Project | None] = relationship(back_populates="applications")
    domains: Mapped[list["ApplicationDomain"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )
    env_vars: Mapped[list["EnvironmentVariable"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )
    webhook_integrations: Mapped[list["WebhookIntegration"]] = relationship(
        back_populates="application", cascade="all, delete-orphan"
    )


class ApplicationDomain(Base, UUIDPk, TimestampMixin):
    __tablename__ = "application_domains"
    __table_args__ = (UniqueConstraint("hostname", name="uq_domains_hostname"),)

    application_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    hostname: Mapped[str] = mapped_column(String(255), index=True)
    target_port: Mapped[int | None] = mapped_column(Integer)  # override app port
    ssl_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    ssl_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|issued|failed|disabled
    ssl_issuer: Mapped[str | None] = mapped_column(String(120))
    ssl_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)

    application: Mapped[Application] = relationship(back_populates="domains")

    @property
    def application_name(self) -> str | None:
        return self.application.name if self.application else None

    @property
    def application_slug(self) -> str | None:
        return self.application.slug if self.application else None


class EnvironmentVariable(Base, UUIDPk, TimestampMixin):
    __tablename__ = "environment_variables"
    __table_args__ = (UniqueConstraint("application_id", "key", name="uq_env_app_key"),)

    application_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(String(120))
    value_encrypted: Mapped[str] = mapped_column(Text)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str | None] = mapped_column(Text)

    application: Mapped[Application] = relationship(back_populates="env_vars")

    @property
    def has_value(self) -> bool:
        return bool(self.value_encrypted)


class WebhookIntegration(Base, UUIDPk, TimestampMixin):
    __tablename__ = "webhook_integrations"

    application_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String(20), default="github")  # github|gitlab|gitea|generic
    secret_encrypted: Mapped[str] = mapped_column(Text)
    secret_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # URL token
    branch: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    application: Mapped[Application] = relationship(back_populates="webhook_integrations")
