"""Live end-to-end chat check against real AWS (Titan, Bedrock, the guardrail and the configured answer backend: converse or harness).

Owner-gated and never part of `make test` or CI: it calls AWS and costs money.
Run it with `make live-check` after `infra/ai` is applied.

It runs the app in-process (FastAPI TestClient over `create_app`) with real
components built from PHOEBE_* env, against a SEPARATE database named by
PHOEBE_LIVE_DATABASE_URL, whose database name must end in `_live`. The database
is migrated and seeded with the configured embedder first.

Output is pass/fail per check plus citation titles. It never prints question
or answer text. Exit status is non-zero if any check fails.
"""

import sys
from typing import Any

from fastapi.testclient import TestClient

from phoebe.auth import hash_password
from phoebe.config import Settings
from phoebe.db import PsycopgDatabase
from phoebe.evals.live import (
    CSRF,
    build_app,
    live_database_url,
    parse_sse,
    require_live_settings,
)

PASSWORD = "live-check-only"  # hashed below; never leaves this process

Q_PTO = "How many PTO days do I get?"
Q_FOLLOW_UP = "And can I carry them over?"
Q_OUT_OF_SCOPE = "What's the Sales East quota?"


def ask(client: TestClient, question: str) -> dict[str, Any] | None:
    """Return the `done` payload, or None if the stream did not finish cleanly."""
    r = client.post("/api/chat", json={"question": question}, headers=CSRF)
    if r.status_code != 200:
        return None
    events = parse_sse(r.text)
    if events is None:
        return None
    done = [data for name, data in events if name == "done"]
    return done[0] if len(done) == 1 else None


def titles(done: dict[str, Any]) -> list[str]:
    return sorted({c["document_title"] for c in done["citations"]})


class Report:
    def __init__(self) -> None:
        self.failed = 0

    def check(self, label: str, ok: bool, detail: str = "") -> None:
        self.failed += 0 if ok else 1
        print(
            f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else "")
        )


def check_pto(report: Report, label: str, done: dict[str, Any] | None) -> None:
    if done is None:
        report.check(f"{label}: stream completed", False)
        return
    text = done["text"]
    report.check(f"{label}: answered, not refused", not done["refused"])
    report.check(
        f"{label}: has citations", bool(done["citations"]), ", ".join(titles(done))
    )
    report.check(f"{label}: mentions 20", "20" in text)


def check_follow_up(report: Report, done: dict[str, Any] | None) -> None:
    if done is None:
        report.check("follow-up: stream completed", False)
        return
    cited = bool(done["citations"])
    report.check(
        "follow-up: cited or refused, never uncited",
        cited or done["refused"],
        ", ".join(titles(done)) if cited else "refused",
    )


def check_out_of_scope(report: Report, done: dict[str, Any] | None) -> None:
    if done is None:
        report.check("out-of-scope: stream completed", False)
        return
    report.check("out-of-scope: refused", done["refused"])
    report.check("out-of-scope: no citations", not done["citations"])


def main() -> int:
    url = live_database_url()
    settings = Settings(  # pyright: ignore[reportCallIssue]
        database_url=url, password_hash=hash_password(PASSWORD), cookie_secure=False
    )
    require_live_settings(settings)
    print(
        f"embedder={settings.embedder} answer={settings.answer_backend} "
        f"rewriter={settings.rewriter_backend} "
        f"guardrail={'on' if settings.guardrail_id else 'off'}"
    )
    report = Report()
    db = PsycopgDatabase(url)
    try:
        client = TestClient(build_app(db, settings))
        r = client.post("/api/login", json={"password": PASSWORD}, headers=CSRF)
        report.check("login", r.status_code == 204)
        if r.status_code == 204:
            check_pto(report, "pto", ask(client, Q_PTO))
            check_follow_up(report, ask(client, Q_FOLLOW_UP))
            check_out_of_scope(report, ask(client, Q_OUT_OF_SCOPE))
    finally:
        db.close()
    print("ALL PASS" if report.failed == 0 else f"{report.failed} FAILED")
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
