import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from phoebe.db import PsycopgDatabase
from phoebe.migrate import apply_migrations

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


@pytest.fixture(scope="session")
def _migrated_db() -> Iterator[PsycopgDatabase]:
    url = os.environ.get("PHOEBE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("PHOEBE_TEST_DATABASE_URL not set")
    database = PsycopgDatabase(url)
    database.execute("drop schema public cascade")
    database.execute("create schema public")
    apply_migrations(database, MIGRATIONS_DIR)
    yield database
    database.close()


@pytest.fixture
def db(_migrated_db: PsycopgDatabase) -> Iterator[PsycopgDatabase]:
    yield _migrated_db
    tables = _migrated_db.fetch(
        "select tablename from pg_tables where schemaname = 'public' and tablename <> 'schema_migrations'"
    )
    if tables:
        names = ", ".join(f'public."{t["tablename"]}"' for t in tables)
        _migrated_db.execute(f"truncate {names} cascade")
