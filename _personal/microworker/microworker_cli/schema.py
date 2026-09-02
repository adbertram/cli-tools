"""JSON Schema validation for site envelopes and task records.

The schemas ship as package data under `schemas/`. A validation failure is a
`SchemaError`, a `ClientError`, so every command exits 2 with the jsonschema
message on stderr.

JSON Schema alone is not enough for the task contract. `pay_amount` is declared
`["number", "null"]`, and `float('nan')` IS a JSON Schema number, so a NaN price
validates cleanly and then binds to SQLite as SQL NULL -- making a task the site
priced read back as "no price published". `validate_task` therefore also runs the
`jsonio.check_finite` walk, over the whole record including `raw`, and
`validate_envelope` does the same over the whole envelope.

There is no merged-run schema. Merged tasks live in the SQLite store (`db.py`),
whose table definition is their structure; each one is validated against
`task.schema.json` on the way in. `validate_file()` therefore accepts exactly
one kind of document: a site envelope.
"""

from __future__ import annotations

import json
from pathlib import Path

from cli_tools_shared.exceptions import ClientError
from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match
from referencing import Registry, Resource

from . import jsonio

SCHEMA_DIR = Path(__file__).resolve().parent / "schemas"
ENVELOPE = "envelope"
TASK = "task"
NAMES = (ENVELOPE, TASK)


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
    # A site's raw record is `{"type": "object"}` to the schema, so a NaN
    # nested anywhere inside it satisfies the envelope schema completely.
    jsonio.check_finite(data, label)


def validate_task(data, label: str = "task") -> None:
    validate(data, TASK, label)
    # After the schema, not instead of it: NaN and Infinity satisfy the
    # "number" type and must not survive as a null price.
    jsonio.check_finite(data, label)


def detect_kind(data) -> str:
    """Which schema a loaded document claims to be, from its top-level keys."""
    if not isinstance(data, dict):
        raise SchemaError("document must be a JSON object")
    if "site" in data and "status" in data:
        return ENVELOPE
    raise SchemaError(
        "document is not an envelope (site, status); "
        f"top-level keys: {', '.join(sorted(data))}")


def validate_file(path: Path) -> str:
    """Validate a JSON file as a site envelope; return the kind it matched."""
    if not path.is_file():
        raise SchemaError(f"{path} is not a file")
    data = jsonio.read_file(path)
    kind = detect_kind(data)
    validate(data, kind, str(path))
    return kind
