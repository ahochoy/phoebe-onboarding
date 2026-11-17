"""Shared by `make live-check` and `make eval`: the live database guard, the
live-settings check, SSE parsing and the in-process app."""

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI

from phoebe.api.app import Deps, create_app
from phoebe.chat.models import AnswerModel, make_models
from phoebe.config import Settings
from phoebe.control import make_control
from phoebe.db import PsycopgDatabase
from phoebe.embed import make_embedder
from phoebe.jobs import InlineJobQueue
from phoebe.limits import make_counters
from phoebe.migrate import apply_migrations
from phoebe.seed import MIGRATIONS_DIR, load_seed
from phoebe.sessions import InMemorySessionStore
from phoebe.storage import LocalBlobStore

CSRF = {"X-Phoebe-Csrf": "1"}


def live_database_url(env: Any = None) -> str:
    url = (env if env is not None else os.environ).get("PHOEBE_LIVE_DATABASE_URL", "")
    if not url:
        raise SystemExit("PHOEBE_LIVE_DATABASE_URL is not set")
    name = urlparse(url).path.lstrip("/")
    if not name.endswith("_live"):
        raise SystemExit("refusing: the database name must end in _live")
    return url


def parse_sse(raw: str) -> list[tuple[str, dict[str, Any]]] | None:
    """Parse SSE frames; None if any frame is malformed (treated as a failure)."""
    out: list[tuple[str, dict[str, Any]]] = []
    for frame in raw.strip().split("\n\n"):
        head, _, data = frame.partition("\n")
        if not head.startswith("event: ") or not data.startswith("data: "):
            return None
        try:
            payload = json.loads(data.removeprefix("data: "))
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        out.append((head.removeprefix("event: "), payload))  # pyright: ignore[reportUnknownArgumentType]
    return out


def require_live_settings(settings: Settings) -> None:
    """Refuse offline defaults, which would exercise fakes and report ALL PASS."""
    missing = [
        name
        for name, ok in (
            ("PHOEBE_EMBEDDER=titan", settings.embedder == "titan"),
            ("PHOEBE_ANSWER_BACKEND=harness", settings.answer_backend == "harness"),
            ("PHOEBE_HARNESS_ARN", bool(settings.harness_arn)),
            ("PHOEBE_REWRITER_BACKEND=bedrock", settings.rewriter_backend == "bedrock"),
            ("PHOEBE_GUARDRAIL_ID", bool(settings.guardrail_id)),
            ("PHOEBE_GUARDRAIL_VERSION", bool(settings.guardrail_version)),
        )
        if not ok
    ]
    if missing:
        raise SystemExit("refusing: live settings required: " + ", ".join(missing))


def build_app(
    db: PsycopgDatabase, settings: Settings, answer: AnswerModel | None = None
) -> FastAPI:
    """Migrate and seed the live database, then the app with real components;
    `answer` replaces the configured answer model (the eval's candidates)."""
    embedder = make_embedder(settings)
    apply_migrations(db, MIGRATIONS_DIR)
    seeded = load_seed(db, embedder, settings.seed_dir)
    print(f"seeded documents={seeded.documents} chunks={seeded.chunks}")
    configured, rewriter, guardrail = make_models(settings)
    deps = Deps(
        db,
        InMemorySessionStore(),
        LocalBlobStore(Path(settings.blob_dir)),
        embedder,
        InlineJobQueue(lambda _doc_id: None),
        settings,
        counters=make_counters(settings),
        control=make_control(settings),
        answer=answer or configured,
        rewriter=rewriter,
        guardrail=guardrail,
    )
    return create_app(deps)
