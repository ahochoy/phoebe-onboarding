import json
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from conftest import CSRF, PW
from phoebe.api.app import Deps
from phoebe.chat.models import ExtractiveAnswerModel, Message, ModelUnavailable
from phoebe.db import PsycopgDatabase
from phoebe.evals.cases import Case
from phoebe.evals.converse import ModelUnsupported
from phoebe.evals.run import Recording, ResultsFile, main, run_case, run_model
from phoebe.seed import load_seed


def case(raw: dict[str, Any]) -> Case:
    return Case.model_validate(raw)


PTO = case(
    {
        "id": "pto",
        "category": "fact",
        "turns": [
            {
                "question": "How many PTO days do I get?",
                "expect": {
                    "answered": True,
                    "must_cite": ["Employee Handbook"],
                    "must_contain": ["20"],
                },
            }
        ],
    }
)


@pytest.fixture
def factory(db: PsycopgDatabase, client: TestClient) -> Callable[[], TestClient]:
    deps: Deps = client.app.state.deps  # type: ignore[attr-defined]
    load_seed(db, deps.embedder, deps.settings.seed_dir)

    def make() -> TestClient:
        c = TestClient(client.app)
        r = c.post("/api/login", json={"password": PW}, headers=CSRF)
        assert r.status_code == 204
        return c

    return make


def set_answer(client: TestClient, model: Any) -> None:
    client.app.state.deps.answer = model  # type: ignore[attr-defined]


class Down:
    def stream(self, messages: Sequence[Message]) -> Iterator[str]:
        raise ModelUnavailable("down")
        yield ""  # pragma: no cover


class Unsupported:
    calls = 0

    def stream(self, messages: Sequence[Message]) -> Iterator[str]:
        Unsupported.calls += 1
        raise ModelUnsupported("shape")
        yield ""  # pragma: no cover


def test_run_case_passes_simple_fact(factory: Callable[[], TestClient]) -> None:
    res = run_case(factory, PTO, "haiku", 0)
    assert res.failures == [], res.failures
    assert res.done is not None and res.latency_s > 0


def test_run_case_records_error_event(
    factory: Callable[[], TestClient], client: TestClient
) -> None:
    set_answer(client, Down())
    res = run_case(factory, PTO, "haiku", 0)
    kinds = {f.kind for f in res.failures}
    # The app turns a model failure into a 3115 refusal; the case fails, no raise.
    assert kinds & {"outcome", "error"}
    assert any("3115" in f.detail for f in res.failures)


def test_follow_up_runs_after_refused_first_turn(
    factory: Callable[[], TestClient],
) -> None:
    c = case(
        {
            "id": "fu",
            "category": "follow_up",
            "turns": [
                {
                    "question": "How many PTO days do I get?",
                    "expect": {"answered": False, "code": "1001"},
                },
                {
                    "question": "How many PTO days do I get?",
                    "expect": {"answered": True, "must_contain": ["20"]},
                },
            ],
        }
    )
    res = run_case(factory, c, "haiku", 0)
    details = [f.detail for f in res.failures]
    assert details and all(d.startswith("turn 1:") for d in details)


def test_each_case_gets_a_fresh_session(factory: Callable[[], TestClient]) -> None:
    first = factory()
    first.post(
        "/api/chat", json={"question": "How many PTO days do I get?"}, headers=CSRF
    )
    second = factory()
    assert second.get("/api/chat/history").json() == []


def test_unsupported_model_is_skipped_not_fatal(
    factory: Callable[[], TestClient], client: TestClient, tmp_path: Path
) -> None:
    Unsupported.calls = 0
    rec = Recording(Unsupported())
    set_answer(client, rec)
    results, unsupported = run_model(
        factory,
        [PTO, PTO.model_copy(update={"id": "pto2"})],
        "glm-5.3",
        1,
        rec,
        ResultsFile(tmp_path / "r.jsonl"),
    )
    assert unsupported
    assert Unsupported.calls == 1  # the second case never ran
    assert results == []  # an unsupported model's case is skipped, not scored


def test_results_are_flushed_per_case(
    factory: Callable[[], TestClient], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = ResultsFile(tmp_path / "r.jsonl")
    cases = [PTO.model_copy(update={"id": f"c{i}"}) for i in range(3)]
    calls = {"n": 0}
    real = run_case

    def flaky_run(*args: Any, **kwargs: Any):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("crash")
        return real(*args, **kwargs)

    monkeypatch.setattr("phoebe.evals.run.run_case", flaky_run)
    with pytest.raises(RuntimeError):
        run_model(factory, cases, "haiku", 1, Recording(ExtractiveAnswerModel()), out)
    lines = (tmp_path / "r.jsonl").read_text().splitlines()
    assert [json.loads(line)["case_id"] for line in lines] == ["c0", "c1"]


def test_main_refuses_non_live_database(monkeypatch: pytest.MonkeyPatch) -> None:
    # It must stop before any model call: fail loudly if one is attempted.
    monkeypatch.setattr("phoebe.evals.run.build_app", _no_aws)
    env = {
        "PHOEBE_LIVE_DATABASE_URL": "postgresql://x@localhost/phoebe",
        "MODEL": "haiku",
        "YES": "1",
    }
    with pytest.raises(SystemExit) as info:
        main([], env=env)
    assert "_live" in str(info.value)


def test_main_refuses_without_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("phoebe.evals.run.build_app", _no_aws)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    env = {"PHOEBE_LIVE_DATABASE_URL": "postgresql://x@localhost/phoebe_live"}
    assert main([], env=env) == 2


def test_main_treats_empty_make_variables_as_defaults(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # `make eval` passes MODEL="" REPEAT="" CASES="" when they are not set.
    monkeypatch.setattr("phoebe.evals.run.build_app", _no_aws)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    env = {
        "PHOEBE_LIVE_DATABASE_URL": "postgresql://x@localhost/phoebe_live",
        "MODEL": "",
        "REPEAT": "",
        "CASES": "",
        "YES": "",
    }
    assert main([], env=env) == 2
    assert "chat calls" in capsys.readouterr().out  # haiku, every case, once


def _no_aws(*_: Any, **__: Any) -> Any:
    raise AssertionError("reached the app (and AWS)")


def test_eval_settings_never_use_a_deployed_state_table(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from phoebe.evals.run import eval_settings

    monkeypatch.setenv("PHOEBE_CONTROL_BACKEND", "dynamodb")
    monkeypatch.setenv("PHOEBE_LIMITS_BACKEND", "dynamodb")
    monkeypatch.setenv("PHOEBE_STATE_TABLE", "phoebe-production-state")
    s = eval_settings("postgresql://x@localhost/phoebe_live", tmp_path)
    assert s.control_backend == "file" and s.limits_backend == "memory"
    assert Path(s.control_file).parent == tmp_path


def test_candidates_get_a_larger_token_cap() -> None:
    from phoebe.config import Settings
    from phoebe.evals.candidates import CANDIDATES
    from phoebe.evals.run import CANDIDATE_MAX_TOKENS, _answer_model

    s = Settings(database_url="x", password_hash="x")  # pyright: ignore[reportCallIssue]
    m = _answer_model(CANDIDATES["glm-5.3"], s)
    assert m._max_tokens == CANDIDATE_MAX_TOKENS > s.answer_max_tokens  # type: ignore[attr-defined]


def test_raw_model_output_is_recorded(
    factory: Callable[[], TestClient], client: TestClient
) -> None:
    # The app replaces a refused answer with refusal copy; the raw text shows why.
    rec = Recording(ExtractiveAnswerModel())
    set_answer(client, rec)
    res = run_case(factory, PTO, "haiku", 0, recording=rec)
    assert len(res.raw) == 1 and "[P1]" in res.raw[0]


def test_live_settings_accept_the_converse_backend() -> None:
    from phoebe.config import Settings
    from phoebe.evals.live import require_live_settings

    base: dict[str, Any] = {
        "database_url": "x",
        "password_hash": "x",
        "embedder": "titan",
        "rewriter_backend": "bedrock",
        "guardrail_id": "g",
        "guardrail_version": "1",
    }
    require_live_settings(Settings(answer_backend="converse", **base))  # pyright: ignore[reportCallIssue]
    with pytest.raises(SystemExit, match="PHOEBE_ANSWER_BACKEND"):
        require_live_settings(Settings(answer_backend="extractive", **base))  # pyright: ignore[reportCallIssue]
