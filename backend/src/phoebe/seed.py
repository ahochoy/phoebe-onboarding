"""Load the Larkspur Labs seed company (groups, people, tasks, documents).

CLI: `uv run python -m phoebe.seed` (wired to `make seed`). It reads only
`PHOEBE_DATABASE_URL` (required) and `PHOEBE_SEED_DIR` (default `backend/seed`)
from the environment, so it does not need `PHOEBE_PASSWORD_HASH` the way the
full app `Settings` does. It applies migrations first, then loads the seed.
"""

import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

from phoebe.db import Database, PsycopgDatabase
from phoebe.embed import Embedder, HashEmbedder
from phoebe.ingest.pipeline import index_document
from phoebe.migrate import apply_migrations
from phoebe.storage import LocalBlobStore

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


@dataclass(frozen=True)
class SeedReport:
    groups: int
    people: int
    tasks: int
    documents: int
    chunks: int


def _clear_seed(tx: Database) -> None:
    """Delete seed rows in FK-safe order (visitor rows are left alone)."""
    tx.execute("delete from task_completions where session_id = ''")
    tx.execute("delete from tasks where session_id is null")
    tx.execute("delete from documents where session_id is null")  # chunks cascade
    tx.execute("delete from people")
    for kind in ("team", "department", "company"):
        tx.execute(
            "delete from groups where session_id is null and kind = :kind",
            {"kind": kind},
        )


def _insert_groups(tx: Database, manifest: dict[str, Any]) -> int:
    company = manifest["company"]
    rows = [(company["id"], company["name"], "company", None)]
    rows += [
        (d["id"], d["name"], "department", company["id"])
        for d in manifest["departments"]
    ]
    rows += [(t["id"], t["name"], "team", t["parent"]) for t in manifest["teams"]]
    for gid, name, kind, parent in rows:  # parents are listed before children
        tx.execute(
            "insert into groups (id, name, kind, parent_id) "
            "values (:id, :name, :kind, :parent)",
            {"id": gid, "name": name, "kind": kind, "parent": parent},
        )
    return len(rows)


def _insert_tasks(tx: Database, manifest: dict[str, Any]) -> dict[str, str]:
    ids: dict[str, str] = {}
    for t in manifest["tasks"]:
        rows = tx.fetch(
            """
            insert into tasks (title, description, link, group_id, position)
            values (:title, :description, :link, :group, :position)
            returning id::text as id
            """,
            {
                "title": t["title"],
                "description": t.get("description", ""),
                "link": t.get("link"),
                "group": t["group"],
                "position": t["position"],
            },
        )
        ids[t["key"]] = rows[0]["id"]
    return ids


def _insert_people(
    tx: Database, manifest: dict[str, Any], task_ids: dict[str, str]
) -> int:
    for p in manifest["people"]:
        tx.execute(
            """
            insert into people (id, name, team_id, start_date, manager, buddy)
            values (:id, :name, :team, :start, :manager, :buddy)
            """,
            {
                "id": p["id"],
                "name": p["name"],
                "team": p["team"],
                "start": p["start_date"],
                "manager": p.get("manager"),
                "buddy": p.get("buddy"),
            },
        )
        for key in p.get("completed", []):
            tx.execute(
                """
                insert into task_completions (person_id, task_id, session_id, done)
                values (:pid, :tid::uuid, '', true)
                """,
                {"pid": p["id"], "tid": task_ids[key]},  # KeyError = bad manifest
            )
    return len(manifest["people"])


def _insert_documents(tx: Database, manifest: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for d in manifest["documents"]:
        last_updated: date | None = d.get("last_updated")
        rows = tx.fetch(
            """
            insert into documents
              (title, purpose, last_updated, doc_type, group_id, source_uri, public_url)
            values (:title, :purpose, :updated, :doc_type, :group, :source, :url)
            returning id::text as id
            """,
            {
                "title": d["title"],
                "purpose": d.get("purpose", ""),
                "updated": last_updated,
                "doc_type": d["doc_type"],
                "group": d["group"],
                "source": d["source"],
                "url": d.get("public_url"),
            },
        )
        ids.append(rows[0]["id"])
    return ids


def load_seed(db: Database, embedder: Embedder, seed_dir: Path) -> SeedReport:
    """Replace all seed rows with the contents of `seed_dir/manifest.yaml`.

    Idempotent. Delete and insert run in one transaction; documents are then
    indexed outside it. Seed documents are read from `seed_dir` (`seed://`).

    Limitation: visitor (sandbox) rows are not deleted, but they may reference
    seed groups, tasks or people by foreign key, which would make a reload
    fail while visitors exist. Run the seed on an empty or freshly reset DB.
    """
    manifest = yaml.safe_load((seed_dir / "manifest.yaml").read_text(encoding="utf-8"))
    with db.transaction() as tx:
        _clear_seed(tx)
        groups = _insert_groups(tx, manifest)
        task_ids = _insert_tasks(tx, manifest)
        people = _insert_people(tx, manifest, task_ids)
        doc_ids = _insert_documents(tx, manifest)
    with tempfile.TemporaryDirectory(prefix="phoebe-seed-") as blob_dir:
        blobs = LocalBlobStore(Path(blob_dir))  # seeds never read blobs
        for doc_id in doc_ids:
            index_document(db, blobs, embedder, doc_id, seed_root=seed_dir)
    failed = db.fetch(
        "select title, failure_reason from documents "
        "where session_id is null and status <> 'indexed'"
    )
    if failed:
        raise RuntimeError(
            "seed documents failed to index: "
            + ", ".join(f"{r['title']} ({r['failure_reason']})" for r in failed)
        )
    chunks = db.fetch(
        "select count(*) as n from chunks c join documents d on d.id = c.document_id "
        "where d.session_id is null"
    )[0]["n"]
    return SeedReport(
        groups=groups,
        people=people,
        tasks=len(task_ids),
        documents=len(doc_ids),
        chunks=chunks,
    )


class _SeedSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PHOEBE_", extra="ignore")

    database_url: str
    seed_dir: Path = Path("backend/seed")


def main() -> None:
    settings = _SeedSettings()  # pyright: ignore[reportCallIssue]
    db = PsycopgDatabase(settings.database_url)
    try:
        applied = apply_migrations(db, MIGRATIONS_DIR)
        if applied:
            print(f"applied migrations: {', '.join(applied)}")
        report = load_seed(db, HashEmbedder(), settings.seed_dir)
    finally:
        db.close()
    print(
        f"seeded groups={report.groups} people={report.people} "
        f"tasks={report.tasks} documents={report.documents} chunks={report.chunks}"
    )


if __name__ == "__main__":
    main()
