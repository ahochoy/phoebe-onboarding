import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import CSRF
from phoebe.api.app import Deps
from phoebe.sessions import sandbox_id

MB5 = 5 * 1024 * 1024


def deps_of(c: TestClient) -> Deps:
    return c.app.state.deps  # type: ignore[attr-defined]


def upload(
    c: TestClient,
    name: str,
    data: bytes,
    *,
    group_id: str = "platform",
    title: str = "Doc",
    purpose: str = "p",
    headers: dict | None = None,
    extra: dict | None = None,
):
    form = {"title": title, "purpose": purpose, "group_id": group_id, **(extra or {})}
    return c.post(
        "/api/documents/upload",
        files={"file": (name, data)},
        data=form,
        headers=CSRF if headers is None else headers,
    )


def post_link(c: TestClient, url: str, **over):
    body = {"url": url, "title": "L", "purpose": "p", "group_id": "platform", **over}
    return c.post("/api/documents/link", json=body, headers=CSRF)


def search(c: TestClient, q: str) -> list[dict]:
    r = c.post("/api/search", json={"query": q}, headers=CSRF)
    assert r.status_code == 200
    return r.json()


def doc_id_by_title(c: TestClient, title: str, scope: str = "all") -> str:
    docs = c.get(f"/api/documents?scope={scope}").json()
    return next(d["id"] for d in docs if d["title"] == title)


def _source_uri(c: TestClient, doc_id: str) -> str:
    rows = deps_of(c).db.fetch(
        "select source_uri from documents where id::text = :id", {"id": doc_id}
    )
    return rows[0]["source_uri"]


def blob_files(c: TestClient) -> list[Path]:
    root: Path = deps_of(c).settings.blob_dir
    return [p for p in root.rglob("*") if p.is_file()]


# ---- listing -------------------------------------------------------------


def test_requires_session(client: TestClient) -> None:
    assert client.get("/api/documents").status_code == 401
    assert client.get(f"/api/documents/{uuid.uuid4()}").status_code == 401


def test_list_mine_vs_all(seeded_client: TestClient) -> None:
    mine = seeded_client.get("/api/documents?scope=mine").json()
    everything = seeded_client.get("/api/documents?scope=all").json()
    assert len(mine) == 9 and len(everything) == 12
    assert seeded_client.get("/api/documents").json() == mine  # default mine
    assert seeded_client.get("/api/documents?scope=zzz").status_code == 422


def test_get_detail(seeded_client: TestClient) -> None:
    d = doc_id_by_title(seeded_client, "Employee Handbook")
    r = seeded_client.get(f"/api/documents/{d}")
    assert r.status_code == 200
    assert "20 days" in r.json()["full_text"] and r.json()["id"] == d


def test_get_unknown_and_non_uuid_404(seeded_client: TestClient) -> None:
    for ident in (str(uuid.uuid4()), "not-a-uuid"):
        r = seeded_client.get(f"/api/documents/{ident}")
        assert r.status_code == 404 and r.json() == {"detail": "not_found"}


# ---- upload --------------------------------------------------------------


def test_upload_then_search(seeded_client: TestClient) -> None:
    r = upload(
        seeded_client,
        "parking.md",
        b"# Parking\nGarage level P2, badge required.\n",
        group_id="platform",
        title="Parking",
    )
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "processing" and body["owned"] is True
    assert body["doc_type"] == "markdown" and body["title"] == "Parking"
    assert any("P2" in p["text"] for p in search(seeded_client, "where do I park"))
    assert (
        seeded_client.get(f"/api/documents/{body['id']}").json()["status"] == "indexed"
    )


def test_upload_blob_key_matches_doc_id(seeded_client: TestClient) -> None:
    r = upload(seeded_client, "a.md", b"# A\ntext here\n")
    doc_id = r.json()["id"]
    sid = sandbox_id(seeded_client.cookies["phoebe_session"])
    assert (
        deps_of(seeded_client).blobs.get(f"uploads/{sid}/{doc_id}")
        == b"# A\ntext here\n"
    )


def test_upload_ignores_client_source_uri(seeded_client: TestClient) -> None:
    r = upload(
        seeded_client,
        "a.md",
        b"# A\ntext\n",
        extra={"source_uri": "seed://handbook.md"},
    )
    assert r.status_code == 202
    sid = sandbox_id(seeded_client.cookies["phoebe_session"])
    assert _source_uri(seeded_client, r.json()["id"]) == (
        f"blob://uploads/{sid}/{r.json()['id']}"
    )
    assert "source_uri" not in r.json()


def test_upload_csv_and_pdf_types(seeded_client: TestClient) -> None:
    assert upload(seeded_client, "t.csv", b"a,b\n1,2\n").json()["doc_type"] == "csv"


def test_upload_too_large_413(seeded_client: TestClient) -> None:
    r = upload(seeded_client, "big.md", b"a" * (MB5 + 1))
    assert r.status_code == 413 and r.json() == {"detail": "file_too_large"}
    assert blob_files(seeded_client) == []


def test_upload_exactly_5mb_accepted(seeded_client: TestClient) -> None:
    r = upload(seeded_client, "big.md", b"a" * MB5)
    assert r.status_code == 202


def test_upload_mismatched_415(seeded_client: TestClient) -> None:
    r = upload(seeded_client, "x.pdf", b"# md")
    assert r.status_code == 415
    body = r.json()
    assert body["detail"] == "unsupported_type" and isinstance(body["reason"], str)
    assert blob_files(seeded_client) == []


def test_upload_unknown_extension_415(seeded_client: TestClient) -> None:
    assert upload(seeded_client, "x.exe", b"MZ").status_code == 415


def test_upload_requires_csrf(seeded_client: TestClient) -> None:
    assert upload(seeded_client, "a.md", b"# a\n", headers={}).status_code == 403


def test_upload_requires_session(client: TestClient) -> None:
    assert upload(client, "a.md", b"# a\n").status_code == 401


def test_upload_form_validation_422(seeded_client: TestClient) -> None:
    assert upload(seeded_client, "a.md", b"# a\n", title="").status_code == 422
    assert upload(seeded_client, "a.md", b"# a\n", title="x" * 201).status_code == 422
    assert upload(seeded_client, "a.md", b"# a\n", purpose="x" * 501).status_code == 422
    r = upload(seeded_client, "a.md", b"# a\n", extra={"last_updated": "garbage"})
    assert r.status_code == 422
    r = seeded_client.post(
        "/api/documents/upload",
        data={"title": "t", "purpose": "p", "group_id": "platform"},
        headers=CSRF,
    )
    assert r.status_code == 422  # no file
    assert blob_files(seeded_client) == []


def test_upload_valid_last_updated(seeded_client: TestClient) -> None:
    r = upload(seeded_client, "a.md", b"# a\n", extra={"last_updated": "2026-10-01"})
    assert r.status_code == 202 and r.json()["last_updated"] == "2026-10-01"


def test_upload_invalid_group_422_and_no_blob(seeded_client: TestClient) -> None:
    r = upload(seeded_client, "a.md", b"# a\n", group_id="nope")
    assert r.status_code == 422 and r.json() == {"detail": "invalid_group"}
    assert blob_files(seeded_client) == []


def test_sandbox_full_409_and_blob_cleaned(seeded_client: TestClient) -> None:
    for i in range(20):
        assert (
            upload(seeded_client, f"{i}.md", b"# a\nx\n", title=f"d{i}").status_code
            == 202
        )
    r = upload(seeded_client, "over.md", b"# a\nx\n")
    assert r.status_code == 409 and r.json() == {"detail": "sandbox_full"}
    assert len(blob_files(seeded_client)) == 20
    assert post_link(seeded_client, "https://example.com/p").status_code == 409


def test_blob_deleted_when_create_fails(
    seeded_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*_a, **_k):
        raise RuntimeError("db down")

    monkeypatch.setattr("phoebe.api.routes_documents.create_document", boom)
    r = upload(seeded_client, "a.md", b"# a\nx\n")
    assert r.status_code == 500 and r.json() == {"detail": "internal_error"}
    assert blob_files(seeded_client) == []


def test_failing_job_does_not_break_response(
    seeded_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(_doc_id: str) -> None:
        raise RuntimeError("secret document text")

    monkeypatch.setattr(deps_of(seeded_client).jobs, "enqueue", boom)
    r = upload(seeded_client, "a.md", b"# a\nx\n")
    assert r.status_code == 202


def test_job_enqueued_once_with_doc_id(
    seeded_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    monkeypatch.setattr(deps_of(seeded_client).jobs, "enqueue", seen.append)
    r = upload(seeded_client, "a.md", b"# a\nx\n")
    assert seen == [r.json()["id"]]


def test_other_session_cannot_read_my_upload(
    seeded_client: TestClient, second_client: TestClient
) -> None:
    d = upload(seeded_client, "a.md", b"# Mine\nsecret xylophone\n").json()["id"]
    assert seeded_client.get(f"/api/documents/{d}").status_code == 200
    r = second_client.get(f"/api/documents/{d}")
    assert r.status_code == 404 and r.json() == {"detail": "not_found"}
    assert (
        second_client.patch(
            f"/api/documents/{d}", json={"title": "x"}, headers=CSRF
        ).status_code
        == 404
    )
    assert second_client.delete(f"/api/documents/{d}", headers=CSRF).status_code == 404
    assert d not in {
        x["id"] for x in second_client.get("/api/documents?scope=all").json()
    }


# ---- link ----------------------------------------------------------------


def test_link_web_202(seeded_client: TestClient) -> None:
    r = post_link(seeded_client, "https://example.com/page")
    assert r.status_code == 202
    b = r.json()
    assert b["doc_type"] == "web" and b["status"] == "processing" and b["owned"]
    assert b["public_url"] == "https://example.com/page"
    assert "source_uri" not in b


def test_link_google_doc_type(seeded_client: TestClient) -> None:
    r = post_link(seeded_client, "https://docs.google.com/document/d/abc123/edit")
    assert r.status_code == 202 and r.json()["doc_type"] == "google_doc"


def test_link_enqueues_via_job(
    seeded_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    monkeypatch.setattr(deps_of(seeded_client).jobs, "enqueue", seen.append)
    r = post_link(seeded_client, "https://example.com/page")
    assert seen == [r.json()["id"]]


def test_link_http_rejected_422(seeded_client: TestClient) -> None:
    r = post_link(seeded_client, "http://example.com")
    assert r.status_code == 422 and r.json() == {"detail": "invalid_link"}


def test_link_bad_urls_422(seeded_client: TestClient) -> None:
    for url in (
        "ftp://example.com/x",
        "https://",
        "not a url",
        "javascript:alert(1)",
        "https://example.com/" + "a" * 2000,
        "",
    ):
        r = post_link(seeded_client, url)
        assert r.status_code == 422 and r.json()["detail"] in {
            "invalid_link",
            "invalid_request",
        }, url
    assert post_link(seeded_client, "https://example.com/" + "a" * 2000).json() == {
        "detail": "invalid_link"
    }


def test_link_validation_and_group(seeded_client: TestClient) -> None:
    assert post_link(seeded_client, "https://example.com", title="").status_code == 422
    r = post_link(seeded_client, "https://example.com", group_id="nope")
    assert r.status_code == 422 and r.json() == {"detail": "invalid_group"}


def test_link_requires_csrf_and_session(
    seeded_client: TestClient, client: TestClient
) -> None:
    body = {"url": "https://example.com", "title": "t", "group_id": "platform"}
    assert seeded_client.post("/api/documents/link", json=body).status_code == 403
    client.cookies.clear()
    assert (
        client.post("/api/documents/link", json=body, headers=CSRF).status_code == 401
    )


def test_link_ignores_extra_source_uri(seeded_client: TestClient) -> None:
    r = post_link(seeded_client, "https://example.com/p", source_uri="seed://x")
    assert r.status_code == 202
    assert _source_uri(seeded_client, r.json()["id"]) == "https://example.com/p"


# ---- patch / delete ------------------------------------------------------


def test_patch_document(seeded_client: TestClient) -> None:
    d = upload(seeded_client, "a.md", b"# a\nx\n").json()["id"]
    r = seeded_client.patch(
        f"/api/documents/{d}",
        json={"title": "New", "group_id": "engineering"},
        headers=CSRF,
    )
    assert r.status_code == 204
    got = seeded_client.get(f"/api/documents/{d}").json()
    assert got["title"] == "New" and got["group_id"] == "engineering"


def test_patch_seed_document(seeded_client: TestClient) -> None:
    d = doc_id_by_title(seeded_client, "Employee Handbook")
    assert (
        seeded_client.patch(
            f"/api/documents/{d}", json={"title": "Handbook v2"}, headers=CSRF
        ).status_code
        == 204
    )
    assert seeded_client.get(f"/api/documents/{d}").json()["title"] == "Handbook v2"


def test_patch_rejects_source_uri_and_bad_group(seeded_client: TestClient) -> None:
    d = upload(seeded_client, "a.md", b"# a\nx\n").json()["id"]
    r = seeded_client.patch(
        f"/api/documents/{d}",
        json={"source_uri": "seed://x", "title": "T"},
        headers=CSRF,
    )
    assert r.status_code == 204
    assert _source_uri(seeded_client, d).startswith("blob://uploads/")
    r = seeded_client.patch(
        f"/api/documents/{d}", json={"group_id": "nope"}, headers=CSRF
    )
    assert r.status_code == 422 and r.json() == {"detail": "invalid_group"}


def test_patch_unknown_404(seeded_client: TestClient) -> None:
    for ident in (str(uuid.uuid4()), "nope"):
        r = seeded_client.patch(
            f"/api/documents/{ident}", json={"title": "x"}, headers=CSRF
        )
        assert r.status_code == 404 and r.json() == {"detail": "not_found"}
        assert (
            seeded_client.delete(f"/api/documents/{ident}", headers=CSRF).status_code
            == 404
        )


def test_delete_upload_removes_blob(seeded_client: TestClient) -> None:
    d = upload(seeded_client, "a.md", b"# a\nx\n").json()["id"]
    assert len(blob_files(seeded_client)) == 1
    assert seeded_client.delete(f"/api/documents/{d}", headers=CSRF).status_code == 204
    assert blob_files(seeded_client) == []
    assert seeded_client.get(f"/api/documents/{d}").status_code == 404


def test_delete_doc_removes_from_search(seeded_client: TestClient) -> None:
    d = doc_id_by_title(seeded_client, "Employee Handbook")
    assert any(p["document_id"] == d for p in search(seeded_client, "PTO days"))
    seeded_client.delete(f"/api/documents/{d}", headers=CSRF)
    assert not any(p["document_id"] == d for p in search(seeded_client, "PTO days"))


def test_delete_requires_csrf(seeded_client: TestClient) -> None:
    d = doc_id_by_title(seeded_client, "Employee Handbook")
    assert seeded_client.delete(f"/api/documents/{d}").status_code == 403


# ---- search --------------------------------------------------------------


def test_search_handbook(seeded_client: TestClient) -> None:
    hits = search(seeded_client, "how many vacation days")
    assert any("20 days" in p["text"] for p in hits) and len(hits) <= 5


def test_search_empty_query_422(seeded_client: TestClient) -> None:
    for q in ("   ", "", "x" * 501):
        r = seeded_client.post("/api/search", json={"query": q}, headers=CSRF)
        assert r.status_code == 422, q
    r = seeded_client.post("/api/search", json={}, headers=CSRF)
    assert r.status_code == 422


def test_search_strips_and_allows_500(seeded_client: TestClient) -> None:
    assert search(seeded_client, "  " + "a" * 500 + "  ") is not None


def test_search_only_sees_visible_groups(seeded_client: TestClient) -> None:
    # sales-only docs are not in Alex's visible groups
    visible = {d["id"] for d in seeded_client.get("/api/documents?scope=mine").json()}
    for q in ("quota", "commission", "pipeline", "handbook"):
        for p in search(seeded_client, q):
            assert p["document_id"] in visible


def test_no_session_token_in_any_response(seeded_client: TestClient) -> None:
    token = seeded_client.cookies["phoebe_session"]
    bodies = []
    up = upload(seeded_client, "a.md", b"# a\nx\n")
    bodies.append(up)
    bodies.append(post_link(seeded_client, "https://example.com/p"))
    bodies.append(seeded_client.get("/api/documents?scope=all"))
    bodies.append(seeded_client.get(f"/api/documents/{up.json()['id']}"))
    bodies.append(seeded_client.get("/api/me"))
    bodies.append(seeded_client.get("/api/groups"))
    bodies.append(seeded_client.get("/api/tasks?scope=all"))
    bodies.append(seeded_client.post("/api/search", json={"query": "a"}, headers=CSRF))
    for r in bodies:
        assert token not in r.text and "source_uri" not in r.text


def test_blob_key_uses_sandbox_id_not_token(seeded_client: TestClient) -> None:
    token = seeded_client.cookies["phoebe_session"]
    r = upload(seeded_client, "a.md", b"# a\nx\n")
    files = blob_files(seeded_client)
    assert len(files) == 1
    assert token not in str(files[0])
    assert sandbox_id(token) in str(files[0])
    assert token not in _source_uri(seeded_client, r.json()["id"])
    rows = deps_of(seeded_client).db.fetch(
        "select session_id from documents where id::text = :id", {"id": r.json()["id"]}
    )
    assert rows[0]["session_id"] == sandbox_id(token) != token


def test_link_doc_public_url_set(seeded_client: TestClient) -> None:
    r = post_link(seeded_client, "https://example.com/p")
    assert r.json()["public_url"] == "https://example.com/p"
    got = seeded_client.get(f"/api/documents/{r.json()['id']}").json()
    assert got["public_url"] == "https://example.com/p"
    up = upload(seeded_client, "a.md", b"# a\nx\n")
    assert up.json()["public_url"] is None


def test_upload_without_content_length_411(seeded_client: TestClient) -> None:
    boundary = "xBOUNDARYx"
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="title"\r\n\r\nT\r\n'
        f'--{boundary}\r\nContent-Disposition: form-data; name="group_id"\r\n\r\n'
        f"platform\r\n"
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="a.md"\r\n\r\n# a\r\n--{boundary}--\r\n'
    ).encode()

    def gen():
        yield body

    r = seeded_client.post(
        "/api/documents/upload",
        content=gen(),
        headers={**CSRF, "Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    assert r.status_code == 411 and r.json() == {"detail": "length_required"}
    assert blob_files(seeded_client) == []


def test_delete_blob_failure_is_swallowed(
    seeded_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    d = upload(seeded_client, "a.md", b"# a\nx\n").json()["id"]

    def boom(_key: str) -> None:
        raise OSError("disk")

    monkeypatch.setattr(deps_of(seeded_client).blobs, "delete", boom)
    assert seeded_client.delete(f"/api/documents/{d}", headers=CSRF).status_code == 204
