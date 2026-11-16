import json
from pathlib import Path
from typing import Any

from phoebe.api.openapi_export import export_openapi

ROOT = Path(__file__).resolve().parents[2]
COMMITTED = ROOT / "frontend" / "openapi.json"


def test_committed_schema_matches_app() -> None:
    committed = json.loads(COMMITTED.read_text())
    assert committed == export_openapi(), (
        "frontend/openapi.json is stale; "
        "run: uv run python -m phoebe openapi > frontend/openapi.json"
    )


def test_event_schemas_present() -> None:
    schema = export_openapi()
    names = {"MetaEvent", "DeltaEvent", "DoneEvent", "ErrorEvent", "StatusOut"}
    assert names <= set(schema["components"]["schemas"])


def _resolve(schema: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
    ref = node.get("$ref")
    if ref is None:
        return node
    target: Any = schema
    for part in ref.removeprefix("#/").split("/"):
        target = target[part]
    return target


def test_doc_status_is_enum() -> None:
    schema = export_openapi()
    prop = schema["components"]["schemas"]["DocumentOut"]["properties"]["status"]
    assert _resolve(schema, prop)["enum"] == ["processing", "indexed", "failed"]
