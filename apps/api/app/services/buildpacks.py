"""Buildpack-style Dockerfile generation per detected runtime.

Nothing here is framework-specific inside the deployer — the deployer only
consumes the generated Dockerfile, making new runtimes a matter of adding a
template below.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BuildConfig:
    runtime: str
    container_port: int = 80
    install_command: str | None = None
    build_command: str | None = None
    start_command: str | None = None
    node_version: str = "22-alpine"
    python_version: str = "3.12-slim"
    php_version: str = "8.3-apache"


def _node_pkg_manager(cfg: BuildConfig, default: str = "npm") -> str:
    for pm in ("pnpm", "yarn", "bun", "npm"):
        if cfg.install_command and cfg.install_command.startswith(pm):
            return pm
    return default


def _node_stage(cfg: BuildConfig, install: str, build: str, start: str, port: int) -> str:
    return f"""\
# --- build stage -----------------------------------------------------------
FROM node:{cfg.node_version} AS build
WORKDIR /app
COPY package*.json ./
RUN {install}
COPY . .
RUN {build}

# --- runtime stage ---------------------------------------------------------
FROM node:{cfg.node_version}
WORKDIR /app
ENV NODE_ENV=production
COPY --from=build /app ./
EXPOSE {port}
CMD ["sh", "-c", "{start}"]
"""


def generate_dockerfile(cfg: BuildConfig) -> str:
    """Return a production-ready Dockerfile for the detected runtime."""
    runtime = cfg.runtime
    port = cfg.container_port

    if runtime in ("nextjs", "node", "express", "nestjs", "react", "vue", "nuxt", "angular"):
        pm = _node_pkg_manager(cfg)
        install = cfg.install_command or {
            "npm": "npm ci || npm install",
            "pnpm": "pnpm install --frozen-lockfile",
            "yarn": "yarn install --frozen-lockfile",
            "bun": "bun install",
        }[pm]
        build = cfg.build_command or ("npm run build" if pm == "npm" else f"{pm} run build")
        if runtime in ("react", "vue", "angular", "nuxt") and not cfg.start_command:
            # static SPA built output served by nginx
            out = {"react": "build", "vue": "dist", "angular": "dist", "nuxt": ".output/public"}[runtime]
            return f"""\
FROM node:{cfg.node_version} AS build
WORKDIR /app
COPY package*.json ./
RUN {install}
COPY . .
RUN {build}

FROM nginx:alpine
COPY --from=build /app/{out} /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
"""
        start = cfg.start_command or ("npm run start" if pm == "npm" else f"{pm} run start")
        return _node_stage(cfg, install, build, start, port)

    if runtime == "laravel" or runtime == "php":
        return f"""\
FROM php:{cfg.php_version}
WORKDIR /var/www/html
RUN apt-get update && apt-get install -y --no-install-recommends \\
        libzip-dev unzip \\
    && docker-php-ext-install zip pdo_mysql \\
    && rm -rf /var/lib/apt/lists/*
COPY --from=composer:2 /usr/bin/composer /usr/bin/composer
COPY composer.json composer.lock* ./
RUN composer install --no-dev --no-scripts --no-autoloader || composer install --no-scripts
COPY . .
RUN composer dump-autoload --optimize
ENV APACHE_DOCUMENT_ROOT=/var/www/html/public
RUN sed -ri -e 's!/var/www/html!${{APACHE_DOCUMENT_ROOT}}!g' \\
        /etc/apache2/sites-available/*.conf \\
        /etc/apache2/apache2.conf \\
    && a2enmod rewrite headers
EXPOSE {port}
CMD ["apache2-foreground"]
"""

    if runtime in ("fastapi", "django", "flask", "python"):
        start = cfg.start_command or {
            "fastapi": "uvicorn main:app --host 0.0.0.0 --port " + str(port),
            "django": "python manage.py runserver 0.0.0.0:" + str(port),
            "flask": "flask run --host=0.0.0.0 --port=" + str(port),
            "python": "python main.py",
        }[runtime]
        return f"""\
FROM python:{cfg.python_version}
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt* ./
RUN pip install --no-cache-dir -r requirements.txt || pip install --no-cache-dir .
COPY . .
EXPOSE {port}
CMD ["sh", "-c", "{start}"]
"""

    if runtime == "go":
        return f"""\
FROM golang:1.22-alpine AS build
WORKDIR /app
COPY go.mod go.sum* ./
RUN go mod download
COPY . .
RUN go build -o /bin/app ./...

FROM alpine:3.20
RUN adduser -D app
COPY --from=build /bin/app /bin/app
USER app
EXPOSE {port}
CMD ["/bin/app"]
"""

    if runtime in ("java", "spring-boot"):
        return f"""\
FROM maven:3.9-eclipse-temurin-21 AS build
WORKDIR /app
COPY pom.xml ./
RUN mvn -B dependency:go-offline || true
COPY . .
RUN mvn -B clean package -DskipTests

FROM eclipse-temurin:21-jre-alpine
WORKDIR /app
COPY --from=build /app/target/*.jar app.jar
EXPOSE {port}
CMD ["java", "-jar", "app.jar"]
"""

    if runtime == "ruby":
        return f"""\
FROM ruby:3.3-alpine
WORKDIR /app
RUN apk add --no-cache build-base postgresql-dev tzdata
COPY Gemfile Gemfile.lock* ./
RUN bundle install || bundle install --without development test
COPY . .
EXPOSE {port}
CMD ["sh", "-c", "{cfg.start_command or 'bundle exec puma -p ' + str(port)}"]
"""

    if runtime == "static":
        return f"""\
FROM nginx:alpine
COPY . /usr/share/nginx/html
EXPOSE {port}
CMD ["nginx", "-g", "daemon off;"]
"""

    raise ValueError(f"No buildpack template for runtime: {runtime!r}")


# Port defaults mirrored for API responses (see runtime_detect.suggest_container_port).
