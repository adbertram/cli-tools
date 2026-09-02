"""JSON Schema validation for envelopes, task records and merged runs.

The schemas ship as package data under `schemas/`. A validation failure is a
`SchemaError`, a `ClientError`, so every command exits 2 with the jsonschema
message on stderr.
"""

from __future__ import annotations

import json
from pathlib import Path

from cli_tools_shared.exceptions import ClientError
from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match
from referencing import Registry, Resource

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
ENVELOPE = "envelope"
TASK = "task"
MERGED = "merged"
NAMES = (ENVELOPE, TASK, MERGED)


class SchemaError(ClientError):
    """The document does not satisfy its schema."""


def load(name: str) -> dict:
    return json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text(encoding="utf-8"))


def _registry() -> Registry:
    return Registry().with_resources(
        (f"urn:microworker:{name}", Resource.from_contents(load(name)))
        for name in NAMES)


def validate(data, name: str, label: str) -> None:
    validator = Draft202012Validator(load(name), registry=_registry())
    errors = list(validator.iter_errors(data))
    if not errors:
        return
    error = best_match(errors)
    where = "/".join(str(part) for part in error.absolute_path)
    raise SchemaError(
        f"{label} does not match the {name} schema at "
        f"'{where}': {error.message}")


def validate_envelope(data, label: str = "envelope") -> None:
    validate(data, ENVELOPE, label)


def validate_task(data, label: str = "task") -> None:
    validate(data, TASK, label)


def validate_merged(data, label: str = "merged run") -> None:
    validate(data, MERGED, label)


def detect_kind(data) -> str:
    """Which schema a loaded document claims to be, from its top-level keys."""
    if not isinstance(data, dict):
        raise SchemaError("document must be a JSON object")
    if "run_id" in data and "sites" in data:
        return MERGED
    if "site" in data and "status" in data:
        return ENVELOPE
    raise SchemaError(
        "document is neither an envelope (site, status) nor a merged run "
        f"(run_id, sites); top-level keys: {', '.join(sorted(data))}")


def validate_file(path: Path) -> str:
    """Validate a JSON file against the schema its shape selects; return the kind."""
    if not path.is_file():
        raise SchemaError(f"{path} is not a file")
    data = json.loads(path.read_text(encoding="utf-8"))
    kind = detect_kind(data)
    validate(data, kind, str(path))
    return kind
