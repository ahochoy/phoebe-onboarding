"""JSON-line logging for the `phoebe` logger tree, metadata only.

Messages are already metadata by convention (ids, counts, timings). Exceptions
are reduced to their type name: messages and tracebacks may carry user text.
"""

import json
import logging
import sys
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, str] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info and record.exc_info[0] is not None:
            out["exc_type"] = record.exc_info[0].__name__
        return json.dumps(out)


class _PhoebeHandler(logging.StreamHandler):  # type: ignore[type-arg]
    pass


def configure_logging(level: str = "INFO") -> None:
    logger = logging.getLogger("phoebe")
    for h in list(logger.handlers):
        if isinstance(h, _PhoebeHandler):
            logger.removeHandler(h)
    handler = _PhoebeHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logger.addHandler(handler)
    logger.setLevel(level.upper())
    # A runtime (e.g. Lambda) may install a root handler; don't print twice.
    logger.propagate = False
