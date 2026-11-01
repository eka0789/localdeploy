"""Runtime / framework detection from project files.

Pure and testable: works on a plain list of relative file paths plus an
optional content reader (so tests can run without a filesystem).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Callable

ReadText = Callable[[str], str | None]

RUNTIMES = [
    "laravel", "php", "nextjs", "nuxt", "react", "vue", "angular", "node",
    "nestjs", "express", "fastapi", "django", "flask", "python", "go",
    "java", "spring-boot", "ruby", "static", "dockerfile", "compose",
]


@dataclass
class Detection:
    runtime: str
    confidence: float = 0.0
    details: dict = field(default_factory=dict)


def _read_json(reader: ReadText, path: str) -> dict | None:
    raw = reader(path)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, ValueError):
        return None


def _has_file(files: list[str], name: str) -> bool:
    return any(f.lower() == name.lower() or f.lower().endswith("/" + name.lower()) for f in files)


def _has_ext(files: list[str], ext: str) -> bool:
    return any(f.lower().endswith(ext) for f in files)


def _detect_node(files: list[str], reader: ReadText) -> Detection | None:
    pkg = _read_json(reader, "package.json") or {}
    if not pkg and not _has_file(files, "package.json"):
        return None
    deps: dict = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    scripts: dict = pkg.get("scripts") or {}
    details = {
        "package_manager": "pnpm" if _has_file(files, "pnpm-lock.yaml")
        else "yarn" if _has_file(files, "yarn.lock")
        else "bun" if _has_file(files, "bun.lockb")
        else "npm",
        "scripts": list(scripts.keys()),
    }

    def has(dep: str) -> bool:
        return dep in deps

    if "next" in deps:
        return Detection("nextjs", 0.95, details)
    if has("@angular/core"):
        return Detection("angular", 0.9, details)
    if has("nuxt") or has("nuxt3"):
        return Detection("nuxt", 0.9, details)
    if has("@nestjs/core"):
        return Detection("nestjs", 0.9, details)
    if has("react"):
        return Detection("react", 0.85, details)
    if has("vue"):
        return Detection("vue", 0.85, details)
    if has("express") or has("fastify") or has("koa"):
        return Detection("express", 0.8, details)
    return Detection("node", 0.7, details)


def _detect_python(files: list[str], reader: ReadText) -> Detection:
    req = reader("requirements.txt") or ""
    pyproject = reader("pyproject.toml") or ""
    combined = (req + "\n" + pyproject).lower()
    if _has_file(files, "manage.py") or "django" in combined:
        return Detection("django", 0.9, {"requirements": True})
    if "fastapi" in combined:
        return Detection("fastapi", 0.9, {"requirements": True})
    if "flask" in combined:
        return Detection("flask", 0.85, {"requirements": True})
    return Detection("python", 0.7, {"requirements": bool(req) or bool(pyproject)})


def detect_runtime(files: list[str], reader: ReadText) -> Detection:
    """Detect the project runtime from the source tree listing."""
    files = [f.replace("\\", "/") for f in files]

    if _has_file(files, "docker-compose.yml") or _has_file(files, "docker-compose.yaml") or _has_file(files, "compose.yml"):
        compose = _read_json(reader, "docker-compose.yml")
        _ = compose  # compose deployments keep their own definition
        if _has_file(files, "dockerfile"):
            pass
        return Detection("compose", 1.0, {"compose_file": True})

    if _has_file(files, "dockerfile"):
        return Detection("dockerfile", 1.0, {})

    # PHP family
    composer = _read_json(reader, "composer.json") or {}
    require = composer.get("require") or {}
    if "laravel/framework" in require or "laravel/lumen-framework" in require:
        return Detection("laravel", 0.95, {"php_version": require.get("php", ">=8.1")})
    if require or _has_file(files, "composer.json") or _has_ext(files, ".php"):
        return Detection("php", 0.8, {})

    node = _detect_node(files, reader)
    if node:
        return node

    if _has_file(files, "go.mod"):
        go_version = ""
        raw = reader("go.mod") or ""
        match = re.search(r"^go\s+(\d+\.\d+)", raw, re.MULTILINE)
        if match:
            go_version = match.group(1)
        return Detection("go", 0.95, {"go_version": go_version or "1.22"})

    if _has_file(files, "pom.xml") or _has_file(files, "build.gradle") or _has_file(files, "build.gradle.kts"):
        raw = (reader("pom.xml") or "") + (reader("build.gradle") or "")
        if "spring-boot" in raw:
            return Detection("spring-boot", 0.9, {})
        return Detection("java", 0.8, {})

    if _has_file(files, "requirements.txt") or _has_file(files, "pyproject.toml") or _has_ext(files, ".py"):
        return _detect_python(files, reader)

    if _has_file(files, "gemfile") or _has_file(files, "gemfile.lock") or _has_file(files, "config.ru"):
        return Detection("ruby", 0.8, {})

    if _has_ext(files, ".html") or _has_file(files, "index.htm"):
        return Detection("static", 0.9, {})

    return Detection("unknown", 0.0, {})


def suggest_health_check_path(runtime: str) -> str:
    return {
        "nextjs": "/",
        "react": "/",
        "vue": "/",
        "angular": "/",
        "static": "/",
    }.get(runtime, "/")


def suggest_container_port(runtime: str) -> int:
    return {
        "nextjs": 3000,
        "nuxt": 3000,
        "node": 3000,
        "express": 3000,
        "nestjs": 3000,
        "react": 3000,
        "vue": 8080,
        "angular": 80,
        "php": 80,
        "laravel": 80,
        "static": 80,
        "fastapi": 8000,
        "django": 8000,
        "flask": 5000,
        "python": 8000,
        "go": 8080,
        "java": 8080,
        "spring-boot": 8080,
        "ruby": 3000,
    }.get(runtime, 80)
