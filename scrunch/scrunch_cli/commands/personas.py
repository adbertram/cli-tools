"""Persona commands for Scrunch CLI."""
COMMAND_CREDENTIALS = {
    "list": ["api_key"],
    "get": ["api_key"],
    "create": ["api_key"],
    "update": ["api_key"],
    "delete": ["api_key"],
}

import typer
from typing import Optional, List

from ..client import get_client
from ..models import CreatePersona, UpdatePersona
from .helpers import model_to_dict
from cli_tools_shared.output import command, print_json, print_table
from cli_tools_shared.filters import apply_filters, apply_properties_filter


app = typer.Typer(help="Manage brand personas", no_args_is_help=True)


@app.command("list")
@command
def personas_list(
    brand_id: int = typer.Argument(..., help="Brand ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of items to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """List personas for a brand.

    Examples:
        scrunch personas list 123
        scrunch personas list 123 --table
        scrunch personas list 123 --limit 10
    """
    client = get_client()
    items = client.list_personas(brand_id, limit=limit)
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
                ["id", "name", "description"],
                ["ID", "Name", "Description"],
            )
    else:
        print_json(items)



@app.command("get")
@command
def personas_get(
    brand_id: int = typer.Argument(..., help="Brand ID"),
    persona_id: int = typer.Argument(..., help="Persona ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """Get details for a specific persona.

    Examples:
        scrunch personas get 123 456
        scrunch personas get 123 456 --table
    """
    client = get_client()
    item = client.get_persona(brand_id, persona_id)
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



@app.command("create")
@command
def personas_create(
    brand_id: int = typer.Argument(..., help="Brand ID"),
    name: str = typer.Option(..., "--name", "-n", help="Persona name"),
    description: str = typer.Option(..., "--description", "-d", help="Persona description"),
):
    """Create a new persona for a brand.

    Examples:
        scrunch personas create 123 --name "Developer" --description "Software developer persona"
    """
    client = get_client()
    data = CreatePersona(name=name, description=description)
    result = client.create_persona(brand_id, data)
    print_json(model_to_dict(result))



@app.command("update")
@command
def personas_update(
    brand_id: int = typer.Argument(..., help="Brand ID"),
    persona_id: int = typer.Argument(..., help="Persona ID"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Persona name"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Persona description"),
):
    """Update a persona.

    Examples:
        scrunch personas update 123 456 --name "New Name"
    """
    client = get_client()
    data = UpdatePersona(name=name, description=description)
    result = client.update_persona(brand_id, persona_id, data)
    print_json(model_to_dict(result))



@app.command("delete")
@command
def personas_delete(
    brand_id: int = typer.Argument(..., help="Brand ID"),
    persona_id: int = typer.Argument(..., help="Persona ID"),
):
    """Archive (delete) a persona.

    Examples:
        scrunch personas delete 123 456
    """
    client = get_client()
    client.delete_persona(brand_id, persona_id)
    print_json({"status": "deleted", "brand_id": brand_id, "persona_id": persona_id})

