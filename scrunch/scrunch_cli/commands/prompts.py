"""Prompt commands for Scrunch CLI."""
import typer
from typing import Optional, List

from ..client import get_client
from ..models import CreatePrompt, PromptStage, AIPlatform
from .helpers import model_to_dict, extract_fields
from cli_tools_shared.output import print_json, print_table, handle_error
from cli_tools_shared.filters import apply_filters, apply_properties_filter


app = typer.Typer(help="Manage brand prompts", no_args_is_help=True)


@app.command("list")
def prompts_list(
    brand_id: int = typer.Argument(..., help="Brand ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of items to return"),
    offset: int = typer.Option(0, "--offset", "-o", help="Pagination offset"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List prompts for a brand.

    Examples:
        scrunch prompts list 123
        scrunch prompts list 123 --table
        scrunch prompts list 123 --limit 50 --offset 100
        scrunch prompts list 123 --filter "stage:eq:Awareness"
    """
    try:
        client = get_client()
        items = client.list_prompts(brand_id, limit=limit, offset=offset)
        items = [model_to_dict(i) for i in items]

        if filter:
            items = apply_filters(items, filter)
        if properties:
            items = apply_properties_filter(items, properties)

        if table:
            if properties:
                cols = [f.strip() for f in properties.split(",")]
                print_table(items, cols, cols)
            else:
                print_table(
                    items,
                    ["id", "text", "stage", "persona_id"],
                    ["ID", "Text", "Stage", "Persona ID"],
                )
        else:
            print_json(items)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def prompts_get(
    brand_id: int = typer.Argument(..., help="Brand ID"),
    prompt_id: int = typer.Argument(..., help="Prompt ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get details for a specific prompt.

    Examples:
        scrunch prompts get 123 456
        scrunch prompts get 123 456 --table
    """
    try:
        client = get_client()
        item = client.get_prompt(brand_id, prompt_id)
        item = model_to_dict(item)

        if properties:
            item = apply_properties_filter([item], properties)[0]

        if table:
            if properties:
                cols = [f.strip() for f in properties.split(",")]
                print_table([item], cols, cols)
            else:
                rows = [{"field": k, "value": str(v)} for k, v in item.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(item)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def prompts_create(
    brand_id: int = typer.Argument(..., help="Brand ID"),
    text: str = typer.Option(..., "--text", help="Prompt text"),
    stage: PromptStage = typer.Option(..., "--stage", "-s", help="Prompt stage (Advice, Awareness, Evaluation, Comparison, Other)"),
    persona_id: Optional[int] = typer.Option(None, "--persona-id", help="Persona ID to associate"),
    tags: Optional[str] = typer.Option(None, "--tags", help="Comma-separated tags"),
    key_topics: Optional[str] = typer.Option(None, "--key-topics", help="Comma-separated key topics"),
    platforms: Optional[str] = typer.Option(None, "--platforms", help="Comma-separated platforms (chatgpt, claude, perplexity, etc.)"),
):
    """Create a new prompt for a brand.

    Examples:
        scrunch prompts create 123 --text "What is the best AI tool?" --stage Awareness
        scrunch prompts create 123 --text "Compare AI tools" --stage Comparison --platforms "chatgpt,claude"
    """
    try:
        client = get_client()
        data = CreatePrompt(
            text=text,
            stage=stage,
            persona_id=persona_id,
            tags=[t.strip() for t in tags.split(",")] if tags else None,
            key_topics=[t.strip() for t in key_topics.split(",")] if key_topics else None,
            platforms=[p.strip() for p in platforms.split(",")] if platforms else None,
        )
        result = client.create_prompt(brand_id, data)
        print_json(model_to_dict(result))

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def prompts_delete(
    brand_id: int = typer.Argument(..., help="Brand ID"),
    prompt_id: int = typer.Argument(..., help="Prompt ID"),
):
    """Archive (delete) a prompt.

    Examples:
        scrunch prompts delete 123 456
    """
    try:
        client = get_client()
        client.delete_prompt(brand_id, prompt_id)
        print_json({"status": "deleted", "brand_id": brand_id, "prompt_id": prompt_id})

    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "create": [
        "api_key"
    ],
    "delete": [
        "api_key"
    ],
    "get": [
        "api_key"
    ],
    "list": [
        "api_key"
    ]
}
