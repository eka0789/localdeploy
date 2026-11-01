"""Pydantic request/response schemas (input validation boundary)."""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")
ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,118}$")
USERNAME_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,64}$")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- auth/users

class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=255)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=255)
    new_password: str = Field(min_length=8, max_length=128)


class UserOut(ORMModel):
    id: uuid.UUID
    username: str
    email: str
    role_id: uuid.UUID | None = None
    role_name: str | None = None
    is_active: bool
    must_change_password: bool = False
    last_login_at: datetime | None = None
    created_at: datetime | None = None


class UserCreate(BaseModel):
    username: str
    email: str
    password: str = Field(min_length=8, max_length=128)
    role_id: str | None = None

    @field_validator("username")
    @classmethod
    def username_valid(cls, v: str) -> str:
        if not USERNAME_RE.match(v):
            raise ValueError("Username may contain letters, digits, dot, dash, underscore (3-64 chars)")
        return v

    @field_validator("email")
    @classmethod
    def email_valid(cls, v: str) -> str:
        if "@" not in v or len(v) > 255:
            raise ValueError("Invalid email address")
        return v.lower()


class UserUpdate(BaseModel):
    email: str | None = None
    role_id: str | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)


class RoleOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    is_system: bool = False
    permission_keys: list[str] = []


# ---------------------------------------------------------------- projects

class ProjectCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


class ProjectOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str | None = None
    created_at: datetime
    application_count: int = 0


# ---------------------------------------------------------------- applications

SourceType = Literal["git", "dockerfile", "compose", "image", "upload"]


class ApplicationCreate(BaseModel):
    name: str = Field(min_length=2, max_length=255)
    project_id: str | None = None
    description: str | None = Field(default=None, max_length=2000)
    source_type: SourceType = "git"
    project_type: str | None = None
    git_url: str | None = Field(default=None, max_length=500)
    git_branch: str | None = Field(default=None, max_length=255)
    git_username: str | None = Field(default=None, max_length=255)
    git_password: str | None = Field(default=None, max_length=500)
    dockerfile_path: str | None = Field(default=None, max_length=255)
    docker_compose_path: str | None = Field(default=None, max_length=255)
    docker_image: str | None = Field(default=None, max_length=500)
    install_command: str | None = Field(default=None, max_length=500)
    build_command: str | None = Field(default=None, max_length=500)
    start_command: str | None = Field(default=None, max_length=500)
    container_port: int = Field(default=80, ge=1, le=65535)
    health_check_path: str | None = Field(default=None, max_length=255)
    auto_deploy: bool = True
    cpu_limit: float | None = Field(default=None, gt=0, le=64)
    memory_limit_mb: int | None = Field(default=None, ge=16, le=65536)

    @field_validator("container_port")
    @classmethod
    def not_privileged(cls, v: int) -> int:
        if v < 1:
            raise ValueError("Port must be >= 1")
        return v


class ApplicationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    project_id: str | None = None
    description: str | None = None
    source_type: SourceType | None = None
    project_type: str | None = None
    git_url: str | None = Field(default=None, max_length=500)
    git_branch: str | None = Field(default=None, max_length=255)
    git_username: str | None = None
    git_password: str | None = None
    dockerfile_path: str | None = None
    docker_compose_path: str | None = None
    docker_image: str | None = None
    install_command: str | None = None
    build_command: str | None = None
    start_command: str | None = None
    container_port: int | None = Field(default=None, ge=1, le=65535)
    health_check_path: str | None = None
    auto_deploy: bool | None = None
    cpu_limit: float | None = Field(default=None, gt=0, le=64)
    memory_limit_mb: int | None = Field(default=None, ge=16, le=65536)


class ApplicationOut(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID | None
    name: str
    slug: str
    description: str | None
    source_type: str
    project_type: str | None
    git_url: str | None
    git_branch: str | None
    status: str
    container_name: str | None
    container_port: int
    health_check_path: str | None
    auto_deploy: bool
    cpu_limit: float | None
    memory_limit_mb: int | None
    last_deployed_at: datetime | None
    created_at: datetime
    domain_count: int = 0
    domains: list[str] = []
    replicas: int = 1
    autoscale_enabled: bool = False
    autoscale_cpu_threshold: int = 70
    autoscale_min: int = 1
    autoscale_max: int = 3
    is_preview: bool = False
    preview_of: str | None = None
    pr_number: int | None = None
    enable_previews: bool = False
    preview_base_domain: str | None = None
    preview_retention_days: int = 7
    server_id: str | None = None


class ApplicationDetail(ApplicationOut):
    git_username: str | None = None
    dockerfile_path: str | None = None
    docker_compose_path: str | None = None
    docker_image: str | None = None
    install_command: str | None = None
    build_command: str | None = None
    start_command: str | None = None
    container_id: str | None = None
    has_git_password: bool = False


class EnvVarCreate(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    value: str = Field(default="", max_length=8000)
    is_secret: bool = True

    @field_validator("key")
    @classmethod
    def key_valid(cls, v: str) -> str:
        if not ENV_KEY_RE.match(v):
            raise ValueError("Env var keys must match [A-Za-z_][A-Za-z0-9_]*")
        return v


class EnvVarUpdate(BaseModel):
    value: str = Field(default="", max_length=8000)
    is_secret: bool | None = None


class EnvVarOut(ORMModel):
    id: uuid.UUID
    key: str
    is_secret: bool
    has_value: bool = True
    created_at: datetime


# ---------------------------------------------------------------- domains

class DomainCreate(BaseModel):
    application_id: str
    hostname: str = Field(min_length=3, max_length=255)
    target_port: int | None = Field(default=None, ge=1, le=65535)
    ssl_enabled: bool = True
    is_primary: bool = False

    @field_validator("hostname")
    @classmethod
    def hostname_valid(cls, v: str) -> str:
        from ..services.traefik import validate_hostname

        error = validate_hostname(v)
        if error:
            raise ValueError(error)
        return v.strip().lower().rstrip(".")


class DomainOut(ORMModel):
    id: uuid.UUID
    application_id: uuid.UUID
    application_name: str | None = None
    application_slug: str | None = None
    hostname: str
    target_port: int | None
    ssl_enabled: bool
    ssl_status: str
    ssl_issuer: str | None
    ssl_expires_at: datetime | None
    verified_at: datetime | None
    is_primary: bool
    created_at: datetime


# ---------------------------------------------------------------- deployments

class DeploymentOut(ORMModel):
    id: uuid.UUID
    application_id: uuid.UUID
    application_name: str | None = None
    application_slug: str | None = None
    status: str
    trigger: str
    git_branch: str | None
    git_commit_sha: str | None
    git_message: str | None
    image_tag: str | None
    source_type: str | None
    project_type: str | None
    error_message: str | None
    build_duration_ms: int | None
    created_by_name: str | None
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


# ---------------------------------------------------------------- databases

DatabaseEngine = Literal["postgresql", "mysql", "mariadb", "redis", "mongodb"]


class DatabaseCreate(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    engine: DatabaseEngine
    version: str | None = Field(default=None, max_length=40)
    username: str | None = Field(default=None, max_length=120)
    database_name: str | None = Field(default=None, max_length=120)
    password: str | None = Field(default=None, max_length=200)
    published_port: int | None = Field(default=None, ge=1024, le=65535)


class DatabaseOut(ORMModel):
    id: uuid.UUID
    name: str
    engine: str
    image: str
    version: str
    username: str
    database_name: str | None
    port: int
    published_port: int | None
    container_name: str
    volume_name: str
    status: str
    last_error: str | None
    last_health_at: datetime | None
    created_at: datetime


# ---------------------------------------------------------------- networking

class TunnelCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    token: str = Field(min_length=20, max_length=1000)


class TunnelOut(ORMModel):
    id: uuid.UUID
    name: str
    status: str
    public_hostnames: list = []
    last_connected_at: datetime | None
    last_error: str | None
    created_at: datetime


class NetworkingModeUpdate(BaseModel):
    mode: Literal["public-ip", "cloudflare-tunnel"]
    public_ip: str | None = None


# ---------------------------------------------------------------- settings

class SettingValue(BaseModel):
    key: str = Field(min_length=1, max_length=120)
    value: Any = None


class SettingsUpdate(BaseModel):
    settings: list[SettingValue]
