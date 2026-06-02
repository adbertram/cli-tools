"""Environment commands for managing Power Platform environments."""
import typer
from typing import Optional

from ..client import get_client
from ..config import get_config
from cli_tools_shared.output import print_json, print_table, print_error, print_success, handle_error, safe_symbol


app = typer.Typer(help="Manage Power Platform environments")

COMMAND_CREDENTIALS = {
    "create": [
        "custom"
    ],
    "current": [
        "custom"
    ],
    "delete": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ],
    "locations": [
        "custom"
    ],
    "rename": [
        "custom"
    ],
    "select": [
        "custom"
    ],
    "settings": [
        "custom"
    ],
    "update": [
        "custom"
    ]
}


def format_environment_for_display(env: dict) -> dict:
    """Format an environment for display."""
    props = env.get("properties", {})

    # Get environment type
    env_type = props.get("environmentSku", "")

    # Get state
    states = props.get("states", {})
    runtime_state = states.get("runtime", {}).get("id", "")

    # Get region
    azure_region = props.get("azureRegion", "")

    # Get created time
    created = props.get("createdTime", "")
    if created:
        created = created.split("T")[0]

    # Get linked environment (Dataverse)
    linked_env = props.get("linkedEnvironmentMetadata", {})
    dataverse_url = linked_env.get("instanceUrl", "")

    # Check if default
    is_default = props.get("isDefault", False)

    env_id = env.get("name", "")
    # Strip provider prefix if present
    if "/providers/" in env_id:
        env_id = env_id.rsplit("/", 1)[-1]

    return {
        "name": props.get("displayName", ""),
        "id": env_id,
        "type": env_type,
        "region": azure_region,
        "state": runtime_state,
        "default": is_default,
        "dataverse_url": dataverse_url,
        "created": created,
    }


@app.command("list")
def environment_list(
    filter: Optional[list[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., name:ilike:%dev%)",
    ),
    limit: int = typer.Option(
        100,
        "--limit",
        "-l",
        help="Maximum number of environments to return",
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
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of fields to include in output",
    ),
):
    """
    List all Power Platform environments accessible to you.

    Shows all environments in your tenant including production, sandbox,
    developer, and trial environments.

    Examples:
        copilot environment list
        copilot environment list --table
        copilot environment list --filter "name:ilike:%dev%" --table
        copilot environment list --limit 50
        copilot environment list --properties "name,id,type"
    """
    from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError

    try:
        client = get_client()
        environments = client.list_environments()

        if not environments:
            print_json([])
            return

        # Apply filters using standard field:op:value syntax
        if filter:
            try:
                validate_filters(filter)
                environments = apply_filters(environments, filter)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        if not environments:
            print_json([])
            return

        # Apply limit
        environments = environments[:limit]

        formatted = [format_environment_for_display(e) for e in environments]

        # Sort by default first, then name
        formatted.sort(key=lambda x: (not x["default"], x["name"].lower()))

        # Apply properties filter if specified
        if properties:
            property_list = [p.strip() for p in properties.split(",")]
            formatted = [
                {k: v for k, v in item.items() if k in property_list}
                for item in formatted
            ]

        use_table = table or output == "table"
        if use_table:
            if properties:
                property_list = [p.strip() for p in properties.split(",")]
                print_table(formatted, columns=property_list, headers=property_list)
            else:
                print_table(
                    formatted,
                    columns=["name", "type", "region", "state", "default", "id"],
                    headers=["Name", "Type", "Region", "State", "Default", "ID"],
                )
        else:
            print_json(formatted)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("get")
def environment_get(
    environment_id: str = typer.Argument(
        ...,
        help="The environment's unique identifier (e.g., Default-<tenant-id> or GUID)",
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
    Get details for a specific environment.

    Examples:
        copilot environment get Default-12345678-1234-1234-1234-123456789012
        copilot environment get 12345678-1234-1234-1234-123456789012
        copilot environment get abc123 --table
    """
    try:
        client = get_client()
        environment = client.get_environment(environment_id)

        formatted = format_environment_for_display(environment)

        use_table = table or output == "table"
        if use_table:
            print_table(
                [formatted],
                columns=["name", "type", "region", "state", "default", "id"],
                headers=["Name", "Type", "Region", "State", "Default", "ID"],
            )
        else:
            print_json(formatted)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("select")
def environment_select(
    environment_id: str = typer.Argument(
        ...,
        help="The environment's unique identifier (e.g., Default-<tenant-id> or GUID)",
    ),
):
    """
    Select an environment for CLI operations.

    Updates the CLI configuration with the selected environment's
    Dataverse URL and environment ID. All subsequent CLI commands
    will target this environment.

    Note: This does not change the Power Platform's default environment
    (which is a tenant-level setting in the admin center). It only
    changes which environment this CLI targets.

    Examples:
        copilot environment select 12345678-1234-1234-1234-123456789012
        copilot environment select Default-12345678-1234-1234-1234-123456789012
    """
    try:
        client = get_client()
        environment = client.get_environment(environment_id)

        # Extract Dataverse URL from environment
        props = environment.get("properties", {})
        linked_env = props.get("linkedEnvironmentMetadata", {})
        dataverse_url = linked_env.get("instanceUrl", "")
        display_name = props.get("displayName", environment_id)

        if not dataverse_url:
            print_error(
                f"Environment '{display_name}' does not have a linked Dataverse instance. "
                "Only environments with Dataverse can be used with this CLI."
            )
            raise typer.Exit(1)

        # Update the .env file
        config = get_config()
        env_file_path = config.env_file_path

        # Read existing .env content
        existing_vars = {}
        if env_file_path.exists():
            with open(env_file_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        existing_vars[key] = value

        # Update with new values
        existing_vars["DATAVERSE_URL"] = dataverse_url
        existing_vars["DATAVERSE_ENVIRONMENT_ID"] = environment.get("name", environment_id)

        # Write back to .env file
        with open(env_file_path, "w") as f:
            for key, value in existing_vars.items():
                f.write(f"{key}={value}\n")

        # Also update os.environ so the current process uses new values immediately
        import os
        os.environ["DATAVERSE_URL"] = dataverse_url
        os.environ["DATAVERSE_ENVIRONMENT_ID"] = environment.get("name", environment_id)

        # Reset the global config so it picks up new values
        from ..config import _reset_config
        _reset_config()

        print_success(f"Selected environment '{display_name}'")
        print_success(f"  DATAVERSE_URL={dataverse_url}")
        print_success(f"  DATAVERSE_ENVIRONMENT_ID={environment.get('name', environment_id)}")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("current")
def environment_current(
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
    Show the currently selected environment.

    Displays the environment that CLI commands will target. This is set
    via 'environment select' and stored in the local .env file.

    Examples:
        copilot environment current
        copilot environment current --table
    """
    try:
        config = get_config()
        env_file_path = config.env_file_path

        # Read from .env file
        dataverse_url = None
        environment_id = None

        if env_file_path.exists():
            with open(env_file_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        if key == "DATAVERSE_URL":
                            dataverse_url = value
                        elif key == "DATAVERSE_ENVIRONMENT_ID":
                            environment_id = value

        if not dataverse_url and not environment_id:
            print_error("No environment selected. Use 'copilot environment select <id>' to select one.")
            raise typer.Exit(1)

        # Try to get environment details from API for the name
        env_name = None
        try:
            if environment_id:
                client = get_client()
                environment = client.get_environment(environment_id)
                props = environment.get("properties", {})
                env_name = props.get("displayName", "")
        except Exception:
            # If we can't reach the API, just show what we have
            pass

        result = {
            "name": env_name or "(unknown)",
            "id": environment_id or "(not set)",
            "dataverse_url": dataverse_url or "(not set)",
        }

        use_table = table or output == "table"
        if use_table:
            print_table(
                [result],
                columns=["name", "id", "dataverse_url"],
                headers=["Name", "Environment ID", "Dataverse URL"],
            )
        else:
            print_json(result)

    except typer.Exit:
        raise
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("create")
def environment_create(
    name: str = typer.Option(
        ...,
        "--name",
        "-n",
        help="Display name for the environment",
    ),
    location: str = typer.Option(
        "unitedstates",
        "--location",
        "-l",
        help="Azure region (e.g., unitedstates, europe, asia). Use 'locations' command to list available.",
    ),
    env_type: str = typer.Option(
        "Sandbox",
        "--type",
        "-t",
        help="Environment type: Sandbox, Production, Developer, Trial, or Teams",
    ),
    description: str = typer.Option(
        "",
        "--description",
        "-d",
        help="Description for the environment",
    ),
    no_dataverse: bool = typer.Option(
        False,
        "--no-dataverse",
        help="Skip Dataverse provisioning (creates environment without a database)",
    ),
    language: int = typer.Option(
        1033,
        "--language",
        help="Dataverse base language code (default: 1033 for English)",
    ),
    currency: str = typer.Option(
        "USD",
        "--currency",
        help="Dataverse currency code (default: USD)",
    ),
):
    """
    Create a new Power Platform environment.

    Creates a new environment and optionally provisions Dataverse (database).
    By default, creates a Sandbox environment with Dataverse in the US region.

    Examples:
        copilot environment create --name "Testing"
        copilot environment create --name "Dev Environment" --type Developer
        copilot environment create --name "EU Sandbox" --location europe --type Sandbox
        copilot environment create --name "Empty Env" --no-dataverse

    Note:
        - Developer environments require a Power Apps Developer Plan license
        - Production environments may require capacity allocation in your tenant
        - Dataverse provisioning can take 1-3 minutes
    """
    try:
        client = get_client()

        typer.echo(f"Creating environment '{name}' ({env_type}) in {location}...")
        if not no_dataverse:
            typer.echo("This includes Dataverse provisioning and may take 1-3 minutes...")

        environment = client.create_environment(
            display_name=name,
            location=location,
            environment_sku=env_type,
            description=description,
            provision_dataverse=not no_dataverse,
            language_code=language,
            currency_code=currency,
        )

        # Check for Dataverse provisioning error
        dataverse_error = environment.pop("_dataverse_error", None)

        formatted = format_environment_for_display(environment)
        print_json(formatted)

        if dataverse_error:
            print_error(f"\nWarning: Environment created but Dataverse provisioning failed: {dataverse_error}")

        print_success(f"\nEnvironment '{name}' created successfully!")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("delete")
def environment_delete(
    environment_id: str = typer.Argument(
        ...,
        help="The environment's unique identifier",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Skip confirmation prompt",
    ),
    wait: bool = typer.Option(
        False,
        "--wait",
        "-w",
        help="Wait for deletion to complete (polls until environment is fully removed)",
    ),
    timeout: int = typer.Option(
        300,
        "--timeout",
        "-T",
        help="Maximum seconds to wait for deletion when using --wait (default: 300)",
    ),
):
    """
    Delete a Power Platform environment.

    WARNING: This permanently deletes the environment and ALL its data including
    apps, flows, agents, Dataverse tables, and records.

    Examples:
        copilot environment delete 12345678-1234-1234-1234-123456789012
        copilot environment delete abc123 --force
        copilot environment delete abc123 --force --wait
        copilot environment delete abc123 -f -w --timeout 600
    """
    import time

    try:
        client = get_client()

        # Get environment details for confirmation
        environment = client.get_environment(environment_id)
        props = environment.get("properties", {})
        display_name = props.get("displayName", environment_id)
        env_type = props.get("environmentSku", "Unknown")

        if not force:
            typer.echo(f"\n{safe_symbol('warning')}  You are about to DELETE environment '{display_name}' ({env_type})")
            typer.echo("This action is PERMANENT and cannot be undone.")
            typer.echo("All apps, flows, agents, and data will be lost.\n")

            confirm = typer.confirm("Are you sure you want to delete this environment?")
            if not confirm:
                typer.echo("Deletion cancelled.")
                raise typer.Exit(0)

        typer.echo(f"Deleting environment '{display_name}'...")
        client.delete_environment(environment_id)

        if wait:
            typer.echo("Waiting for deletion to complete...")
            start_time = time.time()
            poll_interval = 5  # seconds

            while True:
                elapsed = time.time() - start_time
                if elapsed > timeout:
                    print_error(f"Timeout after {timeout}s. Environment may still be deleting.")
                    raise typer.Exit(1)

                try:
                    env = client.get_environment(environment_id)
                    prov_state = env.get("properties", {}).get("provisioningState", "")
                    prov_details = env.get("properties", {}).get("provisioningDetails", {})
                    message = prov_details.get("message", prov_state)

                    # Count completed operations
                    operations = prov_details.get("operations", [])
                    completed = sum(1 for op in operations if op.get("code") == "Deleted")
                    total = len(operations)

                    if total > 0:
                        typer.echo(f"  [{int(elapsed)}s] {message} ({completed}/{total} resources)")
                    else:
                        typer.echo(f"  [{int(elapsed)}s] {message}")

                    time.sleep(poll_interval)

                except Exception as e:
                    # 404 means environment is fully deleted
                    if "404" in str(e) or "not found" in str(e).lower():
                        print_success(f"Environment '{display_name}' fully deleted.")
                        return
                    raise

        else:
            print_success(f"Environment '{display_name}' deletion initiated.")
            typer.echo("Use --wait to wait for full deletion, or check status with 'environment get'.")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("rename")
def environment_rename(
    environment_id: str = typer.Argument(
        ...,
        help="The environment's unique identifier (e.g., Default-<tenant-id> or GUID)",
    ),
    new_name: str = typer.Argument(
        ...,
        help="The new display name for the environment",
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
    Rename a Power Platform environment.

    Changes the display name of an environment. The environment ID remains unchanged.

    Examples:
        copilot environment rename 12345678-1234-1234-1234-123456789012 "My New Name"
        copilot environment rename 12345678-1234-1234-1234-123456789012 "Dev Environment" --table
    """
    try:
        client = get_client()

        # Get current name for confirmation message
        environment = client.get_environment(environment_id)
        props = environment.get("properties", {})
        old_name = props.get("displayName", environment_id)

        typer.echo(f"Renaming environment from '{old_name}' to '{new_name}'...")
        updated = client.rename_environment(environment_id, new_name)

        formatted = format_environment_for_display(updated)

        use_table = table or output == "table"
        if use_table:
            print_table(
                [formatted],
                columns=["name", "type", "region", "state", "default", "id"],
                headers=["Name", "Type", "Region", "State", "Default", "ID"],
            )
        else:
            print_json(formatted)

        print_success(f"Environment renamed from '{old_name}' to '{new_name}'")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("locations")
def environment_locations(
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display output as a formatted table instead of JSON",
    ),
):
    """
    List available locations for creating Power Platform environments.

    Shows all Azure regions where you can create environments.

    Examples:
        copilot environment locations
        copilot environment locations --table
    """
    try:
        client = get_client()
        locations = client.list_environment_locations()

        if not locations:
            typer.echo("No locations found.")
            return

        # Format for display
        formatted = []
        for loc in locations:
            formatted.append({
                "name": loc.get("name", ""),
                "displayName": loc.get("properties", {}).get("displayName", loc.get("name", "")),
            })

        # Sort by name
        formatted.sort(key=lambda x: x["name"])

        if table:
            print_table(
                formatted,
                columns=["name", "displayName"],
                headers=["Name", "Display Name"],
            )
        else:
            print_json(formatted)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("settings")
def environment_settings(
    environment_id: str = typer.Argument(
        ...,
        help="The environment's unique identifier (GUID)",
    ),
    select: Optional[str] = typer.Option(
        None,
        "--select",
        "-s",
        help="Comma-separated list of setting names to retrieve (default: all)",
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
    List environment management settings.

    Retrieves current settings for a Power Platform environment via the
    Environment Management Settings API.

    Examples:
        copilot environment settings 12345678-1234-1234-1234-123456789abc
        copilot environment settings 12345678-1234-1234-1234-123456789abc --table
        copilot environment settings abc123 --select "copilotStudio_ConnectedAgents,copilotStudio_CodeInterpreter"
    """
    try:
        client = get_client()

        select_list = [s.strip() for s in select.split(",")] if select else None
        result = client.get_environment_settings(environment_id, select=select_list)

        # Extract the settings from the response envelope
        settings_list = result.get("objectResult", [])
        if not settings_list:
            typer.echo("No settings found for this environment.")
            return

        # The API returns a list but typically has one object with all settings
        settings = settings_list[0] if settings_list else {}

        # Remove metadata fields for cleaner display
        display_settings = {k: v for k, v in settings.items() if k not in ("id", "tenantId")}

        use_table = table or output == "table"
        if use_table:
            rows = [{"setting": k, "value": str(v)} for k, v in sorted(display_settings.items())]
            print_table(
                rows,
                columns=["setting", "value"],
                headers=["Setting", "Value"],
            )
        else:
            print_json(display_settings)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


def _parse_setting_value(value_str: str):
    """Parse a setting value string into the appropriate Python type."""
    lower = value_str.lower()
    if lower == "true":
        return True
    if lower == "false":
        return False
    try:
        return int(value_str)
    except ValueError:
        pass
    try:
        return float(value_str)
    except ValueError:
        pass
    return value_str


@app.command("update")
def environment_update(
    environment_id: str = typer.Argument(
        ...,
        help="The environment's unique identifier (GUID)",
    ),
    setting: list[str] = typer.Option(
        ...,
        "--setting",
        "-s",
        help="Setting to update as key=value (repeatable). Values are auto-typed: true/false -> bool, digits -> int.",
    ),
):
    """
    Update environment management settings.

    Updates one or more settings for a Power Platform environment via the
    Environment Management Settings API (PATCH).

    Use 'copilot environment settings <id>' to discover available setting names.

    Examples:
        copilot environment update abc123 --setting copilotStudio_ConnectedAgents=true
        copilot environment update abc123 -s copilotStudio_CodeInterpreter=true -s copilotStudio_ConnectedAgents=false
        copilot environment update abc123 --setting enableIpBasedStorageAccessSignatureRule=true
    """
    try:
        client = get_client()

        # Parse key=value pairs
        settings_dict = {}
        for s in setting:
            if "=" not in s:
                print_error(f"Invalid setting format: '{s}'. Expected key=value.")
                raise typer.Exit(1)
            key, value = s.split("=", 1)
            settings_dict[key.strip()] = _parse_setting_value(value.strip())

        typer.echo(f"Updating {len(settings_dict)} setting(s) for environment {environment_id}...")
        for k, v in settings_dict.items():
            typer.echo(f"  {k} = {v}")

        result = client.update_environment_settings(environment_id, settings_dict)

        # Show the updated settings
        settings_list = result.get("objectResult", [])
        if settings_list:
            updated = settings_list[0]
            # Show only the settings that were changed
            display = {k: updated.get(k, "?") for k in settings_dict}
            print_json(display)

        print_success("Settings updated successfully.")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)
