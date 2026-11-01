"""Deployments and their streamed build logs."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..core.db import Base, utcnow
from ..core.mixins import UUIDPk


class Deployment(Base, UUIDPk):
    __tablename__ = "deployments"

    application_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    # queued | running | success | failed | cancelled | timed_out
    trigger: Mapped[str] = mapped_column(String(20), default="manual")  # manual|webhook|rollback|retry
    git_branch: Mapped[str | None] = mapped_column(String(255))
    git_commit_sha: Mapped[str | None] = mapped_column(String(64))
    git_message: Mapped[str | None] = mapped_column(String(500))
    image_tag: Mapped[str | None] = mapped_column(String(255))
    source_type: Mapped[str | None] = mapped_column(String(20))
    project_type: Mapped[str | None] = mapped_column(String(40))
    rollback_of_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("deployments.id"))
    error_message: Mapped[str | None] = mapped_column(Text)
    build_duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    created_by_name: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)

    application = relationship("Application", backref="deployments")
    logs: Mapped[list["DeploymentLog"]] = relationship(
        back_populates="deployment", cascade="all, delete-orphan", order_by="DeploymentLog.sequence"
    )

    @property
    def application_name(self) -> str | None:
        return self.application.name if self.application else None

    @property
    def application_slug(self) -> str | None:
        return self.application.slug if self.application else None

    __table_args__ = (Index("ix_deployments_app_created", "application_id", "created_at"),)


class DeploymentLog(Base, UUIDPk):
    __tablename__ = "deployment_logs"

    deployment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("deployments.id", ondelete="CASCADE"), index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    stream: Mapped[str] = mapped_column(String(10), default="system")  # stdout|stderr|system
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    deployment = relationship("Deployment", back_populates="logs")

    __table_args__ = (Index("ix_deployment_logs_seq", "deployment_id", "sequence"),)


class BackupRecord(Base, UUIDPk):
    __tablename__ = "backup_records"

    target_type: Mapped[str] = mapped_column(String(20), index=True)  # database|volume
    target_id: Mapped[str] = mapped_column(String(64), index=True)
    target_name: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(Text)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    checksum: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|running|success|failed
    restore_of_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("backup_records.id"))
    created_by_name: Mapped[str | None] = mapped_column(String(64))
    error_message: Mapped[str | None] = mapped_column(Text)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
