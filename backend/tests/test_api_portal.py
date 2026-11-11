from fastapi.testclient import TestClient

from conftest import CSRF
from phoebe.api.app import Deps

KIND_ORDER = ["company", "department", "team"]


def deps_of(c: TestClient) -> Deps:
    return c.app.state.deps  # type: ignore[attr-defined]


def tasks(c: TestClient, scope: str = "mine") -> list[dict]:
    r = c.get(f"/api/tasks?scope={scope}")
    assert r.status_code == 200
    return r.json()


def first_open_task(c: TestClient) -> str:
    return next(t["id"] for t in tasks(c) if not t["done"])


def alex_row(c: TestClient) -> dict:
    return next(
        p for p in c.get("/api/people").json() if p["person_id"] == "alex-rivera"
    )


# ---- auth coverage -------------------------------------------------------


def test_portal_gets_require_session(client: TestClient) -> None:
    for path in ("/api/groups", "/api/tasks", "/api/people", "/api/people/x/tasks"):
        assert client.get(path).status_code == 401, path


def test_portal_writes_require_csrf_and_session(logged_in: TestClient) -> None:
    gid = "00000000-0000-0000-0000-000000000000"
    calls = [
        ("post", "/api/groups", {"name": "x", "kind": "team", "parent_id": "p"}),
        ("patch", "/api/groups/x", {"name": "y"}),
        ("delete", "/api/groups/x", None),
        ("post", "/api/tasks", {"title": "t", "group_id": "platform"}),
        ("patch", f"/api/tasks/{gid}", {"title": "t"}),
        ("delete", f"/api/tasks/{gid}", None),
        ("put", f"/api/tasks/{gid}/completion", {"done": True}),
        ("post", "/api/search", {"query": "q"}),
    ]
    for method, path, body in calls:
        kwargs = {"json": body} if body is not None else {}
        r = getattr(logged_in, method)(path, **kwargs)
        assert r.status_code == 403, (method, path)


def test_portal_writes_without_session_401(client: TestClient) -> None:
    r = client.post("/api/search", json={"query": "q"}, headers=CSRF)
    assert r.status_code == 401


# ---- tasks ---------------------------------------------------------------


def test_mine_tasks_grouped_and_ordered(seeded_client: TestClient) -> None:
    kinds = [t["group_kind"] for t in tasks(seeded_client)]
    assert kinds == sorted(kinds, key=KIND_ORDER.index) and len(kinds) == 14


def test_mine_has_alex_done_count(seeded_client: TestClient) -> None:
    assert sum(t["done"] for t in tasks(seeded_client)) == 6


def test_all_tasks_superset_of_mine(seeded_client: TestClient) -> None:
    mine = {t["id"] for t in tasks(seeded_client)}
    everything = {t["id"] for t in tasks(seeded_client, "all")}
    assert mine <= everything and len(everything) > len(mine)


def test_bad_scope_422(seeded_client: TestClient) -> None:
    r = seeded_client.get("/api/tasks?scope=bogus")
    assert r.status_code == 422 and r.json() == {"detail": "invalid_request"}


def test_check_task_updates_progress(seeded_client: TestClient) -> None:
    t = first_open_task(seeded_client)
    r = seeded_client.put(
        f"/api/tasks/{t}/completion", json={"done": True}, headers=CSRF
    )
    assert r.status_code == 204
    assert alex_row(seeded_client)["done"] == 7
    assert next(x for x in tasks(seeded_client) if x["id"] == t)["done"] is True


def test_uncheck_task(seeded_client: TestClient) -> None:
    t = next(x["id"] for x in tasks(seeded_client) if x["done"])
    seeded_client.put(f"/api/tasks/{t}/completion", json={"done": False}, headers=CSRF)
    assert alex_row(seeded_client)["done"] == 5


def test_completion_unknown_task_404(seeded_client: TestClient) -> None:
    r = seeded_client.put(
        "/api/tasks/00000000-0000-0000-0000-000000000000/completion",
        json={"done": True},
        headers=CSRF,
    )
    assert r.status_code == 404 and r.json() == {"detail": "not_found"}


def test_completion_non_uuid_404(seeded_client: TestClient) -> None:
    r = seeded_client.put(
        "/api/tasks/nope/completion", json={"done": True}, headers=CSRF
    )
    assert r.status_code == 404 and r.json() == {"detail": "not_found"}


def test_completion_body_must_be_bool(seeded_client: TestClient) -> None:
    t = first_open_task(seeded_client)
    r = seeded_client.put(f"/api/tasks/{t}/completion", json={}, headers=CSRF)
    assert r.status_code == 422


def test_create_patch_delete_task(seeded_client: TestClient) -> None:
    r = seeded_client.post(
        "/api/tasks",
        json={"title": "Mine", "group_id": "platform", "link": "https://example.com/x"},
        headers=CSRF,
    )
    assert r.status_code == 201
    tid = r.json()["id"]
    assert any(t["id"] == tid and t["owned"] for t in tasks(seeded_client))
    r = seeded_client.patch(
        f"/api/tasks/{tid}", json={"title": "Renamed"}, headers=CSRF
    )
    assert r.status_code == 204
    assert any(t["title"] == "Renamed" for t in tasks(seeded_client))
    assert seeded_client.delete(f"/api/tasks/{tid}", headers=CSRF).status_code == 204
    assert not any(t["id"] == tid for t in tasks(seeded_client))


def test_create_task_bad_group_422(seeded_client: TestClient) -> None:
    r = seeded_client.post(
        "/api/tasks", json={"title": "t", "group_id": "nope"}, headers=CSRF
    )
    assert r.status_code == 422 and r.json() == {"detail": "invalid_group"}


def test_create_task_http_link_422(seeded_client: TestClient) -> None:
    r = seeded_client.post(
        "/api/tasks",
        json={"title": "t", "group_id": "platform", "link": "http://x.example"},
        headers=CSRF,
    )
    assert r.status_code == 422


def test_patch_task_bad_group_422(seeded_client: TestClient) -> None:
    t = first_open_task(seeded_client)
    r = seeded_client.patch(f"/api/tasks/{t}", json={"group_id": "nope"}, headers=CSRF)
    assert r.status_code == 422 and r.json() == {"detail": "invalid_group"}


def test_patch_and_delete_unknown_task_404(seeded_client: TestClient) -> None:
    u = "/api/tasks/00000000-0000-0000-0000-000000000000"
    assert seeded_client.patch(u, json={"title": "x"}, headers=CSRF).status_code == 404
    assert seeded_client.delete(u, headers=CSRF).status_code == 404
    assert seeded_client.delete("/api/tasks/zzz", headers=CSRF).status_code == 404


def test_foreign_task_is_404(
    seeded_client: TestClient, second_client: TestClient
) -> None:
    r = seeded_client.post(
        "/api/tasks", json={"title": "private", "group_id": "platform"}, headers=CSRF
    )
    tid = r.json()["id"]
    assert (
        second_client.patch(
            f"/api/tasks/{tid}", json={"title": "x"}, headers=CSRF
        ).status_code
        == 404
    )
    assert second_client.delete(f"/api/tasks/{tid}", headers=CSRF).status_code == 404
    assert (
        second_client.put(
            f"/api/tasks/{tid}/completion", json={"done": True}, headers=CSRF
        ).status_code
        == 404
    )


# ---- people --------------------------------------------------------------


def test_people_progress(seeded_client: TestClient) -> None:
    people = seeded_client.get("/api/people").json()
    assert any(p["person_id"] == "alex-rivera" for p in people)
    assert alex_row(seeded_client)["total"] == 14


def test_person_tasks(seeded_client: TestClient) -> None:
    r = seeded_client.get("/api/people/alex-rivera/tasks")
    assert r.status_code == 200 and len(r.json()) == 14
    assert sum(t["done"] for t in r.json()) == 6


def test_unknown_person_404(seeded_client: TestClient) -> None:
    r = seeded_client.get("/api/people/nobody/tasks")
    assert r.status_code == 404 and r.json() == {"detail": "not_found"}


# ---- groups --------------------------------------------------------------


def _flatten(nodes: list[dict]) -> list[dict]:
    out = []
    for n in nodes:
        out.append(n)
        out.extend(_flatten(n["children"]))
    return out


def test_group_tree(seeded_client: TestClient) -> None:
    tree = seeded_client.get("/api/groups").json()
    assert len(tree) == 1 and tree[0]["id"] == "larkspur"
    assert {"platform", "engineering"} <= {n["id"] for n in _flatten(tree)}


def test_group_create_rename_delete(seeded_client: TestClient) -> None:
    r = seeded_client.post(
        "/api/groups",
        json={"name": "  Infra  ", "kind": "team", "parent_id": "engineering"},
        headers=CSRF,
    )
    assert r.status_code == 201
    gid = r.json()["id"]
    node = next(
        n for n in _flatten(seeded_client.get("/api/groups").json()) if n["id"] == gid
    )
    assert node["name"] == "Infra" and node["owned"]
    r = seeded_client.patch(f"/api/groups/{gid}", json={"name": "Infra2"}, headers=CSRF)
    assert r.status_code == 204
    assert seeded_client.delete(f"/api/groups/{gid}", headers=CSRF).status_code == 204
    assert gid not in {
        n["id"] for n in _flatten(seeded_client.get("/api/groups").json())
    }


def test_group_create_department_under_company(seeded_client: TestClient) -> None:
    r = seeded_client.post(
        "/api/groups",
        json={"name": "Legal", "kind": "department", "parent_id": "larkspur"},
        headers=CSRF,
    )
    assert r.status_code == 201


def test_group_create_rejects_bad_shapes(seeded_client: TestClient) -> None:
    def post(body: dict):
        return seeded_client.post("/api/groups", json=body, headers=CSRF)

    cases = [
        {"name": "X", "kind": "team", "parent_id": "larkspur"},  # team under company
        {"name": "X", "kind": "department", "parent_id": "engineering"},
        {"name": "X", "kind": "team", "parent_id": "platform"},  # team under team
        {"name": "X", "kind": "team", "parent_id": "nope"},
    ]
    for body in cases:
        r = post(body)
        assert r.status_code == 422 and r.json() == {"detail": "invalid_group"}, body
    for body in (
        {"name": "X", "kind": "company", "parent_id": "larkspur"},
        {"name": "   ", "kind": "team", "parent_id": "engineering"},
        {"name": "x" * 101, "kind": "team", "parent_id": "engineering"},
    ):
        assert post(body).status_code == 422, body


def test_group_rename_validation_and_404(seeded_client: TestClient) -> None:
    assert (
        seeded_client.patch(
            "/api/groups/platform", json={"name": " "}, headers=CSRF
        ).status_code
        == 422
    )
    r = seeded_client.patch("/api/groups/nope", json={"name": "x"}, headers=CSRF)
    assert r.status_code == 404 and r.json() == {"detail": "not_found"}
    assert seeded_client.delete("/api/groups/nope", headers=CSRF).status_code == 404


def test_group_in_use_409(seeded_client: TestClient) -> None:
    r = seeded_client.delete("/api/groups/engineering", headers=CSRF)
    assert r.status_code == 409 and r.json() == {"detail": "group_in_use"}


def test_foreign_group_404(
    seeded_client: TestClient, second_client: TestClient
) -> None:
    gid = seeded_client.post(
        "/api/groups",
        json={"name": "Mine", "kind": "team", "parent_id": "engineering"},
        headers=CSRF,
    ).json()["id"]
    assert second_client.delete(f"/api/groups/{gid}", headers=CSRF).status_code == 404
    assert (
        second_client.patch(
            f"/api/groups/{gid}", json={"name": "z"}, headers=CSRF
        ).status_code
        == 404
    )
    assert gid not in {
        n["id"] for n in _flatten(second_client.get("/api/groups").json())
    }
