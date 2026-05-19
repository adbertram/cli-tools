"""PixVerse video generation commands."""
COMMAND_CREDENTIALS = {
    "text": ["api_key"],
    "status": ["api_key"],
}

import typer
from typing import Optional

from pydantic import BaseModel

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error


app = typer.Typer(help="Generate and inspect PixVerse videos", no_args_is_help=True)


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


@app.command("text")
def videos_text(
    prompt: str = typer.Argument(..., help="Prompt for the video generation"),
    model: Optional[str] = typer.Option(None, help="PixVerse model identifier"),
    duration: Optional[int] = typer.Option(None, help="Requested duration in seconds"),
    quality: Optional[str] = typer.Option(None, help="Requested quality tier"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include (supports dot-notation)"),
):
    """
    Submit a text-to-video generation job.

    Examples:
        pixverse videos text "A neon city skyline at dusk"
        pixverse videos text "A neon city skyline at dusk" --model v4.5 --duration 8
        pixverse videos text "A neon city skyline at dusk" --properties "id,operation"
    """
    try:
        client = get_client()
        job = client.generate_text_video(
            prompt=prompt,
            model=model,
            duration=duration,
            quality=quality,
        )

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            job = extract_fields([job], fields)[0]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([job], fields, fields)
            else:
                print_table(
                    [job],
                    ["id", "operation", "model", "duration", "quality"],
                    ["ID", "Operation", "Model", "Duration", "Quality"],
                )
        else:
            print_json(job)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("status")
def videos_status(
    item_id: str = typer.Argument(..., help="The PixVerse video_id"),
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include (supports dot-notation)"),
):
    """
    Get the current job status for a PixVerse video generation.

    Examples:
        pixverse videos status VIDEO_ID
        pixverse videos status VIDEO_ID --table
        pixverse videos status VIDEO_ID --properties "id,status_code"
    """
    try:
        client = get_client()
        item = client.get_item(item_id)

        # Apply properties field selection with dot-notation support
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            item = extract_fields([item], fields)[0]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([item], fields, fields)
            else:
                # Convert model to key-value table
                item_dict = model_to_dict(item)
                rows = [{"field": k, "value": str(v)} for k, v in item_dict.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(item)

    except Exception as e:
        raise typer.Exit(handle_error(e))
