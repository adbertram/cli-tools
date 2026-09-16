"""Credentials commands - list, get, create, delete, and inspect n8n credentials on the server."""
import json
import sys
import typer
from typing import Optional, List

from ..n8n_api import get_n8n_api_client, N8nApiError
from cli_tools_shared.output import command, print_json, print_table, print_error, print_success, handle_error
from cli_tools_shared.filters import apply_filters, apply_properties_filter, apply_limit

app = typer.Typer(help="Manage n8n credentials on the server", no_args_is_help=True)

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
    ],
    "rename": [
        "api_key"
    ],
    "schema": [
        "api_key"
    ],
    "update": [
        "api_key"
    ]
}


@app.command("list")
@command
def credentials_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List all credentials on the n8n server.

    Example:
        n8n credentials list
        n8n credentials list --table
        n8n credentials list --filter "type:eq:brickowlApi"
        n8n credentials list --properties "id,name"
    """
    try:
        api = get_n8n_api_client()
        data = api.list_credentials()

        if filter:
            data = apply_filters(data, filter)

        data = apply_limit(data, limit)

        if properties:
            data = apply_properties_filter(data, properties)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(data, fields, fields)
            else:
                print_table(data, ["id", "name", "type"], ["ID", "Name", "Type"])
        else:
            print_json(data)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
@command
def credentials_get(
    credential_id: str = typer.Argument(..., help="Credential ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get details for a specific credential by ID.

    Example:
        n8n credentials get qe03iDk3T8FNbNTg
        n8n credentials get qe03iDk3T8FNbNTg --table
    """
    try:
        api = get_n8n_api_client()
        all_creds = api.list_credentials()

        match = None
        for cred in all_creds:
            if str(cred.get("id")) == credential_id:
                match = cred
                break

        if not match:
            print_error(f"Credential '{credential_id}' not found")
            raise typer.Exit(1)

        if table:
            rows = [{"field": k, "value": str(v)} for k, v in match.items()]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(match)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
@command
def credentials_create(
    cred_type: str = typer.Argument(..., help="Credential type name (e.g., brickowlApi)"),
    data: Optional[str] = typer.Argument(None, help="Credential data as JSON string; use --data-stdin for secrets"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Display name (defaults to credential type)"),
    data_stdin: bool = typer.Option(False, "--data-stdin", help="Read credential JSON from piped stdin instead of DATA"),
):
    """
    Create a credential on the n8n server.

    The credential type must match a type defined by an installed node.
    Use 'n8n credentials schema <type>' to see required fields.

    Example:
        $HOME/.local/bin/n8n credentials create brickowlApi --data-stdin --name "Brickowl Prod"

    Supply exactly one of DATA or --data-stdin. Pipe JSON into stdin; do not
    type secrets into an interactive terminal or put them in command arguments.
    """
    try:
        cred_data = _read_credential_data(data, data_stdin)

        api = get_n8n_api_client()

        # n8n natively supports multiple credentials of the same type
        # (e.g. multiple Slack bot tokens for different Slack apps,
        # multiple OAuth accounts). No uniqueness check here — the REST
        # API handles persistence and any real conflicts itself.

        # Validate required fields against schema before creating
        try:
            schema = api.get_credential_schema(cred_type)
            required_fields = schema.get("required", [])
            missing = [f for f in required_fields if not cred_data.get(f)]
            if missing:
                print_error(f"Required fields missing or empty: {', '.join(missing)}")
                from cli_tools_shared.output import print_info
                print_info(f"Run 'n8n credentials schema {cred_type}' to see all fields")
                raise typer.Exit(1)
        except N8nApiError:
            # Schema fetch failed (unknown type) — let the create call surface the error
            pass

        # Default display name from type (e.g., "brickowlApi" -> "Brickowl Api")
        display_name = name or _type_to_display_name(cred_type)

        result = api.create_credential(display_name, cred_type, cred_data)

        print_success(f"Created credential '{result.get('name')}' (id: {result.get('id')})")
        print_json(result)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update")
@command
def credentials_update(
    credential_id: str = typer.Argument(..., help="Credential ID to update"),
    data: Optional[str] = typer.Argument(None, help="Credential data as JSON string; use --data-stdin for secrets"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="New display name"),
    data_stdin: bool = typer.Option(False, "--data-stdin", help="Read credential JSON from piped stdin instead of DATA"),
):
    """
    Update an existing credential's data on the n8n server.

    The JSON payload replaces the credential's stored data, so include every
    field the credential type needs. Use 'n8n credentials schema <type>' to see
    the fields; the server enforces conditional requirements and rejects fields
    a type prohibits.

    Example:
        $HOME/.local/bin/n8n credentials update qe03iDk3T8FNbNTg --data-stdin --name "Brickowl Prod"

    Supply exactly one of DATA or --data-stdin. Pipe JSON into stdin; do not
    type secrets into an interactive terminal or put them in command arguments.
    """
    try:
        cred_data = _read_credential_data(data, data_stdin)

        api = get_n8n_api_client()

        # The credential type owns conditional required/prohibited fields, so the
        # server is the only validator here. Its rejection is surfaced verbatim.
        update_fields = {"data": cred_data}
        if name is not None:
            update_fields["name"] = name

        result = api.update_credential(credential_id, **update_fields)

        print_success(f"Updated credential '{result.get('name')}' (id: {result.get('id')})")
        print_json(result)

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
@command
def credentials_delete(
    credential_id: str = typer.Argument(..., help="Credential ID to delete"),
):
    """
    Delete a credential from the n8n server.

    Example:
        n8n credentials delete qe03iDk3T8FNbNTg
    """
    try:
        api = get_n8n_api_client()
        result = api.delete_credential(credential_id)

        print_success(f"Deleted credential '{result.get('name')}' (id: {result.get('id')})")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("rename")
@command
def credentials_rename(
    credential_id: str = typer.Argument(..., help="Credential ID to rename"),
    name: str = typer.Argument(..., help="New display name"),
):
    """
    Rename a credential on the n8n server.

    Example:
        n8n credentials rename tTBhVO3JjWS6PhOH "Example Slack Bot"
    """
    try:
        api = get_n8n_api_client()
        result = api.update_credential(credential_id, name=name)

        print_success(f"Renamed credential to '{result.get('name')}' (id: {result.get('id')})")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("schema")
@command
def credentials_schema(
    cred_type: str = typer.Argument(..., help="Credential type name (e.g., brickowlApi)"),
):
    """
    Show the JSON schema for a credential type (required fields and properties).

    Example:
        n8n credentials schema brickowlApi
        n8n credentials schema brickfreedomApi
    """
    try:
        api = get_n8n_api_client()
        schema = api.get_credential_schema(cred_type)
        print_json(schema)

    except Exception as e:
        raise typer.Exit(handle_error(e))


def _read_credential_data(data: Optional[str], data_stdin: bool) -> dict:
    """Resolve credential JSON from DATA or piped stdin into a dict.

    Secrets never reach argv or an interactive prompt: exactly one input source
    is accepted, and --data-stdin refuses a terminal before reading.
    """
    if (data is not None) == data_stdin:
        print_error("Provide exactly one of DATA or --data-stdin")
        raise typer.Exit(1)
    if data_stdin:
        if sys.stdin.isatty():
            print_error("--data-stdin requires piped or redirected input")
            raise typer.Exit(1)
        data = sys.stdin.read()

    try:
        cred_data = json.loads(data)
    except json.JSONDecodeError as e:
        print_error(f"Invalid JSON data at line {e.lineno}, column {e.colno}")
        raise typer.Exit(1)

    if not isinstance(cred_data, dict):
        print_error("Credential data must be a JSON object")
        raise typer.Exit(1)

    return cred_data


def _type_to_display_name(cred_type: str) -> str:
    """Convert credential type name to a display name.

    e.g., "brickowlApi" -> "Brickowl API", "brickfreedomApi" -> "Brickfreedom API"
    """
    import re
    # Split on camelCase boundaries
    parts = re.sub(r'([a-z])([A-Z])', r'\1 \2', cred_type).split()
    # Capitalize "api" -> "API", title-case the rest
    return " ".join(p.upper() if p.lower() == "api" else p.title() for p in parts)
