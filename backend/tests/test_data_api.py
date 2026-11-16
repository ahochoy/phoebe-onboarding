import json
import uuid
from collections.abc import Callable, Mapping
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from conftest import make_seed_doc, make_task, seed_org
from phoebe.api.app import make_database
from phoebe.config import Settings
from phoebe.db import Database, DatabaseUnavailable, PsycopgDatabase
from phoebe.db_data_api import DataApiDatabase, encode_params
from phoebe.documents import (
    DocumentPatch,
    delete_document,
    get_document,
    mark_failed,
    mark_indexed,
    update_document,
)
from phoebe.migrate import MIGRATION_LOCK_KEY, apply_migrations
from phoebe.tasks import TaskPatch, delete_task, update_task

CLUSTER = "arn:aws:rds:us-east-2:111122223333:cluster:phoebe"
SECRET = "arn:aws:secretsmanager:us-east-2:111122223333:secret:phoebe"


def client_error(code: str, op: str = "ExecuteStatement") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "x"}}, op)


def records(*rows: Mapping[str, Any]) -> dict[str, Any]:
    return {"formattedRecords": json.dumps(list(rows)), "numberOfRecordsUpdated": 0}


class FakeRds:
    """Records rds-data calls. Responses come from `script` (a queue of dicts or
    exceptions) or, if given, `handler(op, kwargs)`."""

    def __init__(
        self,
        *script: Any,
        handler: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> None:
        self.script = list(script)
        self.handler = handler
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _call(self, op: str, kwargs: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((op, kwargs))
        if self.handler is not None:
            item = self.handler(op, kwargs)
        elif self.script:
            item = self.script.pop(0)
        else:
            item = {
                "BeginTransaction": {"transactionId": "tx-1"},
                "ExecuteStatement": records(),
            }.get(op, {})
        if isinstance(item, Exception):
            raise item
        return item

    def execute_statement(self, **kw: Any) -> dict[str, Any]:
        return self._call("ExecuteStatement", kw)

    def begin_transaction(self, **kw: Any) -> dict[str, Any]:
        return self._call("BeginTransaction", kw)

    def commit_transaction(self, **kw: Any) -> dict[str, Any]:
        return self._call("CommitTransaction", kw)

    def rollback_transaction(self, **kw: Any) -> dict[str, Any]:
        return self._call("RollbackTransaction", kw)

    def ops(self) -> list[str]:
        return [op for op, _ in self.calls]


def make_db(
    client: FakeRds, sleeps: list[float] | None = None, **kw: Any
) -> DataApiDatabase:
    sink = sleeps if sleeps is not None else []
    return DataApiDatabase(
        CLUSTER, SECRET, "phoebe", client=client, sleep=sink.append, **kw
    )


# ---- parameter encoding ---------------------------------------------------


def test_named_params_pass_through() -> None:
    fake = FakeRds()
    sql = "select * from t where g = any(:gids::text[]) and e = :emb::vector"
    make_db(fake).fetch(sql, {"gids": ["a"], "emb": "[1,2]"})
    op, kw = fake.calls[0]
    assert op == "ExecuteStatement"
    assert kw["sql"] == sql
    assert kw["resourceArn"] == CLUSTER
    assert kw["secretArn"] == SECRET
    assert kw["database"] == "phoebe"
    assert kw["parameters"] == [
        {"name": "gids", "value": {"stringValue": '{"a"}'}},
        {"name": "emb", "value": {"stringValue": "[1,2]"}},
    ]
    assert "transactionId" not in kw


def test_param_types() -> None:
    uid = uuid.uuid4()
    aware = datetime(2026, 11, 16, 9, 30, 5, 123, tzinfo=timezone(timedelta(hours=2)))
    by_name = {
        p["name"]: p
        for p in encode_params(
            {
                "s": "hi",
                "i": 7,
                "f": 1.5,
                "b": True,
                "n": None,
                "u": uid,
                "d": date(2026, 11, 16),
                "ts": aware,
                "obj": {"a": [1, "x"]},
                "objs": [{"a": 1}, {"b": 2}],
            }
        )
    }
    assert by_name["s"] == {"name": "s", "value": {"stringValue": "hi"}}
    assert by_name["i"]["value"] == {"longValue": 7}
    assert by_name["f"]["value"] == {"doubleValue": 1.5}
    assert by_name["b"]["value"] == {"booleanValue": True}
    assert by_name["n"]["value"] == {"isNull": True}
    assert by_name["u"]["value"] == {"stringValue": str(uid)}
    assert by_name["u"]["typeHint"] == "UUID"
    assert by_name["d"]["value"] == {"stringValue": "2026-11-16"}
    assert by_name["d"]["typeHint"] == "DATE"
    # Timestamps are normalised to UTC (the Data API takes no offset).
    assert by_name["ts"]["value"] == {"stringValue": "2026-11-16 07:30:05.000123"}
    assert by_name["ts"]["typeHint"] == "TIMESTAMP"
    assert json.loads(by_name["obj"]["value"]["stringValue"]) == {"a": [1, "x"]}
    assert json.loads(by_name["objs"]["value"]["stringValue"]) == [{"a": 1}, {"b": 2}]
    assert "typeHint" not in by_name["s"]


def test_list_params_become_pg_array_literals() -> None:
    by_name = {
        p["name"]: p
        for p in encode_params(
            {
                "xs": ["a", "b,c", 'd"e'],
                "ys": ["back\\slash", None],
                "ns": [1, 2.5, True],
                "empty": [],
                "none": None,
            }
        )
    }
    assert by_name["xs"]["value"] == {"stringValue": '{"a","b,c","d\\"e"}'}
    assert by_name["ys"]["value"] == {"stringValue": '{"back\\\\slash",NULL}'}
    assert by_name["ns"]["value"] == {"stringValue": "{1,2.5,true}"}
    assert by_name["empty"]["value"] == {"stringValue": "{}"}
    assert by_name["none"]["value"] == {"isNull": True}


def test_unsupported_param_type_is_rejected() -> None:
    with pytest.raises(TypeError):
        encode_params({"x": object()})


# ---- results --------------------------------------------------------------


def test_rows_decoded_from_json_records() -> None:
    fake = FakeRds(records({"id": "a", "n": 1}, {"id": "b", "n": 2}))
    rows = make_db(fake).fetch("select id, n from t")
    assert rows == [{"id": "a", "n": 1}, {"id": "b", "n": 2}]
    kw = fake.calls[0][1]
    assert kw["formatRecordsAs"] == "JSON"
    assert kw["includeResultMetadata"] is True


def test_empty_result_without_records() -> None:
    assert make_db(FakeRds({"numberOfRecordsUpdated": 1})).fetch("select 1") == []


def test_json_columns_are_decoded_using_result_metadata() -> None:
    fake = FakeRds(
        {
            "formattedRecords": json.dumps(
                [{"sections": '[{"a": 1}]', "title": '{"not": "json column"}'}]
            ),
            "columnMetadata": [
                {"name": "sections", "typeName": "jsonb"},
                {"name": "title", "typeName": "text"},
            ],
        }
    )
    row = make_db(fake).fetch("select sections, title from t")[0]
    assert row["sections"] == [{"a": 1}]
    assert row["title"] == '{"not": "json column"}'


def test_execute_returns_number_of_records_updated() -> None:
    fake = FakeRds({"numberOfRecordsUpdated": 3})
    assert make_db(fake).execute("delete from t where x = :x", {"x": 1}) == 3
    assert "formatRecordsAs" not in fake.calls[0][1]


# ---- transactions ---------------------------------------------------------


def test_transaction_commits_and_rolls_back() -> None:
    fake = FakeRds()
    db = make_db(fake)
    with db.transaction() as tx:
        tx.execute("insert into t values (:a)", {"a": 1})
        tx.fetch("select 1")
    assert fake.ops() == [
        "BeginTransaction",
        "ExecuteStatement",
        "ExecuteStatement",
        "CommitTransaction",
    ]
    begin = fake.calls[0][1]
    assert (begin["resourceArn"], begin["secretArn"], begin["database"]) == (
        CLUSTER,
        SECRET,
        "phoebe",
    )
    assert all(kw["transactionId"] == "tx-1" for _, kw in fake.calls[1:3])
    assert fake.calls[3][1]["transactionId"] == "tx-1"

    fake = FakeRds()
    db = make_db(fake)
    with pytest.raises(ValueError, match="boom"), db.transaction() as tx:
        tx.execute("insert into t values (1)")
        raise ValueError("boom")
    assert fake.ops() == ["BeginTransaction", "ExecuteStatement", "RollbackTransaction"]
    assert fake.calls[2][1]["transactionId"] == "tx-1"


def test_failed_rollback_does_not_mask_the_original_error() -> None:
    fake = FakeRds()
    db = make_db(fake)

    def handler(op: str, kw: dict[str, Any]) -> Any:
        if op == "RollbackTransaction":
            return client_error("TransactionNotFoundException", op)
        return {"transactionId": "tx-1"} if op == "BeginTransaction" else records()

    fake.handler = handler
    with pytest.raises(ValueError, match="boom"), db.transaction():
        raise ValueError("boom")


def test_top_level_calls_outside_a_transaction_carry_no_transaction_id() -> None:
    fake = FakeRds()
    db = make_db(fake)
    with db.transaction() as tx:
        tx.execute("select 1")
    db.execute("select 2")
    assert "transactionId" not in fake.calls[-1][1]


# ---- resume retries -------------------------------------------------------


def test_retries_while_resuming() -> None:
    sleeps: list[float] = []
    fake = FakeRds(
        client_error("DatabaseResumingException"),
        client_error("DatabaseResumingException"),
        records({"n": 1}),
    )
    assert make_db(fake, sleeps).fetch("select 1 as n") == [{"n": 1}]
    assert fake.ops() == ["ExecuteStatement"] * 3
    assert len(sleeps) == 2
    assert 0 < sleeps[0] < sleeps[1]


def test_resuming_writes_are_retried_too() -> None:
    # A resuming cluster has not run the statement, so a write is safe to resend.
    fake = FakeRds(
        client_error("DatabaseResumingException"), {"numberOfRecordsUpdated": 1}
    )
    assert make_db(fake).execute("delete from t") == 1


def test_still_resuming_after_timeout_raises_database_unavailable() -> None:
    sleeps: list[float] = []
    fake = FakeRds(handler=lambda op, kw: client_error("DatabaseResumingException"))
    with pytest.raises(DatabaseUnavailable):
        make_db(fake, sleeps, resume_timeout_s=10.0).fetch("select 1")
    assert sum(sleeps) <= 10.0
    assert len(fake.calls) == len(sleeps) + 1


def test_statement_timeout_retried_for_reads_only() -> None:
    fake = FakeRds(client_error("StatementTimeoutException"), records({"n": 1}))
    assert make_db(fake).fetch("select 1 as n") == [{"n": 1}]
    assert len(fake.calls) == 2

    fake = FakeRds(
        client_error("StatementTimeoutException"), client_error("AnythingElse")
    )
    with pytest.raises(ClientError, match="StatementTimeout"):
        make_db(fake).fetch("insert into t values (1) returning id")
    assert len(fake.calls) == 1

    fake = FakeRds(client_error("StatementTimeoutException"))
    with pytest.raises(ClientError):
        make_db(fake).execute("update t set x = 1")
    assert len(fake.calls) == 1


def test_no_statement_retries_inside_a_transaction() -> None:
    fake = FakeRds(
        {"transactionId": "tx-1"},
        client_error("StatementTimeoutException"),
        {},
    )
    db = make_db(fake)
    with pytest.raises(ClientError), db.transaction() as tx:
        tx.fetch("select 1")
    assert fake.ops() == ["BeginTransaction", "ExecuteStatement", "RollbackTransaction"]


def test_resuming_inside_a_transaction_is_unavailable_not_retried() -> None:
    fake = FakeRds({"transactionId": "tx-1"}, client_error("DatabaseResumingException"))
    with pytest.raises(DatabaseUnavailable), make_db(fake).transaction() as tx:
        tx.execute("insert into t values (1)")
    assert fake.ops() == ["BeginTransaction", "ExecuteStatement", "RollbackTransaction"]


def test_begin_transaction_waits_for_a_resuming_database() -> None:
    sleeps: list[float] = []
    fake = FakeRds(
        client_error("DatabaseResumingException", "BeginTransaction"),
        {"transactionId": "tx-9"},
    )
    with make_db(fake, sleeps).transaction() as tx:
        tx.execute("select 1")
    assert len(sleeps) == 1
    assert fake.calls[2][1]["transactionId"] == "tx-9"


@pytest.mark.parametrize(
    "code",
    [
        "DatabaseUnavailableException",
        "ServiceUnavailableError",
        "InternalServerErrorException",
    ],
)
def test_other_outage_codes_are_unavailable_without_retry(code: str) -> None:
    fake = FakeRds(client_error(code))
    with pytest.raises(DatabaseUnavailable):
        make_db(fake).fetch("select 1")
    assert len(fake.calls) == 1


def test_sql_errors_pass_through_unchanged() -> None:
    fake = FakeRds(client_error("BadRequestException"))
    with pytest.raises(ClientError):
        make_db(fake).fetch("select nope")


# ---- sliced text ----------------------------------------------------------

DOC_ID = str(uuid.uuid4())
SLICE = 200_000


def _detail_row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": DOC_ID,
        "title": "T",
        "purpose": "",
        "last_updated": "2026-11-16",
        "doc_type": "markdown",
        "group_id": "platform",
        "group_name": "Platform",
        "group_kind": "team",
        "status": "indexed",
        "failure_reason": None,
        "source_uri": "seed://x",
        "public_url": None,
        "owned": False,
        "full_text": None,
        "sections": '[{"heading": "H"}]',
    }
    return row | over


def _doc_handler(text: str | None, slices: list[int]) -> Callable[..., Any]:
    def handler(op: str, kw: dict[str, Any]) -> Any:
        assert op == "ExecuteStatement"
        sql = kw["sql"]
        params = {p["name"]: p["value"] for p in kw["parameters"]}
        if "substr(full_text, :off, 200000)" in sql:
            off = params["off"]["longValue"]
            slices.append(off)
            part = None if text is None else text[off - 1 : off - 1 + SLICE]
            return records({"part": part})
        assert "raw.full_text" not in sql, "full_text must not ride the detail query"
        return {
            **records(_detail_row()),
            "columnMetadata": [{"name": "sections", "typeName": "jsonb"}],
        }

    return handler


def test_large_text_is_fetched_in_slices() -> None:
    text = "".join(chr(97 + i % 26) for i in range(2 * SLICE + 50_000))
    slices: list[int] = []
    fake = FakeRds(handler=_doc_handler(text, slices))
    doc = get_document(make_db(fake), "sid", DOC_ID)
    assert doc is not None
    assert doc.full_text == text
    assert doc.sections == [{"heading": "H"}]
    assert slices == [1, SLICE + 1, 2 * SLICE + 1]


def test_exact_multiple_of_slice_size_terminates() -> None:
    text = "x" * SLICE
    slices: list[int] = []
    doc = get_document(
        make_db(FakeRds(handler=_doc_handler(text, slices))), "s", DOC_ID
    )
    assert doc is not None
    assert doc.full_text == text
    assert slices == [1, SLICE + 1]


def test_null_and_empty_text_survive_slicing() -> None:
    doc = get_document(make_db(FakeRds(handler=_doc_handler(None, []))), "s", DOC_ID)
    assert doc is not None and doc.full_text is None
    doc = get_document(make_db(FakeRds(handler=_doc_handler("", []))), "s", DOC_ID)
    assert doc is not None and doc.full_text == ""


def test_missing_document_is_none_on_data_api() -> None:
    fake = FakeRds(records())
    assert get_document(make_db(fake), "s", DOC_ID) is None
    assert len(fake.calls) == 1


def test_psycopg_path_reads_full_text_whole(db: PsycopgDatabase) -> None:
    seed_org(db)
    doc_id = make_seed_doc(db)
    mark_indexed(db, doc_id, "z" * (SLICE + 10), [])
    spy = SpyDb(db)
    doc = get_document(spy, "s", doc_id)
    assert doc is not None and doc.full_text == "z" * (SLICE + 10)
    assert len(spy.sql) == 1
    assert "raw.full_text" in spy.sql[0]


# ---- migrations -----------------------------------------------------------


class SpyDb:
    """Delegates to a real Database and records the SQL it sees."""

    def __init__(self, inner: Database, log: list[str] | None = None) -> None:
        self.inner = inner
        self.sql: list[str] = log if log is not None else []

    def fetch(self, sql: str, params: Mapping[str, Any] | None = None):
        self.sql.append(sql)
        return self.inner.fetch(sql, params)

    def execute(self, sql: str, params: Mapping[str, Any] | None = None) -> int:
        self.sql.append(sql)
        return self.inner.execute(sql, params)

    def transaction(self):
        from contextlib import contextmanager

        @contextmanager
        def _tx():
            with self.inner.transaction() as tx:
                yield SpyDb(tx, self.sql)

        return _tx()


class RecordingDb:
    """Fake Database logging ('tx'|'top', sql, params) in call order."""

    def __init__(self) -> None:
        self.log: list[tuple[str, str, Any]] = []
        self._where = "top"

    def fetch(self, sql: str, params: Mapping[str, Any] | None = None):
        self.log.append((self._where, sql, params))
        if "to_regclass" in sql:
            return [{"t": None}]
        return []

    def execute(self, sql: str, params: Mapping[str, Any] | None = None) -> int:
        self.log.append((self._where, sql, params))
        return 1

    def transaction(self):
        from contextlib import contextmanager

        @contextmanager
        def _tx():
            self._where = "tx"
            try:
                yield self
            finally:
                self._where = "top"

        return _tx()


def test_migrations_take_advisory_lock(tmp_path: Path) -> None:
    (tmp_path / "001_a.sql").write_text("create table a (x int);")
    (tmp_path / "002_b.sql").write_text("create table b (x int);")
    rec = RecordingDb()
    assert apply_migrations(rec, tmp_path) == ["001_a.sql", "002_b.sql"]
    tx_calls = [(sql, p) for where, sql, p in rec.log if where == "tx"]
    # Each migration's transaction opens with the lock, then its statements.
    firsts = [c for c in tx_calls if "pg_advisory_xact_lock" in c[0]]
    assert len(firsts) == 2
    assert all(
        sql == "select pg_advisory_xact_lock(:k)" and p == {"k": MIGRATION_LOCK_KEY}
        for sql, p in firsts
    )
    assert "pg_advisory_xact_lock" in tx_calls[0][0]
    ddl = [i for i, c in enumerate(tx_calls) if c[0].startswith("create table")]
    assert ddl and ddl[0] > 0
    assert [w for w, s, _ in rec.log if "pg_advisory" in s] == ["tx", "tx"]


def test_migrations_take_advisory_lock_on_data_api(tmp_path: Path) -> None:
    (tmp_path / "001_a.sql").write_text("create table a (x int);")
    fake = FakeRds(
        handler=lambda op, kw: (
            {"transactionId": "tx-1"}
            if op == "BeginTransaction"
            else records({"t": None})
            if "to_regclass" in kw.get("sql", "")
            else records()
        )
    )
    assert apply_migrations(make_db(fake), tmp_path) == ["001_a.sql"]
    ops = fake.ops()
    begin = ops.index("BeginTransaction")
    assert fake.calls[begin + 1][1]["sql"] == "select pg_advisory_xact_lock(:k)"
    assert fake.calls[begin + 1][1]["transactionId"] == "tx-1"
    assert ops[-1] == "CommitTransaction"


def test_migration_applied_by_a_concurrent_runner_is_skipped(
    db: PsycopgDatabase, tmp_path: Path
) -> None:
    (tmp_path / "001_a.sql").write_text("create table lock_probe (x int);")
    assert apply_migrations(db, tmp_path) == ["001_a.sql"]

    class Stale(SpyDb):
        """Its snapshot of applied migrations predates the other runner's commit."""

        def fetch(self, sql: str, params: Mapping[str, Any] | None = None):
            if sql.strip() == "select name from schema_migrations":
                return []
            return super().fetch(sql, params)

    try:
        # Without the re-check under the lock this would fail: the table exists.
        assert apply_migrations(Stale(db), tmp_path) == []
    finally:
        db.execute("drop table lock_probe")
        db.execute("delete from schema_migrations where name = '001_a.sql'")


# ---- make_database / config ----------------------------------------------


def _settings(**kw: Any) -> Settings:
    return Settings(password_hash="x", **kw)  # pyright: ignore[reportCallIssue]


def test_make_database_requires_arns() -> None:
    with pytest.raises(RuntimeError, match="PHOEBE_DB_CLUSTER_ARN"):
        make_database(_settings(db_backend="data_api"))
    with pytest.raises(RuntimeError, match="PHOEBE_DB_SECRET_ARN"):
        make_database(_settings(db_backend="data_api", db_cluster_arn=CLUSTER))


def test_make_database_requires_url_for_psycopg() -> None:
    with pytest.raises(RuntimeError, match="PHOEBE_DATABASE_URL"):
        make_database(_settings())


def test_make_database_builds_a_data_api_database() -> None:
    db = make_database(
        _settings(db_backend="data_api", db_cluster_arn=CLUSTER, db_secret_arn=SECRET)
    )
    assert isinstance(db, DataApiDatabase)


def test_default_settings_stay_offline() -> None:
    s = _settings(database_url="postgresql://unused")
    assert s.db_backend == "psycopg"
    assert s.db_name == "phoebe"
    assert s.db_cluster_arn is None and s.db_secret_arn is None


# ---- 503 mapping ----------------------------------------------------------


def test_database_unavailable_maps_to_503(logged_in: TestClient) -> None:
    deps: Any = logged_in.app.state.deps  # type: ignore[attr-defined]

    def down(*_: Any, **__: Any) -> Any:
        raise DatabaseUnavailable("resuming")

    deps.db.fetch = down  # instance attribute shadows the method
    try:
        r = logged_in.get("/api/documents")
    finally:
        del deps.db.fetch
    assert r.status_code == 503
    assert r.json() == {"detail": "database_unavailable"}


# ---- uuid primary-key lookups --------------------------------------------


def test_uuid_lookups_do_not_cast_the_column(db: PsycopgDatabase) -> None:
    seed_org(db)
    owned = str(uuid.uuid4())
    db.execute(
        """
        insert into documents (id, session_id, title, doc_type, group_id, source_uri)
        values (:id::uuid, 's', 'D', 'markdown', 'platform', 'blob://k')
        """,
        {"id": owned},
    )
    task = make_task(db, group_id="platform", session_id="s")
    spy = SpyDb(db)

    get_document(spy, "s", owned)
    update_document(spy, "s", owned, DocumentPatch(title="New"))
    mark_failed(spy, owned, "r")
    mark_indexed(spy, owned, "t", [])
    delete_document(spy, "s", owned)
    update_task(spy, "s", task, TaskPatch(title="New"))
    delete_task(spy, "s", task)

    id_lookups = [s for s in spy.sql if ":id" in s]
    assert len(id_lookups) >= 8
    for sql in id_lookups:
        assert "id::text = :id" not in sql
        assert ":id::uuid" in sql
