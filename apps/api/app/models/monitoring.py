"""Monitoring metrics for the host server and application containers."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from ..core.db import Base, utcnow
from ..core.mixins import UUIDPk


class ServerMetric(Base, UUIDPk):
    __tablename__ = "server_metrics"

    cpu_percent: Mapped[float] = mapped_column(Float)
    memory_used_mb: Mapped[float] = mapped_column(Float)
    memory_total_mb: Mapped[float] = mapped_column(Float)
    memory_percent: Mapped[float] = mapped_column(Float)
    disk_used_gb: Mapped[float] = mapped_column(Float)
    disk_total_gb: Mapped[float] = mapped_column(Float)
    disk_percent: Mapped[float] = mapped_column(Float)
    net_rx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    net_tx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    load_1: Mapped[float | None] = mapped_column(Float, nullable=True)
    container_count: Mapped[int] = mapped_column(BigInteger, default=0)
    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    __table_args__ = (Index("ix_server_metrics_time", "sampled_at"),)


class ApplicationMetric(Base, UUIDPk):
    __tablename__ = "application_metrics"

    application_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    container_id: Mapped[str | None] = mapped_column(String(80))
    cpu_percent: Mapped[float] = mapped_column(Float, default=0)
    memory_usage_mb: Mapped[float] = mapped_column(Float, default=0)
    memory_limit_mb: Mapped[float] = mapped_column(Float, default=0)
    net_rx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    net_tx_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)

    __table_args__ = (Index("ix_app_metrics_app_time", "application_id", "sampled_at"),)
