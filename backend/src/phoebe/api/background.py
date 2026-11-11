import logging
from collections.abc import Callable
from typing import Any

_log = logging.getLogger("phoebe.api")


def run_guarded(fn: Callable[..., Any], *args: Any, request_id: str) -> None:
    """Run background work; never let an exception (or its message) escape.

    Only the request id and exception type name are logged: messages and
    tracebacks may contain document text. Background work must go through here,
    never call the raw handler directly.
    """
    try:
        fn(*args)
    except Exception as exc:  # noqa: BLE001 - log type only, swallow
        _log.error(
            "background job failed %s request_id=%s", type(exc).__name__, request_id
        )
