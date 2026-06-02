"""Model commands for managing AI Builder models (msdyn_aimodel)."""
import typer
from typing import Optional

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, print_success, handle_error


app = typer.Typer(help="Manage AI Builder models")

COMMAND_CREDENTIALS = {
    "disable": [
        "custom"
    ],
    "enable": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ]
}


# GptPowerPrompt template ID - identifies AI Builder prompts
GPT_POWER_PROMPT_TEMPLATE_ID = "edfdb190-3791-45d8-9a6c-8f90a37c278a"


@app.command("list")
def model_list(
    prompts_only: bool = typer.Option(
        False,
        "--prompts",
        help="Show only GPT prompt models",
    ),
    filter: Optional[list[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., name:ilike:%model%)",
    ),
    limit: int = typer.Option(
        100,
        "--limit",
        "-l",
        help="Maximum number of models to return",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Output as formatted table",
    ),
    output: Optional[str] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output format: json (default) or table",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of fields to include in output",
    ),
):
    """
    List AI Builder models in the environment.

    Examples:
        copilot model list
        copilot model list --prompts --table
        copilot model list --filter "name:ilike:%model%"
        copilot model list --limit 50
        copilot model list --properties "name,id,type"
    """
    from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError

    try:
        client = get_client()

        if prompts_only:
            # Filter to just GPT prompts
            result = client.get(
                f"msdyn_aimodels?$filter=_msdyn_templateid_value eq {GPT_POWER_PROMPT_TEMPLATE_ID}"
                f"&$orderby=msdyn_name&$top={limit}"
            )
        else:
            result = client.get(f"msdyn_aimodels?$orderby=msdyn_name&$top={limit}")

        models = result.get("value", [])

        # Apply filters using standard field:op:value syntax
        if filter:
            try:
                validate_filters(filter)
                models = apply_filters(models, filter)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        use_table = table or output == "table"
        if use_table:
            rows = []
            for m in models:
                statecode = m.get("statecode", 0)
                state = "Active" if statecode == 1 else "Inactive"
                is_managed = m.get("ismanaged", False)
                model_type = "System" if is_managed else "Custom"

                rows.append({
                    "name": m.get("msdyn_name", ""),
                    "type": model_type,
                    "state": state,
                    "id": m.get("msdyn_aimodelid", ""),
                })

            # Apply properties filter if specified
            if properties:
                property_list = [p.strip() for p in properties.split(",")]
                rows = [
                    {k: v for k, v in item.items() if k in property_list}
                    for item in rows
                ]
                print_table(rows, columns=property_list, headers=property_list)
            else:
                print_table(
                    rows,
                    columns=["name", "type", "state", "id"],
                    headers=["Name", "Type", "State", "ID"],
                )
        else:
            # Apply properties filter if specified for JSON output
            if properties:
                property_list = [p.strip() for p in properties.split(",")]
                # For JSON, format each model and filter properties
                rows = []
                for m in models:
                    statecode = m.get("statecode", 0)
                    state = "Active" if statecode == 1 else "Inactive"
                    is_managed = m.get("ismanaged", False)
                    model_type = "System" if is_managed else "Custom"
                    row = {
                        "name": m.get("msdyn_name", ""),
                        "type": model_type,
                        "state": state,
                        "id": m.get("msdyn_aimodelid", ""),
                    }
                    rows.append({k: v for k, v in row.items() if k in property_list})
                print_json(rows)
            else:
                print_json(models)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("get")
def model_get(
    model_id: str = typer.Argument(
        ...,
        help="The model's unique identifier (GUID)",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display output as a formatted table instead of JSON",
    ),
    output: Optional[str] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output format: json (default) or table",
    ),
):
    """
    Get details for a specific AI Builder model.

    Examples:
        copilot model get 12345678-1234-1234-1234-123456789abc
        copilot model get 12345678-1234-1234-1234-123456789abc --table
    """
    try:
        client = get_client()
        model = client.get(f"msdyn_aimodels({model_id})")

        use_table = table or output == "table"
        if use_table:
            statecode = model.get("statecode", 0)
            state = "Active" if statecode == 1 else "Inactive"
            is_managed = model.get("ismanaged", False)
            model_type = "System" if is_managed else "Custom"

            rows = [{
                "name": model.get("msdyn_name", ""),
                "type": model_type,
                "state": state,
                "id": model.get("msdyn_aimodelid", ""),
            }]
            print_table(
                rows,
                columns=["name", "type", "state", "id"],
                headers=["Name", "Type", "State", "ID"],
            )
        else:
            print_json(model)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("enable")
def model_enable(
    model_id: str = typer.Argument(
        ...,
        help="The model's unique identifier (GUID)",
    ),
):
    """
    Enable (activate) an AI Builder model.

    Sets the model's statecode to 1 (Active). This is required before
    publishing the model's configuration.

    Examples:
        copilot model enable 12345678-1234-1234-1234-123456789abc
    """
    try:
        client = get_client()

        # Get model info
        model = client.get(f"msdyn_aimodels({model_id})")
        model_name = model.get("msdyn_name", model_id)
        current_state = model.get("statecode", 0)

        if current_state == 1:
            typer.echo(f"Model '{model_name}' is already active")
            return

        typer.echo(f"Enabling model '{model_name}'...")

        # Activate by setting statecode=1 and statuscode=1
        client.patch(f"msdyn_aimodels({model_id})", {
            "statecode": 1,
            "statuscode": 1
        })

        print_success(f"Model '{model_name}' enabled successfully")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("disable")
def model_disable(
    model_id: str = typer.Argument(
        ...,
        help="The model's unique identifier (GUID)",
    ),
):
    """
    Disable (deactivate) an AI Builder model.

    Sets the model's statecode to 0 (Inactive).

    Examples:
        copilot model disable 12345678-1234-1234-1234-123456789abc
    """
    try:
        client = get_client()

        # Get model info
        model = client.get(f"msdyn_aimodels({model_id})")
        model_name = model.get("msdyn_name", model_id)
        current_state = model.get("statecode", 0)

        if current_state == 0:
            typer.echo(f"Model '{model_name}' is already inactive")
            return

        typer.echo(f"Disabling model '{model_name}'...")

        # Deactivate by setting statecode=0 and statuscode=0
        client.patch(f"msdyn_aimodels({model_id})", {
            "statecode": 0,
            "statuscode": 0
        })

        print_success(f"Model '{model_name}' disabled successfully")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)
