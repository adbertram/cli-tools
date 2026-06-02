"""Templates commands for Mailchimp CLI."""
import typer
from typing import List, Optional

from cli_tools_shared.filters import apply_filters, apply_limit, apply_properties_filter
from cli_tools_shared.output import print_json, print_table, handle_error

from ..client import get_client

app = typer.Typer(help="Manage email templates")


@app.command("list")
def templates_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(10, "--limit", "-l", help="Maximum number of templates to return"),
    offset: int = typer.Option(0, "--offset", "-o", help="Offset for pagination"),
    template_type: Optional[str] = typer.Option(None, "--type", help="Filter by type (user, base, gallery)"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List all templates.

    Examples:
        mailchimp templates list
        mailchimp templates list --table
        mailchimp templates list --type user
        mailchimp templates list --count 20
    """
    try:
        client = get_client()

        kwargs = {}
        if template_type:
            kwargs["type"] = template_type

        result = client.list_templates(count=limit, offset=offset, **kwargs)
        templates = result.get("templates", [])
        templates = apply_filters(templates, filter)
        templates = apply_limit(templates, limit)
        templates = apply_properties_filter(templates, properties)

        if table:
            columns = [field.strip() for field in properties.split(",")] if properties else ["id", "type", "name", "category", "date_created"]
            headers = [column.replace("_", " ").replace(".", " ").title() for column in columns]
            print_table(templates, columns, headers)
        else:
            print_json(templates)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def templates_get(
    template_id: str = typer.Argument(..., help="The template ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as table"),
):
    """
    Get details for a specific template.

    Examples:
        mailchimp templates get TEMPLATE_ID
        mailchimp templates get TEMPLATE_ID --table
    """
    try:
        client = get_client()
        template = client.get_template(template_id)

        if table:
            summary = [{
                "id": template.get("id", ""),
                "type": template.get("type", ""),
                "name": template.get("name", ""),
                "category": template.get("category", "N/A"),
                "active": template.get("active", False),
                "created": template.get("date_created", "")[:10] if template.get("date_created") else "N/A",
            }]

            print_table(
                summary,
                ["id", "type", "name", "category", "active", "created"],
                ["ID", "Type", "Name", "Category", "Active", "Created"],
            )
        else:
            print_json(template)

    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ]
}
