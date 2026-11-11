"""Required 0-leak property test for hybrid retrieval.

The oracle below is plain Python over what this test created. It must not
reuse any production SQL.
"""

from dataclasses import dataclass

from conftest import ALEX, index_seed_text, seed_org
from phoebe.documents import DocumentPatch, update_document
from phoebe.embed import HashEmbedder
from phoebe.groups import visible_group_ids
from phoebe.retrieve import search
from phoebe.sandbox import EntityKind, hide

SESSIONS = ["s1", "s2", "s3"]
GROUPS = ["acme", "eng", "sales", "platform", "payments", "sales-east"]
COMMON = "handbook policy process guide onboarding"


@dataclass
class Spec:
    doc_id: str
    token: str
    phrase: str
    group: str
    owner: str | None  # session id, or None for seed


def _doc(db, specs: list[Spec], group: str, owner: str | None, n: int) -> Spec:
    token = f"zebra{n:02d}"
    phrase = f"quokka{n:02d} procedure for {group}"
    md = f"# {token} {group}\n{COMMON} {token}.\n\n{phrase}. {COMMON}.\n".encode()
    doc_id = index_seed_text(db, group, md, title=f"Doc {token}", session_id=owner)
    spec = Spec(doc_id, token, phrase, group, owner)
    specs.append(spec)
    return spec


def build(db) -> tuple[list[Spec], set[tuple[str, str]], dict[tuple[str, str], str]]:
    seed_org(db)
    specs: list[Spec] = []
    n = 0
    seeds: dict[str, Spec] = {}
    for g in GROUPS:
        n += 1
        seeds[g] = _doc(db, specs, g, None, n)
    for sid, groups in (("s1", ["platform", "payments"]), ("s2", ["eng", "sales"])):
        for g in groups:
            n += 1
            _doc(db, specs, g, sid, n)
    n += 1
    hidden = _doc(db, specs, "platform", None, n)
    n += 1
    moved_out = _doc(db, specs, "platform", None, n)
    n += 1
    moved_in = _doc(db, specs, "sales-east", None, n)

    hide(db, "s1", EntityKind.DOCUMENT, hidden.doc_id)
    update_document(db, "s1", moved_out.doc_id, DocumentPatch(group_id="sales-east"))
    update_document(db, "s1", moved_in.doc_id, DocumentPatch(group_id="platform"))
    hides = {("s1", hidden.doc_id)}
    moves = {
        ("s1", moved_out.doc_id): "sales-east",
        ("s1", moved_in.doc_id): "platform",
    }
    return specs, hides, moves


def oracle_visible(
    sid: str,
    specs: list[Spec],
    hides: set[tuple[str, str]],
    moves: dict[tuple[str, str], str],
) -> set[str]:
    out = set()
    for s in specs:
        if s.owner is not None:
            group = s.group if s.owner == sid else None
        elif (sid, s.doc_id) in hides:
            group = None
        else:
            group = moves.get((sid, s.doc_id), s.group)
        if group in ALEX:
            out.add(s.doc_id)
    return out


def queries(specs: list[Spec]) -> list[str]:
    qs = [s.token for s in specs] + [s.phrase for s in specs]
    qs += [COMMON, "handbook", "procedure for platform", "onboarding guide policy"]
    assert len(qs) >= 30
    return qs


def test_zero_leaks_and_recall(db):
    specs, hides, moves = build(db)
    by_id = {s.doc_id: s for s in specs}
    embedder = HashEmbedder()
    qs = queries(specs)
    total_seen = 0

    for sid in SESSIONS:
        allowed = oracle_visible(sid, specs, hides, moves)
        # sanity: oracle's group view matches the persona's chain
        assert set(visible_group_ids(db, sid, "platform")) == set(ALEX)
        assert allowed  # non-vacuous
        assert len(allowed) < len(specs)  # something must be excluded

        for q in qs:
            for kw in ({}, {"k": 20, "candidates": 100}):
                for p in search(db, embedder, sid, ALEX, q, **kw):
                    total_seen += 1
                    assert p.document_id in by_id
                    assert p.document_id in allowed, (
                        f"LEAK: session={sid} got doc token="
                        f"{by_id[p.document_id].token}"
                    )
        # a query with all groups passed must still not leak other sessions' docs
        for q in qs:
            for p in search(db, embedder, sid, GROUPS, q, k=20, candidates=100):
                s = by_id[p.document_id]
                assert s.owner in (None, sid)
                if s.owner is None:
                    assert (sid, s.doc_id) not in hides

        # positive recall: every visible doc is found by its unique token
        for doc_id in allowed:
            hits = search(db, embedder, sid, ALEX, by_id[doc_id].token)
            assert doc_id in {h.document_id for h in hits}, (
                f"recall miss: session={sid} token={by_id[doc_id].token}"
            )
        # and every excluded doc is never found by its own token
        for s in specs:
            if s.doc_id not in allowed:
                hits = search(db, embedder, sid, ALEX, s.token, k=20, candidates=100)
                assert s.doc_id not in {h.document_id for h in hits}

    assert total_seen > 0
