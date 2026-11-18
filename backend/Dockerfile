# syntax=docker/dockerfile:1
# Build context is the repository root (the lock file lives there). Two final
# targets share one build and one runtime base (ruling R9):
#   docker build -f backend/Dockerfile --target api .   # API Lambda + local stack (default)
#   docker build -f backend/Dockerfile --target jobs .  # worker, DLQ, sweeper, ops, budget

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

FROM base AS runtime-base
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY --chmod=a+rX backend/src /app/backend/src
COPY --chmod=a+rX backend/migrations /app/backend/migrations
COPY --chmod=a+rX backend/seed /app/backend/seed
# The answer system prompt, read by the converse backend at startup.
COPY --chmod=a+rX backend/prompts /app/backend/prompts
RUN mkdir -p /app/data/blobs && chown -R 10001:10001 /app/data
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH=/app/backend/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PHOEBE_SEED_DIR=/app/backend/seed \
    PHOEBE_BLOB_DIR=/app/data/blobs
USER 10001:10001

# Non-HTTP Lambdas. No Lambda Web Adapter: Lambda starts every extension in
# /opt/extensions, and the adapter would wait on :8080 and race awslambdaric
# for invocations. The Lambda passes the handler as its command.
FROM runtime-base AS jobs
ENTRYPOINT ["python", "-m", "awslambdaric"]
CMD ["phoebe.lambdas.ops.handler"]

# API Lambda (uvicorn behind the Lambda Web Adapter) and the local stack.
# Kept last so a build without --target produces it.
FROM runtime-base AS api
COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:1.1.0 /lambda-adapter /opt/extensions/lambda-adapter
ENV AWS_LWA_PORT=8080 \
    AWS_LWA_READINESS_CHECK_PATH=/api/health \
    AWS_LWA_READINESS_CHECK_HEALTHY_STATUS=200
EXPOSE 8080
CMD ["uvicorn", "phoebe.api.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log", "--no-proxy-headers"]
