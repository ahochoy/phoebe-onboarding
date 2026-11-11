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
