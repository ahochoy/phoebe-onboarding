"""Spend-safety enforcement: login throttle, upload/chat caps, kill switch.

Everything fails closed: if a store cannot answer, the AI path is refused with
503 `chat_paused` and nothing is admitted.
"""

import hashlib
import ipaddress
import re

from fastapi import HTTPException, Request

from phoebe.config import Settings
from phoebe.limits import LimitsUnavailable

HOUR = 3600
DAY = 86400


_PORT = re.compile(r"^(.*):\d+$")


def client_ip(request: Request, header: str | None) -> str:
    """The throttle key for this client.

    With `header` (CloudFront-Viewer-Address: `ip:port`, IPv6 as `addr:port`
    or `[addr]:port`), the trailing port is always stripped and brackets
    removed. A value that still is not an IP keys on a hash of the raw header,
    never on the socket peer (behind CloudFront that is shared by everyone).
    """
    fallback = request.client.host if request.client else "unknown"
    if not header:
        return fallback
    raw = request.headers.get(header, "").strip()
    if not raw:
        return fallback
    m = _PORT.match(raw)
    host = m.group(1) if m else raw
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    try:
        return str(ipaddress.ip_address(host))
    except ValueError:
        return "hdr-" + hashlib.sha256(raw.encode()).hexdigest()[:32]


def _deps(request: Request):
    return request.app.state.deps


def _settings(request: Request) -> Settings:
    return _deps(request).settings


def throttle_login(request: Request) -> None:
    s = _settings(request)
    # The header is only trustworthy behind the origin guard (CloudFront).
    ip = client_ip(request, s.client_ip_header if s.origin_secret else None)
    try:
        ok = _deps(request).counters.hit(
            f"login#{ip}", s.login_per_ip_window, s.login_window_seconds
        )
    except LimitsUnavailable:
        raise HTTPException(503, "chat_paused") from None
    if not ok:
        raise HTTPException(429, "too_many_attempts")


def require_ai_open(request: Request) -> None:
    try:
        state = _deps(request).control.get()
    except LimitsUnavailable:
        raise HTTPException(503, "chat_paused") from None
    if state == "open":
        return
    raise HTTPException(503, "demo_closed" if state == "closed" else "chat_paused")


def _charge(
    request: Request,
    checks: list[tuple[str, int, int, str]],
) -> None:
    counters = _deps(request).counters
    for key, limit, window, code in checks:
        try:
            ok = counters.hit(key, limit, window)
        except LimitsUnavailable:
            raise HTTPException(503, "chat_paused") from None
        if not ok:
            raise HTTPException(429, code)


def charge_chat(request: Request, sandbox: str) -> None:
    s = _settings(request)
    _charge(
        request,
        [
            (f"chat#{sandbox}", s.chat_per_session_hour, HOUR, "session_chat_limit"),
            ("chat#global", s.chat_global_day, DAY, "global_chat_limit"),
        ],
    )


def charge_upload(request: Request, sandbox: str) -> None:
    s = _settings(request)
    _charge(
        request,
        [
            (
                f"upload#{sandbox}",
                s.uploads_per_session_day,
                DAY,
                "session_upload_limit",
            ),
            ("upload#global", s.uploads_global_day, DAY, "global_upload_limit"),
        ],
    )
