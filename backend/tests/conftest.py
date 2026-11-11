import os
import tempfile
import uuid
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from phoebe.api.app import Deps, create_app
from phoebe.auth import hash_password
from phoebe.config import Settings
from phoebe.db import Database, PsycopgDatabase
from phoebe.embed import HashEmbedder
from phoebe.ingest.pipeline import index_document
from phoebe.jobs import InlineJobQueue
from phoebe.migrate import apply_migrations
from phoebe.seed import load_seed
from phoebe.sessions import InMemorySessionStore
from phoebe.storage import LocalBlobStore

ALEX = ["acme", "eng", "platform"]

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"
SEED_DIR = Path(__file__).resolve().parents[1] / "seed"

PW = "correct horse battery staple"
CSRF = {"X-Phoebe-Csrf": "1"}


@pytest.fixture(scope="session")
def _migrated_db() -> Iterator[PsycopgDatabase]:
    url = os.environ.get("PHOEBE_TEST_DATABASE_URL")
    if not url:
        pytest.skip("PHOEBE_TEST_DATABASE_URL not set")
    dbname = urlsplit(url).path.lstrip("/")
    if not dbname.endswith("_test"):
        pytest.exit(
            "Refusing to run: PHOEBE_TEST_DATABASE_URL must point at a database "
            f"whose name ends in '_test' (got {dbname!r}); the suite drops the schema.",
            returncode=2,
        )
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


def seed_completion(db: Database, person_id: str, task_id: str, done: bool) -> None:
    """Insert a seed-level completion row (session_id = '')."""
    db.execute(
        """
        insert into task_completions (person_id, task_id, session_id, done)
        values (:person_id, :task_id, '', :done)
        """,
        {"person_id": person_id, "task_id": task_id, "done": done},
    )


_TMP = tempfile.TemporaryDirectory(prefix="phoebe-tests-")
_SEED_ROOT = Path(_TMP.name) / "seed"
_SEED_ROOT.mkdir()
_BLOBS = LocalBlobStore(Path(_TMP.name) / "blobs")


def index_seed_text(
    db: Database,
    group_id: str,
    md: bytes,
    *,
    title: str = "Doc",
    session_id: str | None = None,
) -> str:
    """Insert a Markdown doc (seed, or owned when `session_id` is given) and index it."""
    name = uuid.uuid4().hex
    if session_id is None:
        (_SEED_ROOT / f"{name}.md").write_bytes(md)
        uri = f"seed://{name}.md"
    else:
        key = f"uploads/{session_id}/{name}"
        _BLOBS.put(key, md)
        uri = f"blob://{key}"
    rows = db.fetch(
        """
        insert into documents (session_id, title, doc_type, group_id, source_uri)
        values (:sid, :title, 'markdown', :group_id, :uri) returning id::text as id
        """,
        {"sid": session_id, "title": title, "group_id": group_id, "uri": uri},
    )
    doc_id = rows[0]["id"]
    index_document(db, _BLOBS, HashEmbedder(), doc_id, seed_root=_SEED_ROOT)
    return doc_id


@pytest.fixture
def client(db: PsycopgDatabase, tmp_path: Path) -> Iterator[TestClient]:
    blobs = LocalBlobStore(tmp_path / "blobs")
    embedder = HashEmbedder()
    settings = Settings(
        database_url="postgresql://unused",
        password_hash=hash_password(PW),
        cookie_secure=False,
        blob_dir=tmp_path / "blobs",
        seed_dir=SEED_DIR,
    )
    jobs = InlineJobQueue(
        lambda doc_id: index_document(
            db, blobs, embedder, doc_id, seed_root=settings.seed_dir
        )
    )
    deps = Deps(db, InMemorySessionStore(), blobs, embedder, jobs, settings)
    with TestClient(create_app(deps)) as c:
        yield c


def _login(c: TestClient) -> TestClient:
    r = c.post("/api/login", json={"password": PW}, headers=CSRF)
    assert r.status_code == 204
    return c


@pytest.fixture
def logged_in(client: TestClient) -> TestClient:
    return _login(client)


@pytest.fixture
def seeded_client(db: PsycopgDatabase, client: TestClient) -> TestClient:
    deps: Deps = client.app.state.deps  # type: ignore[attr-defined]
    load_seed(db, deps.embedder, deps.settings.seed_dir)
    return _login(client)


@pytest.fixture
def second_client(logged_in: TestClient) -> Iterator[TestClient]:
    """Another logged-in visitor on the same app, with a different cookie."""
    with TestClient(logged_in.app) as c:
        yield _login(c)
