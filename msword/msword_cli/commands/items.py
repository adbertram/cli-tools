"""Document commands for Msword CLI."""
import typer
from typing import Optional, List

from pydantic import BaseModel

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error


app = typer.Typer(help="Manage Word documents", no_args_is_help=True)


def model_to_dict(item):
    """Convert model or dict to dict for field extraction."""
    if isinstance(item, BaseModel):
        return item.model_dump()
    return item


def extract_field(item, field: str):
    """Extract a field value, supporting dot-notation for nested fields."""
    data = model_to_dict(item)
    parts = field.split(".")
    value = data
    for part in parts:
        if isinstance(value, dict):
            value = value.get(part)
        else:
            return None
    return value


def extract_fields(items: list, fields: list) -> list:
    """Extract specified fields from items, supporting dot-notation."""
    result = []
    for item in items:
        extracted = {}
        for field in fields:
            value = extract_field(item, field)
            extracted[field] = value
        result.append(extracted)
    return result


@app.command("read")
def doc_read(
    file: str = typer.Argument(..., help="Path to the .docx file"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Read text content from a Word document.

    Examples:
        msword docs read document.docx
        msword docs read document.docx --table
    """
    try:
        client = get_client()
        result = client.read_document(file)

        if table:
            rows = [{"field": k, "value": str(v)[:100]} for k, v in model_to_dict(result).items() if v is not None]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(result)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("convert")
def doc_convert(
    file: str = typer.Argument(..., help="Path to the .docx file"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file path (default: stdout)"),
):
    """
    Convert a Word document to Markdown.

    Examples:
        msword docs convert document.docx
        msword docs convert document.docx --output document.md
    """
    try:
        client = get_client()
        result = client.convert_to_markdown(file)

        if output:
            with open(output, "w") as f:
                f.write(result.markdown)
            from cli_tools_shared.output import print_success
            print_success(f"Written to {output}")
        else:
            print_json(result)
    except Exception as e:
        raise typer.Exit(handle_error(e))


comments_app = typer.Typer(help="Manage document comments", no_args_is_help=True)
app.add_typer(comments_app, name="comments")


@comments_app.command("list")
def comments_list(
    file: str = typer.Argument(..., help="Path to the .docx file"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of comments to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List comments from a Word document.

    Shows each comment along with the text it references.

    Examples:
        msword docs comments list document.docx
        msword docs comments list document.docx --table
        msword docs comments list document.docx --filter "author:Jane"
    """
    try:
        client = get_client()
        comments = client.extract_comments(file)

        # Apply limit
        comments = comments[:limit]

        # Apply filter (client-side)
        if filter:
            from ..filters import validate_filters, apply_filters, FilterValidationError
            try:
                validate_filters(filter)
                dicts = [model_to_dict(c) for c in comments]
                dicts = apply_filters(dicts, filter)
                comments = dicts  # Already dicts after filtering
            except FilterValidationError as e:
                from cli_tools_shared.exceptions import ClientError
                raise ClientError(f"Invalid filter: {e}")

        # Apply properties
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            comments = extract_fields(comments, fields)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(comments, fields, fields)
            else:
                print_table(
                    comments,
                    ["author", "text", "context"],
                    ["Author", "Comment", "Context"],
                )
        else:
            print_json(comments)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@comments_app.command("add")
def comments_add(
    file: str = typer.Argument(..., help="Path to the .docx file"),
    text: str = typer.Option(..., "--text", help="Comment text"),
    author: str = typer.Option(..., "--author", help="Comment author name"),
    reference_text: str = typer.Option(..., "--reference-text", help="Text in the document to attach the comment to"),
    occurrence: int = typer.Option(1, "--occurrence", help="Which occurrence of reference-text to target"),
):
    """
    Add an inline comment to a Word document.

    Anchors the comment to the specified reference text in the document.

    Examples:
        msword docs comments add doc.docx --text "Fix this" --author "Editor" --reference-text "some text"
        msword docs comments add doc.docx --text "Rephrase" --author "Editor" --reference-text "repeated" --occurrence 2
    """
    try:
        client = get_client()
        result = client.add_comment(file, text, author, reference_text, occurrence)
        print_json(result)
    except Exception as e:
        raise typer.Exit(handle_error(e))
