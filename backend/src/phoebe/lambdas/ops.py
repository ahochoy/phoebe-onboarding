"""Operator tasks, invoked by hand: `{"task": "migrate" | "seed_if_empty" | "status"}`."""

import logging
from dataclasses import asdict
from typing import Any

from phoebe.api.app import startup_check_embedder
from phoebe.lambdas import runtime
from phoebe.migrate import apply_migrations
from phoebe.seed import MIGRATIONS_DIR, load_seed

log = logging.getLogger(__name__)


def _seed_groups(db: Any) -> int:
    return db.fetch("select count(*) as n from groups where session_id is null")[0]["n"]


def handler(event: Any, context: Any = None) -> dict[str, Any]:
    task = event.get("task") if isinstance(event, dict) else None
    if task not in ("migrate", "seed_if_empty", "status"):
        return {"error": "unknown_task"}
    d = runtime.deps()
    if task == "migrate":
        applied = apply_migrations(d.db, MIGRATIONS_DIR)
        log.info("migrate applied=%d", len(applied))
        return {"applied": applied}
    if task == "seed_if_empty":
        # The one handler that checks the embedder (the API checks lazily).
        startup_check_embedder(d.db, d.embedder)
        # Never wipes: any existing seed group means the seed is already loaded.
        if _seed_groups(d.db) > 0:
            log.info("seed_if_empty skipped")
            return {"seeded": False}
        report = load_seed(d.db, d.embedder, d.settings.seed_dir)
        log.info("seed_if_empty seeded documents=%d", report.documents)
        return {"seeded": True, **asdict(report)}
    has_table = d.db.fetch("select to_regclass('public.schema_migrations')::text as t")[
        0
    ]["t"]
    if has_table is None:
        return {"migrations": 0, "seed_groups": 0}
    migrations = d.db.fetch("select count(*) as n from schema_migrations")[0]["n"]
    return {"migrations": migrations, "seed_groups": _seed_groups(d.db)}
