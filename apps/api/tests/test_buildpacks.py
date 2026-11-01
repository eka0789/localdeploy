"""Buildpack Dockerfile generation tests."""
import pytest

from app.services.buildpacks import BuildConfig, generate_dockerfile


def test_node_buildpack_structure():
    cfg = BuildConfig(runtime="nextjs", container_port=3000)
    dockerfile = generate_dockerfile(cfg)
    assert "FROM node:22-alpine AS build" in dockerfile
    assert "npm ci || npm install" in dockerfile
    assert "EXPOSE 3000" in dockerfile
    assert "CMD [" in dockerfile


def test_react_static_serving():
    cfg = BuildConfig(runtime="react", container_port=80)
    dockerfile = generate_dockerfile(cfg)
    assert "nginx:alpine" in dockerfile
    assert "/usr/share/nginx/html" in dockerfile


def test_php_laravel_buildpack():
    cfg = BuildConfig(runtime="laravel", container_port=80)
    dockerfile = generate_dockerfile(cfg)
    assert "composer" in dockerfile
    assert "APACHE_DOCUMENT_ROOT=/var/www/html/public" in dockerfile


def test_python_buildpack():
    cfg = BuildConfig(runtime="fastapi", container_port=8000)
    dockerfile = generate_dockerfile(cfg)
    assert "pip install" in dockerfile
    assert "uvicorn main:app" in dockerfile
    assert "EXPOSE 8000" in dockerfile


def test_go_buildpack_multi_stage():
    cfg = BuildConfig(runtime="go", container_port=8080)
    dockerfile = generate_dockerfile(cfg)
    assert "golang:1.22-alpine AS build" in dockerfile
    assert "go build" in dockerfile
    assert "USER app" in dockerfile


def test_static_buildpack():
    cfg = BuildConfig(runtime="static", container_port=80)
    dockerfile = generate_dockerfile(cfg)
    assert "nginx:alpine" in dockerfile


def test_unknown_runtime_raises():
    with pytest.raises(ValueError):
        generate_dockerfile(BuildConfig(runtime="cobol"))
