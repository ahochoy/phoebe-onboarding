import threading
from contextlib import suppress
from pathlib import Path

import pytest

from phoebe.db import to_pyformat
from phoebe.migrate import apply_migrations

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


def test_to_pyformat_named_and_casts():
    assert (
        to_pyformat("select :a::vector, '%' , :b_2")
        == "select %(a)s::vector, '%%' , %(b_2)s"
    )


def test_migrations_apply_once(db):
    # fixture already migrated; second run applies nothing
    assert apply_migrations(db, MIGRATIONS_DIR) == []
    assert db.fetch("select extname from pg_extension where extname='vector'") == [
        {"extname": "vector"}
    ]


def test_transaction_rolls_back(db):
    with pytest.raises(RuntimeError), db.transaction() as tx:
        tx.execute("insert into groups(id,name,kind) values ('g','G','company')")
        raise RuntimeError
    assert db.fetch("select id from groups") == []


def test_literal_percent_without_params(db):
    assert db.fetch("select '100%' as p") == [{"p": "100%"}]


def test_uncommitted_rows_invisible_to_plain_fetch(db):
    with db.transaction() as tx:
        tx.execute("insert into groups(id,name,kind) values ('g','G','company')")
        assert tx.fetch("select id from groups") == [{"id": "g"}]
        assert db.fetch("select id from groups") == []
    assert db.fetch("select id from groups") == [{"id": "g"}]


def test_outside_write_survives_other_threads_rollback(db):
    in_tx, outside_done = threading.Event(), threading.Event()

    def hold_then_rollback():
        with suppress(RuntimeError), db.transaction() as tx:
            tx.execute("insert into groups(id,name,kind) values ('a','A','company')")
            in_tx.set()
            outside_done.wait(timeout=5)
            raise RuntimeError

    t = threading.Thread(target=hold_then_rollback)
    t.start()
    assert in_tx.wait(timeout=5)
    db.execute("insert into groups(id,name,kind) values ('b','B','company')")
    outside_done.set()
    t.join(timeout=5)
    assert db.fetch("select id from groups order by id") == [{"id": "b"}]


def test_nested_transaction_uses_savepoint(db):
    with db.transaction() as tx:
        tx.execute("insert into groups(id,name,kind) values ('a','A','company')")
        with suppress(RuntimeError), tx.transaction() as inner:
            inner.execute("insert into groups(id,name,kind) values ('b','B','company')")
            raise RuntimeError
    assert db.fetch("select id from groups") == [{"id": "a"}]
