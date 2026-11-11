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
