# syntax=docker/dockerfile:1
# Build context is the repository root (the lock file lives there):
#   docker build -f backend/Dockerfile .

FROM python:3.14.7-slim-trixie AS base

RUN apt-get -o Acquire::Retries=0 update \
    && apt-get -o Acquire::Retries=0 upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

FROM base AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.8 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
# Dependencies only; the app runs from source (see PYTHONPATH below) so that
# migrations and seeds keep their repo-relative location.
RUN uv sync --locked --no-dev --no-install-project

FROM base AS runtime
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:1.1.0 /lambda-adapter /opt/extensions/lambda-adapter
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY --chmod=a+rX backend/src /app/backend/src
COPY --chmod=a+rX backend/migrations /app/backend/migrations
COPY --chmod=a+rX backend/seed /app/backend/seed
RUN mkdir -p /app/data/blobs && chown -R 10001:10001 /app/data
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/backend/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PHOEBE_SEED_DIR=/app/backend/seed \
    PHOEBE_BLOB_DIR=/app/data/blobs \
    AWS_LWA_PORT=8080 \
    AWS_LWA_READINESS_CHECK_PATH=/api/health \
    AWS_LWA_READINESS_CHECK_HEALTHY_STATUS=200
USER 10001:10001
EXPOSE 8080
CMD ["uvicorn", "phoebe.api.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log", "--no-proxy-headers"]
