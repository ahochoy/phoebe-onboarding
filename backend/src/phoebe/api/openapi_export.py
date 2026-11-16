"""Offline OpenAPI export for the frontend's generated client.

Builds the app with no database, AWS or blob store (nothing is touched while
generating the schema), and merges in the SSE event schemas, which no route
returns as a response model.
"""

import json
from typing import Any, cast

from phoebe.api.app import Deps, create_app
from phoebe.chat.events import DeltaEvent, DoneEvent, ErrorEvent, MetaEvent
from phoebe.config import Settings

_EVENTS = (MetaEvent, DeltaEvent, DoneEvent, ErrorEvent)


def export_openapi() -> dict[str, Any]:
    none: Any = None
    settings = Settings(database_url="postgresql://unused", password_hash="unused")
    deps = Deps(none, none, none, none, none, settings)
    schema = create_app(deps).openapi()
    schemas: dict[str, Any] = schema.setdefault("components", {}).setdefault(
        "schemas", {}
    )
    for model in _EVENTS:
        body = model.model_json_schema(
            ref_template="#/components/schemas/{model}", mode="serialization"
        )
        for name, definition in body.pop("$defs", {}).items():
            schemas.setdefault(name, definition)
        schemas[model.__name__] = body
    return cast(dict[str, Any], json.loads(json.dumps(schema)))


def dump_openapi() -> str:
    return json.dumps(export_openapi(), sort_keys=True, indent=2) + "\n"
