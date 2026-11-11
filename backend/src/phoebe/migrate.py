import re
from pathlib import Path

from phoebe.db import Database

_MIGRATION_FILE = re.compile(r"^\d{3}_.+\.sql$")


def apply_migrations(db: Database, directory: Path) -> list[str]:
    """Apply unapplied `NNN_*.sql` files in order; return the names applied."""
    has_table = (
        db.fetch("select to_regclass('public.schema_migrations') as t")[0]["t"]
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
            tx.execute(path.read_text())
            tx.execute(
                "insert into schema_migrations (name) values (:name)",
                {"name": path.name},
            )
        applied.append(path.name)
    return applied
