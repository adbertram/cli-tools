"""Strict JSON parsers used by finite ntfy commands."""

import json
from cli_tools_shared import ClientError


def parse_publish(output: str) -> dict:
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        raise ClientError("ntfy publish returned malformed JSON") from exc
    if not isinstance(value, dict):
        raise ClientError("ntfy publish returned JSON that is not an object")
    return value


def parse_ndjson(output: str) -> list[dict]:
    rows = []
    for line in output.splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ClientError("ntfy returned malformed NDJSON") from exc
        if not isinstance(value, dict):
            raise ClientError("ntfy returned a non-object NDJSON row")
        rows.append(value)
    return rows


def parse_server_table(output: str, columns: tuple[str, ...]) -> list[dict]:
    """Parse upstream whitespace tables against a fixed, versioned schema."""
    rows = []
    for line in output.splitlines():
        values = line.split()
        if not values:
            continue
        if tuple(value.lower() for value in values[: len(columns)]) == columns:
            continue
        if len(values) != len(columns):
            raise ClientError("ntfy server output does not match the expected table schema")
        rows.append(dict(zip(columns, values, strict=True)))
    return rows
