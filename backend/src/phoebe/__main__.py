"""Operational CLI: `python -m phoebe migrate|seed`.

Reads only PHOEBE_DATABASE_URL (and PHOEBE_SEED_DIR for seed), so it works in a
container that has no PHOEBE_PASSWORD_HASH.
"""

import os
import sys

from phoebe.db import PsycopgDatabase
from phoebe.migrate import apply_migrations
from phoebe.seed import MIGRATIONS_DIR
from phoebe.seed import main as seed_main

USAGE = "usage: python -m phoebe {migrate|seed}"


def _migrate() -> None:
    url = os.environ.get("PHOEBE_DATABASE_URL")
    if not url:
        raise SystemExit("PHOEBE_DATABASE_URL is not set")
    db = PsycopgDatabase(url)
    try:
        applied = apply_migrations(db, MIGRATIONS_DIR)
    finally:
        db.close()
    print(
        f"applied migrations: {', '.join(applied)}"
        if applied
        else "migrations up to date"
    )


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in ("migrate", "seed"):
        print(USAGE, file=sys.stderr)
        return 2
    if argv[0] == "migrate":
        _migrate()
    else:
        seed_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
