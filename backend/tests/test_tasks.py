import pytest
from pydantic import ValidationError

from conftest import make_task, seed_completion, seed_org
from phoebe.sandbox import EntityKind, hide
from phoebe.tasks import (
    NewTask,
    PersonProgress,
    TaskPatch,
    TaskView,
    create_task,
    delete_task,
    list_tasks,
    progress,
    set_completion,
    update_task,
)


def ids(tasks: list[TaskView]) -> list[str]:
    return [t.id for t in tasks]


def title_of(tasks: list[TaskView], task_id: str) -> str:
    return next(t.title for t in tasks if t.id == task_id)


def done_of(tasks: list[TaskView], task_id: str) -> bool:
    return next(t.done for t in tasks if t.id == task_id)


def by_id(rows: list[PersonProgress], person_id: str) -> PersonProgress:
    return next(r for r in rows if r.person_id == person_id)


def test_hide_seed_task_only_for_session(db):
    seed_org(db)
    t = make_task(db, group_id="acme")
    assert delete_task(db, "s1", t) is True
    assert t not in ids(list_tasks(db, "s1"))
    assert t in ids(list_tasks(db, "s2"))


def test_patch_seed_task_title(db):
    seed_org(db)
    t = make_task(db, title="Read handbook", group_id="acme")
    assert update_task(db, "s1", t, TaskPatch(title="Read the handbook")) is True
    assert title_of(list_tasks(db, "s1"), t) == "Read the handbook"
    assert title_of(list_tasks(db, "s2"), t) == "Read handbook"


def test_patch_seed_task_merges_fields(db):
    seed_org(db)
    t = make_task(db, title="A", group_id="acme")
    update_task(db, "s1", t, TaskPatch(title="B"))
    update_task(db, "s1", t, TaskPatch(description="desc", position=5))
    task = next(x for x in list_tasks(db, "s1") if x.id == t)
    assert (task.title, task.description, task.position) == ("B", "desc", 5)


def test_patch_seed_task_group(db):
    seed_org(db)
    t = make_task(db, group_id="acme")
    update_task(db, "s1", t, TaskPatch(group_id="platform"))
    task = next(x for x in list_tasks(db, "s1") if x.id == t)
    assert (task.group_id, task.group_name, task.group_kind) == (
        "platform",
        "Platform",
        "team",
    )


def test_unknown_and_foreign_ids_return_false(db):
    seed_org(db)
    mine = create_task(db, "s1", NewTask(title="Mine", group_id="acme"))
    missing = "00000000-0000-0000-0000-000000000000"
    assert update_task(db, "s1", missing, TaskPatch(title="x")) is False
    assert delete_task(db, "s1", missing) is False
    assert update_task(db, "s1", "not-a-uuid", TaskPatch(title="x")) is False
    assert update_task(db, "s2", mine, TaskPatch(title="x")) is False
    assert delete_task(db, "s2", mine) is False
    assert mine in ids(list_tasks(db, "s1"))


def test_hidden_seed_task_cannot_be_updated(db):
    seed_org(db)
    t = make_task(db, group_id="acme")
    delete_task(db, "s1", t)
    assert update_task(db, "s1", t, TaskPatch(title="x")) is False
    assert delete_task(db, "s1", t) is False


def test_owned_task_crud(db):
    seed_org(db)
    t = create_task(db, "s1", NewTask(title="Mine", group_id="platform"))
    assert t in ids(list_tasks(db, "s1"))
    assert t not in ids(list_tasks(db, "s2"))
    assert update_task(db, "s1", t, TaskPatch(title="Renamed")) is True
    assert title_of(list_tasks(db, "s1"), t) == "Renamed"
    assert delete_task(db, "s1", t) is True
    assert t not in ids(list_tasks(db, "s1"))
    assert db.fetch("select 1 from tasks where id = :id::uuid", {"id": t}) == []


def test_create_task_unknown_group_raises(db):
    seed_org(db)
    with pytest.raises(ValueError):
        create_task(db, "s1", NewTask(title="x", group_id="nope"))


def test_task_in_hidden_group_excluded(db):
    seed_org(db)
    t = make_task(db, group_id="sales-east")
    hide(db, "s1", EntityKind.GROUP, "sales-east")
    assert t not in ids(list_tasks(db, "s1"))
    assert t in ids(list_tasks(db, "s2"))


def test_list_filter_by_group_ids(db):
    seed_org(db)
    a = make_task(db, group_id="acme")
    b = make_task(db, group_id="platform")
    assert ids(list_tasks(db, "s1", group_ids=["platform"])) == [b]
    assert set(ids(list_tasks(db, "s1"))) == {a, b}
    assert list_tasks(db, "s1", group_ids=[]) == []


def test_list_ordering(db):
    seed_org(db)
    team = make_task(db, title="T", group_id="platform")
    dept = make_task(db, title="D", group_id="eng")
    co_b = make_task(db, title="B", group_id="acme")
    co_a = make_task(db, title="A", group_id="acme")
    assert ids(list_tasks(db, "s1")) == [co_a, co_b, dept, team]
    update_task(db, "s1", co_a, TaskPatch(position=9))
    assert ids(list_tasks(db, "s1")) == [co_b, co_a, dept, team]


def test_completion_session_beats_seed(db):
    seed_org(db)
    t = make_task(db, group_id="acme")
    seed_completion(db, "alex-rivera", t, True)
    set_completion(db, "s1", "alex-rivera", t, False)
    assert done_of(list_tasks(db, "s1", person_id="alex-rivera"), t) is False
    assert done_of(list_tasks(db, "s2", person_id="alex-rivera"), t) is True
    assert done_of(list_tasks(db, "s2"), t) is False
    set_completion(db, "s1", "alex-rivera", t, True)
    assert done_of(list_tasks(db, "s1", person_id="alex-rivera"), t) is True


def test_progress_counts_visible_tasks_only(db):
    seed_org(db)
    make_task(db, group_id="acme")
    make_task(db, group_id="sales-east")
    alex = by_id(progress(db, "s1"), "alex-rivera")
    assert (alex.done, alex.total) == (0, 1)
    assert (alex.name, alex.team_name, alex.department_name) == (
        "Alex Rivera",
        "Platform",
        "Engineering",
    )


def test_progress_resolves_completions_per_session(db):
    seed_org(db)
    t1 = make_task(db, group_id="acme")
    t2 = make_task(db, group_id="platform")
    seed_completion(db, "alex-rivera", t1, True)
    seed_completion(db, "alex-rivera", t2, True)
    set_completion(db, "s1", "alex-rivera", t2, False)
    alex = by_id(progress(db, "s1"), "alex-rivera")
    assert (alex.done, alex.total) == (1, 2)
    assert by_id(progress(db, "s2"), "alex-rivera").done == 2
    delete_task(db, "s1", t1)
    alex = by_id(progress(db, "s1"), "alex-rivera")
    assert (alex.done, alex.total) == (0, 1)


def test_new_task_validation():
    with pytest.raises(ValidationError):
        NewTask(title="", group_id="acme")
    with pytest.raises(ValidationError):
        NewTask(title="x" * 201, group_id="acme")
    with pytest.raises(ValidationError):
        NewTask(title="x", description="d" * 2001, group_id="acme")
    with pytest.raises(ValidationError):
        NewTask(title="x", group_id="acme", link="http://example.com")
    with pytest.raises(ValidationError):
        NewTask(title="x", group_id="acme", link="javascript:alert(1)")
    ok = NewTask(title="x", group_id="acme", link="https://example.com/a")
    assert ok.link == "https://example.com/a"
    with pytest.raises(ValidationError):
        TaskPatch(title="")
    with pytest.raises(ValidationError):
        TaskPatch(link="ftp://x.y")


def test_hide_override_hides_seed_task(db):
    seed_org(db)
    t = make_task(db, group_id="acme")
    hide(db, "s1", EntityKind.TASK, t)
    assert t not in ids(list_tasks(db, "s1"))
