from pathlib import Path
from typing import Any, Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PHOEBE_")

    # Required for db_backend="psycopg"; unused with "data_api".
    database_url: str | None = None
    db_backend: Literal["psycopg", "data_api"] = "psycopg"
    db_cluster_arn: str | None = None
    db_secret_arn: str | None = None
    db_name: str = "phoebe"
    # Empty/None only when password_hash_secret_arn supplies it (resolve_secrets).
    password_hash: str | None = None
    password_hash_secret_arn: str | None = None
    origin_secret: str | None = None
    origin_secret_arn: str | None = None
    blob_backend: Literal["local", "s3"] = "local"
    uploads_bucket: str | None = None
    job_backend: Literal["inline", "sqs"] = "inline"
    jobs_queue_url: str | None = None
    log_level: str = "INFO"
    session_backend: Literal["memory", "dynamodb"] = "memory"
    sessions_table: str | None = None
    cookie_secure: bool = True
    blob_dir: Path = Path("data/blobs")
    seed_dir: Path = Path("backend/seed")
    embedder: Literal["hash", "titan"] = "hash"
    aws_region: str = "us-east-2"
    max_chunks_per_document: int = 400
    limits_backend: Literal["memory", "dynamodb"] = "memory"
    control_backend: Literal["file", "dynamodb"] = "file"
    control_file: Path = Path("data/control.json")
    state_table: str | None = None
    kill_switch_cache_seconds: int = 5
    chat_per_session_hour: int = 30
    chat_global_day: int = 300
    uploads_per_session_day: int = 5
    uploads_global_day: int = 50
    login_per_ip_window: int = 10
    login_window_seconds: int = 900
    # At most the static body cap in api.routes_chat (4000).
    question_max_chars: int = Field(default=1000, ge=1, le=4000)
    history_exchanges: int = 3
    history_turn_max_chars: int = 2000
    answer_max_tokens: int = 700
    answer_max_chars: int = 6000
    # None: per-embedder default (see chat.service.min_similarity).
    refusal_min_similarity: float | None = None
    rewrite_max_tokens: int = 64
    answer_backend: Literal["extractive", "harness"] = "extractive"
    harness_arn: str | None = None
    rewriter_backend: Literal["heuristic", "bedrock"] = "heuristic"
    rewrite_model_id: str = "us.amazon.nova-micro-v1:0"
    guardrail_id: str | None = None
    guardrail_version: str | None = None
    client_ip_header: str | None = None


def _read_secret(client: Any, arn: str) -> str:
    try:
        value = client.get_secret_value(SecretId=arn)["SecretString"]
    except Exception:  # noqa: BLE001 - nothing chained: never echo AWS detail
        raise RuntimeError("could not read a configured secret") from None
    if not isinstance(value, str) or not value:
        raise RuntimeError("a configured secret is empty")
    return value


def resolve_secrets(settings: Settings, *, client: Any = None) -> Settings:
    """Fill `origin_secret` / `password_hash` from Secrets Manager (read once)."""
    if settings.password_hash_secret_arn and settings.password_hash:
        raise RuntimeError(
            "PHOEBE_PASSWORD_HASH must be empty when PHOEBE_PASSWORD_HASH_SECRET_ARN"
            " is set"
        )
    if not (settings.origin_secret_arn or settings.password_hash_secret_arn):
        return settings
    if client is None:
        import boto3

        client = boto3.client("secretsmanager", region_name=settings.aws_region)
    update: dict[str, str] = {}
    if settings.origin_secret_arn:
        update["origin_secret"] = _read_secret(client, settings.origin_secret_arn)
    if settings.password_hash_secret_arn:
        update["password_hash"] = _read_secret(
            client, settings.password_hash_secret_arn
        )
    return settings.model_copy(update=update)


class ControlSettings(BaseSettings):
    """Only what the control CLI and budget handler need; no DB or password."""

    model_config = SettingsConfigDict(env_prefix="PHOEBE_")

    control_backend: Literal["file", "dynamodb"] = "file"
    control_file: Path = Path("data/control.json")
    state_table: str | None = None
    sessions_table: str | None = None
    aws_region: str = "us-east-2"
    kill_switch_cache_seconds: int = 5
