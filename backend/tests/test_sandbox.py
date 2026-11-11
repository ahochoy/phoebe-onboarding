from conftest import make_seed_doc, make_task, seed_completion, seed_org
from phoebe.groups import create_group, group_tree
from phoebe.sandbox import EntityKind, hide, patch, reset_session
from phoebe.tasks import NewTask, TaskView, create_task, list_tasks, set_completion


def titles(tasks: list[TaskView]) -> list[str]:
    return [t.title for t in tasks]


def count(db, table: str, session_id: str) -> int:
    rows = db.fetch(
        f"select count(*) as n from {table} where session_id = :sid",
        {"sid": session_id},
    )
    return rows[0]["n"]


def test_reset_clears_everything_for_session_only(db):
    seed_org(db)
    t = make_task(db, group_id="acme")
    create_task(db, "s1", NewTask(title="Mine", group_id="platform"))
    hide(db, "s1", EntityKind.TASK, str(t))
    create_task(db, "s2", NewTask(title="Theirs", group_id="platform"))
    reset_session(db, "s1")
    assert titles(list_tasks(db, "s1")) == titles(list_tasks(db, "s0"))
    assert "Theirs" in titles(list_tasks(db, "s2"))
    assert "Mine" not in titles(list_tasks(db, "s1"))


def test_reset_clears_completions_and_patches(db):
    seed_org(db)
    t = make_task(db, group_id="acme")
    seed_completion(db, "alex-rivera", t, True)
    set_completion(db, "s1", "alex-rivera", t, False)
    set_completion(db, "s2", "alex-rivera", t, False)
    patch(db, "s1", EntityKind.TASK, t, {"title": "Changed"})
    reset_session(db, "s1")
    assert count(db, "task_completions", "s1") == 0
    assert count(db, "task_completions", "s2") == 1
    assert count(db, "overrides", "s1") == 0
    # seed row untouched
    seed = db.fetch("select done from task_completions where session_id = ''")
    assert [r["done"] for r in seed] == [True]
    assert titles(list_tasks(db, "s1")) == ["Task"]


def test_reset_deletes_nested_owned_groups_and_their_content(db):
    seed_org(db)
    g1 = create_group(db, "s1", "Guild", "team", "eng")
    g2 = create_group(db, "s1", "Sub", "team", g1)
    g3 = create_group(db, "s1", "Subsub", "team", g2)
    create_task(db, "s1", NewTask(title="In g3", group_id=g3))
    other = create_group(db, "s2", "Other", "team", "eng")
    reset_session(db, "s1")
    assert count(db, "groups", "s1") == 0
    assert count(db, "tasks", "s1") == 0
    assert count(db, "groups", "s2") == 1
    assert other in {n.id for n in group_tree(db, "s2")[0].children[0].children}


def test_reset_returns_blob_keys_and_deletes_documents_and_chunks(db):
    seed_org(db)
    seed_doc = make_seed_doc(db)
    rows = db.fetch(
        """
        insert into documents (session_id, title, doc_type, group_id, source_uri, status)
        values
          ('s1', 'Up', 'pdf', 'platform', 'blob://abc/key.pdf', 'indexed'),
          ('s1', 'Link', 'web', 'platform', 'https://example.com', 'indexed'),
          ('s2', 'Other', 'pdf', 'platform', 'blob://zzz/other.pdf', 'indexed')
        returning id::text as id, title
        """
    )
    up = next(r["id"] for r in rows if r["title"] == "Up")
    db.execute(
        """
        insert into chunks (document_id, ordinal, heading_path, text,
                            start_offset, end_offset, embedding)
        values (:d::uuid, 0, 'h', 't', 0, 1, :emb::vector)
        """,
        {"d": up, "emb": "[" + ",".join(["0"] * 1024) + "]"},
    )
    keys = reset_session(db, "s1")
    assert keys == ["abc/key.pdf"]
    assert count(db, "documents", "s1") == 0
    assert count(db, "documents", "s2") == 1
    assert db.fetch("select 1 from documents where id = :d::uuid", {"d": seed_doc})
    assert db.fetch("select 1 from chunks") == []


def test_reset_fresh_session_is_noop(db):
    seed_org(db)
    make_task(db, group_id="acme")
    assert reset_session(db, "s0") == []
    assert len(list_tasks(db, "s0")) == 1
