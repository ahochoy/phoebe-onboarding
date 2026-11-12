from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PHOEBE_")

    database_url: str
    password_hash: str
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
    question_max_chars: int = 1000
    history_exchanges: int = 3
    history_turn_max_chars: int = 2000
    answer_max_tokens: int = 700
    answer_max_chars: int = 6000
    rewrite_max_tokens: int = 64
    answer_backend: Literal["extractive", "harness"] = "extractive"
    harness_arn: str | None = None
    rewriter_backend: Literal["heuristic", "bedrock"] = "heuristic"
    rewrite_model_id: str = "us.amazon.nova-micro-v1:0"
    guardrail_id: str | None = None
    guardrail_version: str | None = None
    client_ip_header: str | None = None


class ControlSettings(BaseSettings):
    """Only what the control CLI and budget handler need; no DB or password."""

    model_config = SettingsConfigDict(env_prefix="PHOEBE_")

    control_backend: Literal["file", "dynamodb"] = "file"
    control_file: Path = Path("data/control.json")
    state_table: str | None = None
    sessions_table: str | None = None
    aws_region: str = "us-east-2"
    kill_switch_cache_seconds: int = 5
