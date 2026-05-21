"""Document commands for Msword CLI."""

from typing import List, Optional

import typer
from pydantic import BaseModel

from cli_tools_shared.filters import FilterValidationError, apply_filters, validate_filters
from cli_tools_shared.output import handle_error, print_json, print_table

from .client import get_client

app = typer.Typer(help="Manage Word documents", no_args_is_help=True)
COMMAND_CREDENTIALS = {
    "read": ["no_auth"],
    "convert": ["no_auth"],
    "comments": ["no_auth"],
}


def model_to_dict(item):
    """Convert model or dict to dict for field extraction."""
    if isinstance(item, BaseModel):
        return item.model_dump()
    return item


def extract_field(item, field: str):
    """Extract a field value, supporting dot-notation for nested fields."""
    data = model_to_dict(item)
    value = data
    for part in field.split("."):
        if isinstance(value, dict):
            value = value.get(part)
            continue
        return None
    return value


def extract_fields(items: list, fields: list) -> list:
    """Extract specified fields from items, supporting dot-notation."""
    result = []
    for item in items:
        extracted = {}
        for field in fields:
            extracted[field] = extract_field(item, field)
        result.append(extracted)
    return result


@app.command("read")
def doc_read(
    file: str = typer.Argument(..., help="Path to the .docx file"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Read text content from a Word document."""
    try:
        result = get_client().read_document(file)
        if table:
            rows = [{"field": key, "value": str(value)[:100]} for key, value in model_to_dict(result).items() if value is not None]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(result)
    except Exception as error:
        raise typer.Exit(handle_error(error))


@app.command("convert")
def doc_convert(
    file: str = typer.Argument(..., help="Path to the .docx file"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file path (default: stdout)"),
):
    """Convert a Word document to Markdown."""
    try:
        result = get_client().convert_to_markdown(file)
        if output:
            with open(output, "w", encoding="utf-8") as handle:
                handle.write(result.markdown)
            from cli_tools_shared.output import print_success

            print_success(f"Written to {output}")
            return
        print_json(result)
    except Exception as error:
        raise typer.Exit(handle_error(error))


comments_app = typer.Typer(help="Manage document comments", no_args_is_help=True)
app.add_typer(comments_app, name="comments")


@comments_app.command("list")
def comments_list(
    file: str = typer.Argument(..., help="Path to the .docx file"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of comments to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., author:eq:Jane)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List comments from a Word document."""
    try:
        comments = get_client().extract_comments(file)[:limit]
        if filter:
            try:
                validate_filters(filter)
                dicts = [model_to_dict(comment) for comment in comments]
                comments = apply_filters(dicts, filter)
            except FilterValidationError as error:
                from cli_tools_shared.exceptions import ClientError

                raise ClientError(f"Invalid filter: {error}") from error

        if properties:
            fields = [field.strip() for field in properties.split(",")]
            comments = extract_fields(comments, fields)

        if table:
            if properties:
                fields = [field.strip() for field in properties.split(",")]
                print_table(comments, fields, fields)
            else:
                print_table(comments, ["author", "text", "context"], ["Author", "Comment", "Context"])
        else:
            print_json(comments)
    except Exception as error:
        raise typer.Exit(handle_error(error))


@comments_app.command("get")
def comments_get(
    file: str = typer.Argument(..., help="Path to the .docx file"),
    comment_id: str = typer.Argument(..., help="Comment ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get a single comment from a Word document."""
    try:
        comment = get_client().get_comment(file, comment_id)
        if table:
            rows = [
                {"field": key, "value": value}
                for key, value in model_to_dict(comment).items()
            ]
            print_table(rows, ["field", "value"], ["Field", "Value"])
            return
        print_json(comment)
    except Exception as error:
        raise typer.Exit(handle_error(error))


@comments_app.command("add")
def comments_add(
    file: str = typer.Argument(..., help="Path to the .docx file"),
    text: str = typer.Option(..., "--text", help="Comment text"),
    author: str = typer.Option(..., "--author", help="Comment author name"),
    reference_text: str = typer.Option(..., "--reference-text", help="Text in the document to attach the comment to"),
    occurrence: int = typer.Option(1, "--occurrence", help="Which occurrence of reference-text to target"),
):
    """Add an inline comment to a Word document."""
    try:
        print_json(get_client().add_comment(file, text, author, reference_text, occurrence))
    except Exception as error:
        raise typer.Exit(handle_error(error))
