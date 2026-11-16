"""Per-container dependencies shared by every Lambda handler."""

import functools

from phoebe.api.app import Deps, build_deps, make_database
from phoebe.config import Settings, resolve_secrets
from phoebe.logconfig import configure_logging


@functools.cache
def deps() -> Deps:
    """Built once per container from PHOEBE_* env, the same way the API builds it."""
    settings = Settings()
    configure_logging(settings.log_level)
    settings = resolve_secrets(settings)
    db = make_database(settings)
    try:
        return build_deps(settings, db)
    except BaseException:
        db.close()
        raise
