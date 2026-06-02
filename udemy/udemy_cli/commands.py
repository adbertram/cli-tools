"""Course commands for Udemy CLI."""
COMMAND_CREDENTIALS = {
    "get": [
        "personal_access_token"
    ],
    "list": [
        "personal_access_token"
    ],
    "management": [
        "browser_session"
    ],
    "update": [
        "browser_session"
    ]
}

import json
from pathlib import Path
from typing import Optional, List

import typer
from pydantic import BaseModel

from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.filter_map import FilterMap
from cli_tools_shared.output import handle_error, print_json, print_table
from .client import get_client


app = typer.Typer(help="Manage instructor courses", no_args_is_help=True)
COURSE_FILTER_MAP = FilterMap()


def model_to_dict(item):
    """Convert Pydantic models to dictionaries."""
    if isinstance(item, BaseModel):
        return item.model_dump()
    return item


def extract_field(item, field: str):
    """Extract a field value using dot notation."""
    value = model_to_dict(item)
    for part in field.split("."):
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def extract_fields(items: list, fields: list[str]) -> list[dict]:
    """Extract selected fields from each item."""
    return [
        {field: extract_field(item, field) for field in fields}
        for item in items
    ]


def parse_properties(properties: Optional[str]) -> Optional[list[str]]:
    """Parse a comma-separated properties option."""
    if properties is None:
        return None
    fields = [field.strip() for field in properties.split(",") if field.strip()]
    if not fields:
        raise typer.BadParameter("At least one property is required.")
    return fields


def load_update_file(path: Path) -> dict:
    """Load a course management update payload from JSON."""
    try:
        data = json.loads(path.read_text())
    except OSError as e:
        raise ClientError(f"Failed to read update file: {e}") from e
    except json.JSONDecodeError as e:
        raise ClientError(f"Update file is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise ClientError("Update file must contain a JSON object.")
    return data


@app.command("list")
def courses_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of courses to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List instructor-taught courses."""
    try:
        client = get_client()
        courses = client.list_courses(limit=limit, filters=filter)
        fields = parse_properties(properties)
        output = extract_fields(courses, fields) if fields else courses

        if table:
            columns = fields or ["id", "title", "is_published", "rating", "num_reviews", "url"]
            headers = [column.replace("_", " ").title() for column in columns]
            print_table(output, columns, headers)
        else:
            print_json(output)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def courses_get(
    course_id: str = typer.Argument(..., help="Course ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get one instructor-taught course by ID."""
    try:
        client = get_client()
        course = client.get_course(course_id)
        fields = parse_properties(properties)
        output = extract_fields([course], fields)[0] if fields else course

        if table:
            course_dict = model_to_dict(output)
            rows = [{"field": key, "value": str(value)} for key, value in course_dict.items()]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(output)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("management")
def courses_management(
    course_id: str = typer.Argument(..., help="Numeric Udemy course ID"),
):
    """Get browser-backed course management fields except curriculum."""
    try:
        client = get_client()
        print_json(client.get_course_management(course_id))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update")
def courses_update(
    course_id: str = typer.Argument(..., help="Numeric Udemy course ID"),
    update_file: Path = typer.Option(
        ...,
        "--file",
        "-f",
        help="JSON file containing course management fields to update",
        exists=True,
        dir_okay=False,
        readable=True,
    ),
):
    """Update browser-backed course management fields except curriculum."""
    try:
        client = get_client()
        updates = load_update_file(update_file)
        print_json(client.update_course_management(course_id, updates))
    except Exception as e:
        raise typer.Exit(handle_error(e))
