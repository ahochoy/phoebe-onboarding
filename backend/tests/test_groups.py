import pytest

from conftest import make_seed_doc, make_task, seed_org
from phoebe.groups import (
    GroupInUse,
    GroupNode,
    create_group,
    delete_group,
    group_tree,
    rename_group,
    visible_group_ids,
)
from phoebe.persona import PERSONA_ID, get_persona
from phoebe.sandbox import EntityKind, hide, patch


def flatten(nodes: list[GroupNode]) -> list[GroupNode]:
    out: list[GroupNode] = []
    for node in nodes:
        out.append(node)
        out.extend(flatten(node.children))
    return out


def ids(nodes: list[GroupNode]) -> list[str]:
    return [n.id for n in flatten(nodes)]


def name_of(nodes: list[GroupNode], group_id: str) -> str:
    return next(n.name for n in flatten(nodes) if n.id == group_id)


def test_alex_sees_team_dept_company(db):
    seed_org(db)
    assert sorted(visible_group_ids(db, "s1", "platform")) == [
        "acme",
        "eng",
        "platform",
    ]


def test_visitor_group_only_in_own_tree(db):
    seed_org(db)
    gid = create_group(db, "s1", "Data", "team", "eng")
    assert gid.startswith("s-")
    assert gid in ids(group_tree(db, "s1"))
    assert gid not in ids(group_tree(db, "s2"))
    owned = {n.id: n.owned for n in flatten(group_tree(db, "s1"))}
    assert owned[gid] is True
    assert owned["eng"] is False


def test_rename_seed_group_is_per_session(db):
    seed_org(db)
    assert rename_group(db, "s1", "platform", "Platform Infra") is True
    assert name_of(group_tree(db, "s1"), "platform") == "Platform Infra"
    assert name_of(group_tree(db, "s2"), "platform") == "Platform"


def test_rename_own_group(db):
    seed_org(db)
    gid = create_group(db, "s1", "Data", "team", "eng")
    assert rename_group(db, "s1", gid, "Data Eng") is True
    assert name_of(group_tree(db, "s1"), gid) == "Data Eng"
    assert rename_group(db, "s2", gid, "Hijack") is False


def test_delete_group_in_use_refused(db):
    seed_org(db)
    make_task(db, group_id="platform")
    with pytest.raises(GroupInUse):
        delete_group(db, "s1", "platform")


def test_delete_group_with_seed_doc_refused(db):
    seed_org(db)
    make_seed_doc(db, group_id="platform")
    with pytest.raises(GroupInUse):
        delete_group(db, "s1", "platform")


def test_delete_group_with_child_refused(db):
    seed_org(db)
    with pytest.raises(GroupInUse):
        delete_group(db, "s1", "eng")


def test_delete_group_with_own_task_refused_only_for_owner(db):
    seed_org(db)
    make_task(db, group_id="payments", session_id="s1")
    with pytest.raises(GroupInUse):
        delete_group(db, "s1", "payments")
    assert delete_group(db, "s2", "payments") is True


def test_delete_unused_seed_group_hides_per_session(db):
    seed_org(db)
    assert delete_group(db, "s1", "payments") is True
    assert "payments" not in ids(group_tree(db, "s1"))
    assert "payments" in ids(group_tree(db, "s2"))
    assert delete_group(db, "s1", "payments") is False


def test_hidden_seed_task_does_not_block_delete(db):
    seed_org(db)
    task_id = make_task(db, group_id="payments")
    hide(db, "s1", EntityKind.TASK, task_id)
    assert delete_group(db, "s1", "payments") is True


def test_delete_own_group(db):
    seed_org(db)
    gid = create_group(db, "s1", "Data", "team", "eng")
    assert delete_group(db, "s1", gid) is True
    assert gid not in ids(group_tree(db, "s1"))
    assert delete_group(db, "s2", gid) is False


def test_create_group_under_foreign_parent_rejected(db):
    seed_org(db)
    foreign = create_group(db, "s2", "Theirs", "team", "eng")
    with pytest.raises(ValueError):
        create_group(db, "s1", "Mine", "team", foreign)


def test_hidden_group_excluded_from_visibility(db):
    seed_org(db)
    hide(db, "s1", EntityKind.GROUP, "platform")
    assert visible_group_ids(db, "s1", "platform") == []
    assert sorted(visible_group_ids(db, "s2", "platform")) == [
        "acme",
        "eng",
        "platform",
    ]


def test_patch_merges_fields(db):
    seed_org(db)
    patch(db, "s1", EntityKind.GROUP, "platform", {"name": "A"})
    patch(db, "s1", EntityKind.GROUP, "platform", {"other": 1})
    row = db.fetch(
        "select patch from overrides where session_id = 's1' and entity_id = 'platform'"
    )[0]
    assert row["patch"] == {"name": "A", "other": 1}


def test_get_persona(db):
    seed_org(db)
    persona = get_persona(db)
    assert persona.id == PERSONA_ID == "alex-rivera"
    assert persona.name == "Alex Rivera"
    assert (persona.team_id, persona.team_name) == ("platform", "Platform")
    assert (persona.department_id, persona.department_name) == ("eng", "Engineering")
    assert persona.manager == "Priya Nair"
    assert persona.buddy == "Sam Okafor"
