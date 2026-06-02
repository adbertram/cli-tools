"""Model listing commands for Gemini CLI."""
import typer
from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error

app = typer.Typer(help="List available Gemini models")


@app.command("list")
def models_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    List available Gemini models.

    Example:
        gemini models list
        gemini models list --table
    """
    try:
        client = get_client()
        models = client.list_models()

        model_data = []
        for m in models:
            model_data.append({
                "name": m.name,
                "display_name": getattr(m, 'display_name', 'N/A'),
                "description": getattr(m, 'description', 'N/A'),
                "supported_generation_methods": ', '.join(getattr(m, 'supported_generation_methods', [])),
            })

        if table:
            print_table(
                model_data,
                ["name", "display_name", "description"],
                ["Name", "Display Name", "Description"]
            )
        else:
            print_json(model_data)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "list": [
        "custom"
    ]
}
