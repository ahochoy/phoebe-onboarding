"""Operational CLI: `python -m phoebe migrate|seed|control`.

migrate and seed read only PHOEBE_DATABASE_URL (and PHOEBE_SEED_DIR for seed);
control reads only the PHOEBE_CONTROL_* / state-table settings. None needs
PHOEBE_PASSWORD_HASH.
"""

import os
import sys

from phoebe.config import ControlSettings
from phoebe.control import STATES, make_inner_control
from phoebe.db import PsycopgDatabase
from phoebe.migrate import apply_migrations
from phoebe.seed import MIGRATIONS_DIR
from phoebe.seed import main as seed_main

USAGE = (
    "usage: python -m phoebe {migrate|seed}"
    " | python -m phoebe control {open|chat_paused|closed|status}"
)


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


def _control(action: str) -> None:
    store = make_inner_control(ControlSettings())
    if action != "status":
        store.set(action)  # type: ignore[arg-type]
    print(store.get())


def main(argv: list[str]) -> int:
    if argv[:1] == ["control"]:
        if len(argv) != 2 or argv[1] not in (*STATES, "status"):
            print(USAGE, file=sys.stderr)
            return 2
        _control(argv[1])
        return 0
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
