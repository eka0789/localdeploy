# LocalDeploy API image
# NOTE: build context must be the repository root so the app package is present:
#   docker build -f infrastructure/docker/api.Dockerfile .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# git is required by the deployment engine (cloning repositories)
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY apps/api/pyproject.toml ./
COPY apps/api/app ./app
COPY apps/api/alembic.ini ./
COPY apps/api/alembic ./alembic

RUN pip install --no-cache-dir .

EXPOSE 8000

# Bootstrap (schema + seed) happens on startup; migrations via alembic when needed.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
