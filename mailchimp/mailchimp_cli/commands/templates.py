"""Templates commands for Mailchimp CLI."""
import typer
from typing import Optional

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error

app = typer.Typer(help="Manage email templates")


@app.command("list")
def templates_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    count: int = typer.Option(10, "--count", "-c", help="Number of templates to return"),
    offset: int = typer.Option(0, "--offset", "-o", help="Offset for pagination"),
    template_type: Optional[str] = typer.Option(None, "--type", help="Filter by type (user, base, gallery)"),
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

        result = client.list_templates(count=count, offset=offset, **kwargs)
        templates = result.get("templates", [])

        if table:
            table_data = []
            for template in templates:
                table_data.append({
                    "id": template.get("id", ""),
                    "type": template.get("type", ""),
                    "name": template.get("name", ""),
                    "category": template.get("category", "N/A"),
                    "created": template.get("date_created", "")[:10] if template.get("date_created") else "N/A",
                })

            print_table(
                table_data,
                ["id", "type", "name", "category", "created"],
                ["ID", "Type", "Name", "Category", "Created"],
            )
        else:
            print_json(result)

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
