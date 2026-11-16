import re
from pathlib import Path

from phoebe.db import Database
from phoebe.sqlsplit import split_statements

_MIGRATION_FILE = re.compile(r"^\d{3}_.+\.sql$")


# Arbitrary fixed key for the migration advisory lock.
MIGRATION_LOCK_KEY = 7_450_413_901

# `pg_advisory_xact_lock` returns `void`, which the RDS Data API cannot return as
# a result column; wrap it so the statement yields an int (the volatile call in
# the subquery is still evaluated, so the lock is taken).
MIGRATION_LOCK_SQL = "select 1 as locked from (select pg_advisory_xact_lock(:k)) s"


def _already_applied(db: Database, name: str) -> bool:
    if (
        db.fetch("select to_regclass('public.schema_migrations')::text as t")[0]["t"]
        is None
    ):
        return False
    return bool(
        db.fetch("select 1 from schema_migrations where name = :name", {"name": name})
    )


def apply_migrations(db: Database, directory: Path) -> list[str]:
    """Apply unapplied `NNN_*.sql` files in order; return the names applied."""
    has_table = (
        db.fetch("select to_regclass('public.schema_migrations')::text as t")[0]["t"]
        is not None
    )
    done = (
        {r["name"] for r in db.fetch("select name from schema_migrations")}
        if has_table
        else set()
    )
    applied: list[str] = []
    for path in sorted(p for p in directory.iterdir() if _MIGRATION_FILE.match(p.name)):
        if path.name in done:
            continue
        with db.transaction() as tx:
            # Serialise concurrent runners; the lock drops at commit/rollback.
            tx.execute(MIGRATION_LOCK_SQL, {"k": MIGRATION_LOCK_KEY})
            if _already_applied(tx, path.name):  # a runner that held the lock first
                continue
            # One statement per call: the Data API takes no multi-statement SQL.
            for statement in split_statements(path.read_text()):
                tx.execute(statement)
            tx.execute(
                "insert into schema_migrations (name) values (:name)",
                {"name": path.name},
            )
        applied.append(path.name)
    return applied
