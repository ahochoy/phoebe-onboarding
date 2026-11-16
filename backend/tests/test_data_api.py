import json
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient
from psycopg.types.numeric import Int8

from conftest import make_seed_doc, make_task, seed_org
from phoebe.api.app import make_database
from phoebe.chat.history import list_turns
from phoebe.config import Settings
from phoebe.db import (
    Database,
    DatabaseUnavailable,
    PsycopgDatabase,
    json_column,
    utc_datetime,
    wake_database,
)
from phoebe.db_data_api import TEXT_SLICE_CHARS, DataApiDatabase, encode_params
from phoebe.documents import (
    DocumentPatch,
    _fetch_text_sliced,
    delete_document,
    get_document,
    mark_failed,
    mark_indexed,
    update_document,
)
from phoebe.embed import HashEmbedder
from phoebe.ingest.pipeline import index_document
from phoebe.migrate import MIGRATION_LOCK_KEY, MIGRATION_LOCK_SQL, apply_migrations
from phoebe.sandbox import is_uuid
from phoebe.sqlsplit import split_statements
from phoebe.storage import LocalBlobStore
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
    assert "includeResultMetadata" not in kw


def test_empty_result_without_records() -> None:
    assert make_db(FakeRds({"numberOfRecordsUpdated": 1})).fetch("select 1") == []


def test_adapter_does_not_sniff_types() -> None:
    """Per the Data API JSON format (no columnMetadata): jsonb/date/timestamp
    arrive as strings and the adapter hands them over untouched."""
    raw = {"s": '[{"a": 1}]', "d": "2026-11-16", "ts": "2026-11-16 12:00:00.123456"}
    fake = FakeRds({"formattedRecords": json.dumps([raw]), "columnMetadata": None})
    assert make_db(fake).fetch("select 1") == [raw]


def test_json_column_helpers_are_backend_agnostic() -> None:
    assert json_column('[{"a": 1}]') == [{"a": 1}]
    assert json_column([{"a": 1}]) == [{"a": 1}]  # psycopg: already parsed
    assert utc_datetime("2026-11-16 12:00:00.123456") == datetime(
        2026, 11, 16, 12, 0, 0, 123456, tzinfo=UTC
    )
    aware = datetime(2026, 11, 16, 12, tzinfo=UTC)
    assert utc_datetime(aware) is aware


def test_chat_history_reads_data_api_formatted_records() -> None:
    cit = {
        "n": 1,
        "chunk_id": "c1",
        "document_id": DOC_ID,
        "document_title": "T",
        "heading_path": "H",
        "start": 0,
        "end": 5,
    }
    turn = {
        "id": str(uuid.uuid4()),
        "role": "assistant",
        "text": "hi",
        "refused": False,
        "created_at": "2026-11-16 12:00:00.123456",
        "citations": json.dumps([cit]),
    }

    def handler(op: str, kw: dict[str, Any]) -> Any:
        if "from chat_turns" in kw["sql"]:
            return records(turn)
        return records({"chunk_id": "c1"})

    turns = list_turns(make_db(FakeRds(handler=handler)), "sid", ["platform"])
    assert turns[0].created_at == datetime(2026, 11, 16, 12, 0, 0, 123456, tzinfo=UTC)
    assert turns[0].citations[0].chunk_id == "c1"
    assert turns[0].citations[0].removed is False


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


def test_wake_answers_from_an_awake_cluster() -> None:
    fake, sleeps = FakeRds(), []
    assert make_db(fake, sleeps).wake() is True
    assert [kw["sql"] for _, kw in fake.calls] == ["select 1"]
    assert sleeps == []


def test_wake_does_not_wait_for_a_resuming_cluster() -> None:
    fake, sleeps = FakeRds(client_error("DatabaseResumingException")), []
    assert make_db(fake, sleeps).wake() is False
    assert len(fake.calls) == 1
    assert sleeps == []


def test_wake_during_an_outage_is_unavailable() -> None:
    fake = FakeRds(client_error("DatabaseUnavailableException"))
    with pytest.raises(DatabaseUnavailable):
        make_db(fake).wake()


def test_wake_database_falls_back_to_a_query(db: PsycopgDatabase) -> None:
    assert wake_database(db) is True


def test_sql_errors_pass_through_unchanged() -> None:
    fake = FakeRds(client_error("BadRequestException"))
    with pytest.raises(ClientError):
        make_db(fake).fetch("select nope")


# ---- sliced text ----------------------------------------------------------

DOC_ID = str(uuid.uuid4())
SLICE = 15_000


def test_slice_fits_the_data_api_row_limit() -> None:
    # The Data API caps a result row at 64 KB; keep a slice ≤ 60 KB at 4 bytes/char.
    assert DataApiDatabase.text_slice_chars == SLICE
    assert TEXT_SLICE_CHARS * 4 <= 61_440


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
        if f"substr(full_text, :off::int, {SLICE})" in sql:
            off = params["off"]["longValue"]
            slices.append(off)
            part = None if text is None else text[off - 1 : off - 1 + SLICE]
            return records({"part": part})
        assert "raw.full_text" not in sql, "full_text must not ride the detail query"
        # Data API JSON format: columnMetadata is null; dates arrive as strings.
        return {**records(_detail_row()), "columnMetadata": None}

    return handler


def test_large_text_is_fetched_in_slices() -> None:
    text = "".join(chr(97 + i % 26) for i in range(2 * SLICE + 5_000))
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


class Int8Db:
    """Binds Python ints as `bigint`, as the Data API does (`longValue`)."""

    def __init__(self, inner: Database) -> None:
        self.inner = inner

    def fetch(
        self, sql: str, params: Mapping[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        bound = {
            k: Int8(v) if isinstance(v, int) and not isinstance(v, bool) else v
            for k, v in (params or {}).items()
        }
        return self.inner.fetch(sql, bound)

    def execute(self, sql: str, params: Mapping[str, Any] | None = None) -> int:
        raise NotImplementedError

    def transaction(self):
        raise NotImplementedError


def test_sliced_text_query_accepts_bigint_offsets(db: PsycopgDatabase) -> None:
    # Regression: `substr(text, bigint, integer)` does not exist in Postgres.
    seed_org(db)
    doc_id = make_seed_doc(db)
    text = "y" * (SLICE + 10)
    mark_indexed(db, doc_id, text, [])
    assert _fetch_text_sliced(Int8Db(db), doc_id, SLICE) == text


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
        sql == MIGRATION_LOCK_SQL and p == {"k": MIGRATION_LOCK_KEY}
        for sql, p in firsts
    )
    assert "pg_advisory_xact_lock" in tx_calls[0][0]
    ddl = [i for i, c in enumerate(tx_calls) if c[0].startswith("create table")]
    assert ddl and ddl[0] > 0
    assert [w for w, s, _ in rec.log if "pg_advisory" in s] == ["tx", "tx"]


def test_splitter_basic_and_empty_statements() -> None:
    assert split_statements("select 1;; select 2 ;\n ;") == ["select 1", "select 2"]
    assert split_statements("select 1") == ["select 1"]
    assert split_statements("  \n ") == []


def test_splitter_ignores_semicolons_in_quotes() -> None:
    assert split_statements("select 'a;b', 'it''s; ok'; select 2") == [
        "select 'a;b', 'it''s; ok'",
        "select 2",
    ]
    assert split_statements('select "a;b", "q""x;y"; select 2') == [
        'select "a;b", "q""x;y"',
        "select 2",
    ]


def test_splitter_dollar_quoting() -> None:
    body = "begin perform 1; return 2; end;"
    sql = f"create function f() returns int as $${body}$$ language plpgsql; select 2"
    assert split_statements(sql) == [
        f"create function f() returns int as $${body}$$ language plpgsql",
        "select 2",
    ]
    tagged = "create function g() as $fn$ x; $$ y; $fn$ language sql; select 3"
    assert split_statements(tagged) == [
        "create function g() as $fn$ x; $$ y; $fn$ language sql",
        "select 3",
    ]
    assert split_statements("select $1; select 2") == ["select $1", "select 2"]


def test_splitter_comments() -> None:
    sql = (
        "-- lead; comment\nselect 1; -- trail; ing\nselect 2 /* a; /* nested; */ b; */;"
    )
    assert split_statements(sql) == ["select 1", "select 2"]
    assert split_statements("select '-- not a comment; ok', '/* nor this */'") == [
        "select '-- not a comment; ok', '/* nor this */'"
    ]
    assert split_statements("-- only a comment;\n/* and another; */") == []


EXPECTED_STATEMENTS = {"001_init.sql": 13, "002_sandboxes.sql": 1, "003_chat.sql": 3}


def test_every_migration_file_splits_into_the_expected_statements() -> None:
    from conftest import MIGRATIONS_DIR

    files = sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql"))
    assert files == sorted(EXPECTED_STATEMENTS), "new migration: add its count"
    for name, count in EXPECTED_STATEMENTS.items():
        stmts = split_statements((MIGRATIONS_DIR / name).read_text())
        assert len(stmts) == count, name
        assert all(s and not s.endswith(";") for s in stmts)


def test_data_api_receives_one_statement_per_call_in_one_transaction() -> None:
    from conftest import MIGRATIONS_DIR

    def handler(op: str, kw: dict[str, Any]) -> Any:
        if op == "BeginTransaction":
            return {"transactionId": f"tx-{len(fake.calls)}"}
        if "to_regclass" in kw.get("sql", ""):
            return records({"t": None})
        return records()

    fake = FakeRds(handler=handler)
    applied = apply_migrations(make_db(fake), MIGRATIONS_DIR)
    assert applied == sorted(EXPECTED_STATEMENTS)
    for op, kw in fake.calls:
        if op == "ExecuteStatement" and "transactionId" in kw:
            assert len(split_statements(kw["sql"])) == 1  # never multi-statement
    # Per file, under one transactionId: lock, schema check, the file's
    # statements, the schema_migrations insert; then the commit.
    by_tx: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for op, kw in fake.calls:
        if "transactionId" in kw:
            by_tx.setdefault(kw["transactionId"], []).append((op, kw))
    assert len(by_tx) == len(EXPECTED_STATEMENTS)
    for run, count in zip(by_tx.values(), EXPECTED_STATEMENTS.values(), strict=True):
        sqls = [kw["sql"] for op, kw in run if op == "ExecuteStatement"]
        assert sqls[0] == MIGRATION_LOCK_SQL
        assert len(sqls) == 2 + count + 1
        assert sqls[-1].startswith("insert into schema_migrations")
        assert run[-1][0] == "CommitTransaction"


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
    assert fake.calls[begin + 1][1]["sql"] == MIGRATION_LOCK_SQL
    assert fake.calls[begin + 1][1]["transactionId"] == "tx-1"
    assert ops[-1] == "CommitTransaction"


def test_migration_lock_sql_returns_a_value_and_holds_the_lock(
    db: PsycopgDatabase,
) -> None:
    # Real Postgres: the wrapped call yields an int column (not `void`, which the
    # Data API rejects) and the advisory lock is held until the transaction ends.
    held = (
        "select count(*) as n from pg_locks where locktype = 'advisory'"
        " and pid = pg_backend_pid()"
    )
    with db.transaction() as tx:
        rows = tx.fetch(MIGRATION_LOCK_SQL, {"k": MIGRATION_LOCK_KEY})
        assert rows == [{"locked": 1}]
        assert tx.fetch(held)[0]["n"] == 1
    assert db.fetch(held)[0]["n"] == 0


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


def test_uuid_lookups_do_not_cast_the_column(
    db: PsycopgDatabase, tmp_path: Path
) -> None:
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

    # The indexing pipeline (lock, lookup, chunk delete/insert).
    (tmp_path / "x.md").write_text("# Hi\n\nHello there, this is some text.\n")
    indexed = make_seed_doc(db, title="Idx")
    db.execute(
        "update documents set source_uri = 'seed://x.md' where id = :id::uuid",
        {"id": indexed},
    )
    index_document(
        spy,
        LocalBlobStore(tmp_path / "blobs"),
        HashEmbedder(),
        indexed,
        seed_root=tmp_path,
    )
    assert (
        db.fetch("select status from documents where id = :id::uuid", {"id": indexed})[
            0
        ]["status"]
        == "indexed"
    )

    id_lookups = [s for s in spy.sql if ":id" in s]
    assert len(id_lookups) >= 10
    for sql in id_lookups:
        assert "id::text = :id" not in sql
        assert ":id::uuid" in sql
    chunk_sql = [s for s in spy.sql if "chunks" in s and ":d" in s]
    assert len(chunk_sql) == 2 and all(":d::uuid" in s for s in chunk_sql)


def test_is_uuid_is_strictly_canonical() -> None:
    good = str(uuid.uuid4())
    assert is_uuid(good) and is_uuid(good.upper())
    for bad in (
        f"urn:uuid:{good}",
        good.replace("-", ""),
        "{" + good + "}",
        "-" + good,
        good + "-",
        "not-a-uuid",
        "",
    ):
        assert not is_uuid(bad), bad
    fake = FakeRds()
    assert get_document(make_db(fake), "s", f"urn:uuid:{good}") is None
    assert fake.calls == []  # rejected before any statement
