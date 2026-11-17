"""`make eval`: run the question set through the real chat pipeline.

Owner-run only: it calls AWS (Titan, the rewriter, the guardrail and the
answer models) and costs money. It runs the app in-process against the
separate `_live` database, like `make live-check`, never a deployed env.

Env: MODEL (haiku | haiku-direct | kimi-k3.1 | glm-5.3 | gpt-oss-120b | all,
or a comma list; default haiku), CASES (ids or categories, comma list),
REPEAT (default 1), YES=1 to skip the cost confirmation. Plus the live
settings `make live-check` needs (PHOEBE_LIVE_DATABASE_URL, PHOEBE_*).
"""

import json
import os
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from fastapi.testclient import TestClient

from phoebe.auth import hash_password
from phoebe.chat.models import AnswerModel, Message, make_models
from phoebe.config import Settings
from phoebe.db import PsycopgDatabase
from phoebe.evals.candidates import Candidate, resolve
from phoebe.evals.cases import Case, load_cases
from phoebe.evals.converse import ConverseAnswerModel, ModelUnsupported
from phoebe.evals.cost import confirm, estimate
from phoebe.evals.grade import Failure, grade
from phoebe.evals.live import (
    CSRF,
    build_app,
    live_database_url,
    parse_sse,
    require_live_settings,
)
from phoebe.evals.scorecard import CaseResult, render, summarize

# backend/evals/results; this file is backend/src/phoebe/evals/run.py.
RESULTS_DIR = Path(__file__).resolve().parents[3] / "evals" / "results"
PASSWORD = "eval-only"  # hashed below; never leaves this process
# Raised in the eval's own Settings so a full run is never throttled.
EVAL_CHAT_CAP = 100_000
# max_tokens for candidates (reasoning models think before answering).
CANDIDATE_MAX_TOKENS = 4_096


class Recording:
    """Wraps the answer model: notes a ModelUnsupported (the app turns every
    model error into a 3115 refusal, so the runner could not see it otherwise)
    and the token usage a ConverseStream model reports."""

    def __init__(self, inner: AnswerModel) -> None:
        self.inner = inner
        self.unsupported = False

    def stream(self, messages: Sequence[Message]) -> Iterator[str]:
        try:
            yield from self.inner.stream(messages)
        except ModelUnsupported:
            self.unsupported = True
            raise

    def usage(self) -> tuple[int, int]:
        u = getattr(self.inner, "usage", None) or {}
        return int(u.get("inputTokens", 0)), int(u.get("outputTokens", 0))


class ResultsFile:
    """One JSON line per case, flushed as it is written, so a crash or Ctrl-C
    leaves every finished case on disk."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fh: TextIO | None = None

    def write(self, result: CaseResult) -> None:
        if self._fh is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = self.path.open("a", encoding="utf-8")
        self._fh.write(json.dumps(asdict(result), default=str) + "\n")
        self._fh.flush()

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()


def _turn(
    client: TestClient, question: str
) -> tuple[dict[str, Any] | None, str | None]:
    """The turn's `done` payload, or None and the error that replaced it."""
    r = client.post("/api/chat", json={"question": question}, headers=CSRF)
    if r.status_code != 200:
        try:
            detail = r.json().get("detail")
        except ValueError:
            detail = None
        return None, f"http {r.status_code} {detail or ''}".strip()
    events = parse_sse(r.text)
    if events is None:
        return None, "malformed stream"
    for name, data in events:
        if name == "error":
            return None, f"error event {data.get('code')}"
    done = [data for name, data in events if name == "done"]
    if len(done) != 1:
        return None, "no done event"
    return done[0], None


def run_case(
    client_factory: Callable[[], TestClient],
    case: Case,
    model: str,
    repeat: int,
    usage: Callable[[], tuple[int, int]] | None = None,
) -> CaseResult:
    """Plays every turn in one fresh session and grades each turn that has
    expectations. Failures are prefixed with their turn number."""
    client = client_factory()
    before = usage() if usage else (0, 0)
    failures: list[Failure] = []
    done: dict[str, Any] | None = None
    latency = 0.0
    for i, turn in enumerate(case.turns, start=1):
        start = time.monotonic()
        done, error = _turn(client, turn.question)
        latency = time.monotonic() - start
        if turn.expect is not None:
            failures += [
                Failure(f.kind, f"turn {i}: {f.detail}")
                for f in grade(turn.expect, done, error)
            ]
    after = usage() if usage else (0, 0)
    return CaseResult(
        model=model,
        case_id=case.id,
        category=case.category,
        repeat=repeat,
        failures=failures,
        latency_s=latency,
        in_tok=after[0] - before[0],
        out_tok=after[1] - before[1],
        text=str((done or {}).get("text", "")),
        done=done,
    )


def run_model(
    client_factory: Callable[[], TestClient],
    cases: list[Case],
    model: str,
    repeat: int,
    recording: Recording,
    out: ResultsFile,
) -> tuple[list[CaseResult], bool]:
    """Every case `repeat` times; stops early if the model is unsupported."""
    results: list[CaseResult] = []
    for n in range(repeat):
        for c in cases:
            result = run_case(client_factory, c, model, n, recording.usage)
            if recording.unsupported:
                print(
                    f"{model}: unsupported (the model rejected the request); skipping"
                )
                return results, True
            results.append(result)
            out.write(result)
            print(f"{model} {c.id}: {'pass' if not result.failures else 'FAIL'}")
    return results, False


def eval_settings(url: str, scratch: Path) -> Settings:
    """The eval app's settings: the live database, raised chat caps, and its own
    in-process counters and kill switch. Explicit values beat PHOEBE_* env, so a
    shell set up for a deployed env can never make an eval read or write that
    env's state table (kill switch or counters)."""
    return Settings(  # pyright: ignore[reportCallIssue]
        database_url=url,
        password_hash=hash_password(PASSWORD),
        cookie_secure=False,
        chat_per_session_hour=EVAL_CHAT_CAP,
        chat_global_day=EVAL_CHAT_CAP,
        limits_backend="memory",
        control_backend="file",
        control_file=scratch / "control.json",
    )


def _answer_model(c: Candidate, settings: Settings) -> AnswerModel:
    if c.harness:
        return make_models(settings)[0]
    assert c.model_id is not None
    # Reasoning models spend output tokens on thinking before the answer; the
    # app's cap (700) would cut them off. The answer itself is still limited by
    # PHOEBE_ANSWER_MAX_CHARS in the app.
    return ConverseAnswerModel(
        c.model_id, settings.aws_region, max_tokens=CANDIDATE_MAX_TOKENS
    )


def main(argv: list[str], env: Mapping[str, str] | None = None) -> int:
    env = os.environ if env is None else env
    url = live_database_url(env)  # before anything that could call AWS
    # `make eval` passes unset variables as "", so empty means the default.
    models = resolve(env.get("MODEL") or "haiku")
    only = {s.strip() for s in (env.get("CASES") or "").split(",") if s.strip()} or None
    repeat = max(1, int(env.get("REPEAT") or "1"))
    cases = load_cases(only=only)
    if not cases:
        raise SystemExit("no cases match CASES")
    est = estimate(cases, models, repeat)
    if not confirm(est, yes=env.get("YES") == "1", stdin_isatty=sys.stdin.isatty()):
        return 2

    scratch = Path(tempfile.mkdtemp(prefix="phoebe-eval-"))
    settings = eval_settings(url, scratch)
    require_live_settings(settings)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    db = PsycopgDatabase(url)
    results: list[CaseResult] = []
    unsupported: set[str] = set()
    try:
        for m in models:
            recording = Recording(_answer_model(m, settings))
            app = build_app(db, settings, recording)

            def factory(app: Any = app) -> TestClient:
                c = TestClient(app)
                r = c.post("/api/login", json={"password": PASSWORD}, headers=CSRF)
                if r.status_code != 204:
                    raise SystemExit(f"eval login failed: {r.status_code}")
                return c

            out = ResultsFile(RESULTS_DIR / f"{stamp}-{m.name}.jsonl")
            try:
                got, skipped = run_model(factory, cases, m.name, repeat, recording, out)
            finally:
                out.close()
            results += got
            if skipped:
                unsupported.add(m.name)
    finally:
        db.close()
    print()
    print(render(summarize(results, models, unsupported), results))
    print(f"\nresults: {RESULTS_DIR}/{stamp}-*.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
