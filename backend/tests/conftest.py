import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from phoebe.db import Database, PsycopgDatabase
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


def seed_org(db: Database) -> None:
    """Insert the synthetic org: acme > eng > (platform, payments), sales > sales-east."""
    db.execute(
        """
        insert into groups (id, name, kind, parent_id) values
          ('acme', 'Acme', 'company', null),
          ('eng', 'Engineering', 'department', 'acme'),
          ('sales', 'Sales', 'department', 'acme'),
          ('platform', 'Platform', 'team', 'eng'),
          ('payments', 'Payments', 'team', 'eng'),
          ('sales-east', 'Sales East', 'team', 'sales')
        """
    )
    db.execute(
        """
        insert into people (id, name, team_id, start_date, manager, buddy)
        values ('alex-rivera', 'Alex Rivera', 'platform', '2026-11-02',
                'Priya Nair', 'Sam Okafor')
        """
    )


def make_task(
    db: Database,
    *,
    group_id: str,
    title: str = "Task",
    session_id: str | None = None,
) -> str:
    rows = db.fetch(
        """
        insert into tasks (title, group_id, session_id)
        values (:title, :group_id, :session_id) returning id::text as id
        """,
        {"title": title, "group_id": group_id, "session_id": session_id},
    )
    return rows[0]["id"]


def make_seed_doc(
    db: Database, *, group_id: str = "platform", title: str = "Doc"
) -> str:
    rows = db.fetch(
        """
        insert into documents (title, doc_type, group_id, source_uri, status)
        values (:title, 'markdown', :group_id, 'seed://doc', 'indexed')
        returning id::text as id
        """,
        {"title": title, "group_id": group_id},
    )
    return rows[0]["id"]
