"""Shared command helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
import json

from pydantic import BaseModel

from cli_tools_shared.output import print_json, print_table


def model_to_dict(item: Any) -> Dict[str, Any]:
    if isinstance(item, BaseModel):
        return item.model_dump(mode="json")
    return item


def parse_properties(properties: Optional[str]) -> Optional[List[str]]:
    if properties is None:
        return None
    fields = [field.strip() for field in properties.split(",") if field.strip()]
    if not fields:
        raise ValueError("--properties must include at least one field")
    return fields


def extract_field(item: Any, field: str) -> Any:
    value = model_to_dict(item)
    for part in field.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def extract_fields(items: List[Any], fields: List[str]) -> List[Dict[str, Any]]:
    return [{field: extract_field(item, field) for field in fields} for item in items]


def emit(
    data: Any,
    table: bool,
    properties: Optional[str],
    default_columns: List[str],
) -> None:
    fields = parse_properties(properties)
    output = data

    if fields is not None:
        items = data if isinstance(data, list) else [data]
        extracted = extract_fields(items, fields)
        output = extracted if isinstance(data, list) else extracted[0]

    if table:
        if isinstance(output, list):
            columns = fields if fields is not None else default_columns
            print_table(output, columns, columns)
            return
        if fields is not None:
            print_table([output], fields, fields)
            return
        rows = [
            {"field": key, "value": json.dumps(value) if isinstance(value, (dict, list)) else value}
            for key, value in model_to_dict(output).items()
            if value is not None
        ]
        print_table(rows, ["field", "value"], ["Field", "Value"])
        return

    print_json(output)


def parse_json_object(value: Optional[str], option_name: str) -> Optional[Dict[str, Any]]:
    if value is None:
        return None
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError(f"{option_name} must be a JSON object")
    return parsed


def parse_json_array(value: Optional[str], option_name: str) -> Optional[List[Any]]:
    if value is None:
        return None
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise ValueError(f"{option_name} must be a JSON array")
    return parsed


def read_body(body: Optional[str], body_file: Optional[Path]) -> Optional[str]:
    if body is not None and body_file is not None:
        raise ValueError("Use either --body or --body-file, not both")
    if body_file is None:
        return body
    return body_file.read_text()


def confirm_delete(resource: str, resource_id: str, force: bool) -> None:
    if force:
        return
    import typer

    if not typer.confirm(f"Delete {resource} {resource_id}?"):
        raise typer.Exit(0)
