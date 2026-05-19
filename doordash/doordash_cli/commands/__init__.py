"""Shared command helpers for DoorDash CLI."""
from pydantic import BaseModel

from cli_tools_shared.filters import apply_properties_filter
from cli_tools_shared.output import print_output


def emit_rows(rows, *, table, properties, columns):
    """Render rows to JSON or table. `columns` is an ordered {key: header} dict
    (Python 3.7+ dict insertion order is part of the language spec)."""
    dicts = [r.model_dump(mode="json") if isinstance(r, BaseModel) else r for r in rows]
    if properties:
        keys = [p.strip() for p in properties.split(",") if p.strip()]
        print_output(apply_properties_filter(dicts, properties), table=table, columns=keys, headers=keys)
        return
    print_output(dicts, table=table, columns=list(columns), headers=list(columns.values()))
