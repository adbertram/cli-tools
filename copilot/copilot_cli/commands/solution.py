"""Solution commands for Copilot CLI."""
import typer
from typing import Optional

from ..client import get_client, get_client_for_environment
from cli_tools_shared.output import print_json, print_table, print_success, handle_error

app = typer.Typer(help="Manage solutions and solution components")

COMMAND_CREDENTIALS = {
    "agent": [
        "custom"
    ],
    "component": [
        "custom"
    ],
    "connection-reference": [
        "custom"
    ],
    "create": [
        "custom"
    ],
    "create-settings": [
        "custom"
    ],
    "custom-connector": [
        "custom"
    ],
    "delete": [
        "custom"
    ],
    "export": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "import": [
        "custom"
    ],
    "list": [
        "custom"
    ],
    "publisher": [
        "custom"
    ],
    "remove": [
        "custom"
    ],
    "update": [
        "custom"
    ]
}

# Subcommand for agent operations within solutions
agent_app = typer.Typer(help="Manage agents in solutions")
app.add_typer(agent_app, name="agent")

# Subcommand for connection-reference operations within solutions
connection_reference_app = typer.Typer(help="Manage connection references in solutions")
app.add_typer(connection_reference_app, name="connection-reference")

# Subcommand for custom-connector operations within solutions
custom_connector_app = typer.Typer(help="Manage custom connectors in solutions")
app.add_typer(custom_connector_app, name="custom-connector")

# Subcommand for component operations within solutions
component_app = typer.Typer(help="List and inspect solution components")
app.add_typer(component_app, name="component")


def format_solution_for_display(solution: dict, preferred_solution_id: str = None) -> dict:
    """Format a solution record for display."""
    solution_id = solution.get("solutionid", "")
    is_preferred = solution_id == preferred_solution_id if preferred_solution_id else False
    return {
        "friendlyname": solution.get("friendlyname", ""),
        "uniquename": solution.get("uniquename", ""),
        "solutionid": solution_id,
        "version": solution.get("version", ""),
        "ismanaged": "Yes" if solution.get("ismanaged") else "No",
        "preferred": "Yes" if is_preferred else "",
    }


@app.command("list")
def list_solutions(
    filter: Optional[list[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., name:ilike:%solution%)",
    ),
    limit: int = typer.Option(
        100,
        "--limit",
        "-l",
        help="Maximum number of solutions to return",
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
    unmanaged: bool = typer.Option(
        False,
        "--unmanaged",
        "-u",
        help="Only show unmanaged solutions (solutions you can modify)",
    ),
    include_invisible: bool = typer.Option(
        False,
        "--include-invisible",
        help="Include solutions not visible in the Power Apps UI",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of fields to include in output",
    ),
):
    """
    List solutions in the environment.

    By default, only solutions visible in the Power Apps UI are shown.
    The "Preferred" column indicates the user's default solution for new components.

    Examples:
        copilot solution list
        copilot solution list --table
        copilot solution list --unmanaged
        copilot solution list --include-invisible
        copilot solution list --filter "name:ilike:%solution%"
        copilot solution list --limit 50
    """
    from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError

    try:
        client = get_client()

        # Get the user's preferred solution
        preferred_solution_id = client.get_user_preferred_solution()

        # Get solutions
        solutions = client.list_solutions(
            unmanaged_only=unmanaged,
            include_invisible=include_invisible,
        )

        # Apply filters using standard field:op:value syntax
        if filter:
            try:
                validate_filters(filter)
                solutions = apply_filters(solutions, filter)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        # If no preferred solution is set, default is "Common Data Services Default Solution"
        if not preferred_solution_id:
            for s in solutions:
                if s.get("uniquename") == "Cr61726" or "Common Data Services Default" in s.get("friendlyname", ""):
                    preferred_solution_id = s.get("solutionid")
                    break

        # Apply limit
        solutions = solutions[:limit]

        formatted = [format_solution_for_display(s, preferred_solution_id) for s in solutions]

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
                # Use properties list for table columns
                property_list = [p.strip() for p in properties.split(",")]
                print_table(formatted, columns=property_list, headers=property_list)
            else:
                print_table(
                    formatted,
                    columns=["friendlyname", "uniquename", "version", "ismanaged", "preferred"],
                    headers=["Display Name", "Name", "Version", "Managed", "Preferred"],
                )
        else:
            print_json(formatted)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("get")
def get_solution(
    solution: str = typer.Argument(
        ...,
        help="The solution's unique name or GUID",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display output as a formatted table instead of JSON",
    ),
):
    """
    Get details for a specific solution.

    Examples:
        copilot solution get MySolution
        copilot solution get 12345678-1234-1234-1234-123456789abc
        copilot solution get MySolution --table
    """
    try:
        client = get_client()
        result = client.get_solution(solution)

        if table:
            formatted = format_solution_for_display(result)
            print_table(
                [formatted],
                columns=["friendlyname", "uniquename", "version", "ismanaged"],
                headers=["Display Name", "Name", "Version", "Managed"],
            )
        else:
            print_json(result)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("update")
def update_solution(
    solution: str = typer.Argument(
        ...,
        help="The solution's unique name or GUID",
    ),
    preferred: Optional[bool] = typer.Option(
        None,
        "--preferred/--no-preferred",
        help="Set or unset this solution as the preferred solution for the current user",
    ),
):
    """
    Update solution settings.

    The --preferred flag sets this solution as the default location for new components.

    Examples:
        copilot solution update MySolution --preferred
        copilot solution update MySolution --no-preferred
    """
    try:
        client = get_client()

        # Get the solution to validate it exists
        solution_details = client.get_solution(solution)
        solution_id = solution_details.get("solutionid")
        solution_name = solution_details.get("friendlyname", solution)

        if preferred is not None:
            if solution_details.get("ismanaged"):
                typer.echo("Error: Cannot set a managed solution as preferred.", err=True)
                raise typer.Exit(1)

            if preferred:
                client.set_user_preferred_solution(solution_id)
                print_success(f"'{solution_name}' is now your preferred solution.")
            else:
                # Check if this is currently the preferred solution
                current_preferred = client.get_user_preferred_solution()
                if current_preferred == solution_id:
                    client.clear_user_preferred_solution()
                    print_success(f"'{solution_name}' is no longer your preferred solution.")
                else:
                    typer.echo(f"'{solution_name}' is not currently your preferred solution.")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("create")
def create_solution(
    name: str = typer.Option(
        ...,
        "--name",
        "-n",
        help="The display name for the solution",
    ),
    unique_name: str = typer.Option(
        ...,
        "--unique-name",
        "-u",
        help="The unique name for the solution (no spaces, used for identification)",
    ),
    publisher: str = typer.Option(
        ...,
        "--publisher",
        "-p",
        help="The publisher's unique name or GUID",
    ),
    version: str = typer.Option(
        "1.0.0.0",
        "--version",
        "-v",
        help="The solution version (format: major.minor.build.revision)",
    ),
    description: Optional[str] = typer.Option(
        None,
        "--description",
        "-d",
        help="Optional description for the solution",
    ),
):
    """
    Create a new unmanaged solution.

    A publisher must exist before creating a solution. Use 'copilot solution publisher list'
    to see available publishers.

    Examples:
        copilot solution create --name "My Solution" --unique-name MySolution --publisher MyPublisher
        copilot solution create -n "My Solution" -u MySolution -p MyPublisher -v 1.0.0.0
        copilot solution create -n "My Solution" -u MySolution -p MyPublisher -d "Description here"
    """
    try:
        client = get_client()

        client.create_solution(
            unique_name=unique_name,
            friendly_name=name,
            publisher_id=publisher,
            version=version,
            description=description,
        )

        print_success(f"Solution '{name}' created successfully.")

        # Fetch the created solution to display its details
        created_solution = client.get_solution(unique_name)
        print_json(format_solution_for_display(created_solution))

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("delete")
@app.command("remove")
def delete_solution(
    solution: str = typer.Argument(
        ...,
        help="The solution's unique name or GUID",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Skip confirmation prompt",
    ),
):
    """
    Delete an unmanaged solution.

    This deletes the solution container but does NOT delete the components within it.
    Components will remain in the environment.

    Examples:
        copilot solution delete MySolution
        copilot solution delete MySolution --force
    """
    try:
        client = get_client()

        # Get solution details for display
        solution_details = client.get_solution(solution)
        solution_name = solution_details.get("friendlyname", solution)

        if solution_details.get("ismanaged"):
            typer.echo("Error: Cannot delete managed solutions.", err=True)
            raise typer.Exit(1)

        if not force:
            confirm = typer.confirm(
                f"Delete solution '{solution_name}'? Components will remain in the environment."
            )
            if not confirm:
                typer.echo("Aborted.")
                raise typer.Exit(0)

        client.delete_solution(solution)
        print_success(f"Solution '{solution_name}' deleted.")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@agent_app.command("add")
def add_agent_to_solution(
    solution: str = typer.Option(
        ...,
        "--solution",
        "-s",
        help="The solution's unique name",
    ),
    agent_id: str = typer.Option(
        ...,
        "--agent",
        "-a",
        help="The agent's unique identifier (GUID)",
    ),
    include_connection: bool = typer.Option(
        True,
        "--include-connection/--no-connection",
        help="Also add the agent's connection reference to the solution (default: True)",
    ),
    add_required: bool = typer.Option(
        True,
        "--add-required/--no-required",
        help="Add required dependent components (default: True)",
    ),
):
    """
    Add a Copilot agent (and optionally its connection reference) to a solution.

    This command adds the specified agent to an unmanaged solution. By default,
    it also adds the agent's connection reference for knowledge sources.

    Examples:
        copilot solution agent add --solution MySolution --agent <agent-id>
        copilot solution agent add -s MySolution -a <agent-id> --no-connection
        copilot solution agent add -s MySolution -a <agent-id> --no-required
    """
    try:
        client = get_client()

        # Get agent name for display
        bot = client.get_bot(agent_id)
        agent_name = bot.get("name", agent_id)

        # Add the agent to the solution
        client.add_bot_to_solution(
            solution_unique_name=solution,
            bot_id=agent_id,
            add_required_components=add_required,
        )
        print_success(f"Agent '{agent_name}' added to solution '{solution}'.")

        # Optionally add connection reference
        if include_connection:
            provider_ref_id = bot.get("_providerconnectionreferenceid_value")
            if provider_ref_id:
                try:
                    client.add_connection_reference_to_solution(
                        solution_unique_name=solution,
                        connection_reference_id=provider_ref_id,
                        add_required_components=False,
                    )
                    print_success(f"Connection reference added to solution '{solution}'.")
                except Exception as conn_error:
                    # Connection reference might already be in the solution
                    error_str = str(conn_error).lower()
                    if "already exists" in error_str or "duplicate" in error_str:
                        typer.echo("Connection reference already exists in solution.", err=True)
                    else:
                        typer.echo(f"Warning: Could not add connection reference: {conn_error}", err=True)
            else:
                typer.echo("Note: Agent has no connection reference configured.", err=True)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@agent_app.command("remove")
def remove_agent_from_solution(
    solution: str = typer.Option(
        ...,
        "--solution",
        "-s",
        help="The solution's unique name",
    ),
    agent_id: str = typer.Option(
        ...,
        "--agent",
        "-a",
        help="The agent's unique identifier (GUID)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-F",
        help="Skip confirmation prompt",
    ),
):
    """
    Remove a Copilot agent from a solution.

    This removes the agent from the solution but does NOT delete the agent itself.

    Examples:
        copilot solution agent remove --solution MySolution --agent <agent-id>
        copilot solution agent remove -s MySolution -a <agent-id> --force
    """
    try:
        client = get_client()

        # Get agent name for display
        bot = client.get_bot(agent_id)
        agent_name = bot.get("name", agent_id)

        if not force:
            confirm = typer.confirm(
                f"Remove agent '{agent_name}' from solution '{solution}'?"
            )
            if not confirm:
                typer.echo("Aborted.")
                raise typer.Exit(0)

        client.remove_bot_from_solution(
            solution_unique_name=solution,
            bot_id=agent_id,
        )
        print_success(f"Agent '{agent_name}' removed from solution '{solution}'.")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@connection_reference_app.command("add")
def add_connection_reference_to_solution(
    solution: str = typer.Option(
        ...,
        "--solution",
        "-s",
        help="The solution's unique name",
    ),
    connection_id: str = typer.Option(
        ...,
        "--connection-reference",
        "-c",
        help="The connection reference's unique identifier (GUID)",
    ),
):
    """
    Add a connection reference to a solution.

    Examples:
        copilot solution connection-reference add --solution MySolution --connection-reference <id>
        copilot solution connection-reference add -s MySolution -c <connection-reference-id>
    """
    try:
        client = get_client()

        client.add_connection_reference_to_solution(
            solution_unique_name=solution,
            connection_reference_id=connection_id,
            add_required_components=False,
        )
        print_success(f"Connection reference added to solution '{solution}'.")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@connection_reference_app.command("remove")
def remove_connection_reference_from_solution(
    solution: str = typer.Option(
        ...,
        "--solution",
        "-s",
        help="The solution's unique name",
    ),
    connection_id: str = typer.Option(
        ...,
        "--connection-reference",
        "-c",
        help="The connection reference's unique identifier (GUID)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-F",
        help="Skip confirmation prompt",
    ),
):
    """
    Remove a connection reference from a solution.

    This removes the connection reference from the solution but does NOT delete it.

    Examples:
        copilot solution connection-reference remove --solution MySolution --connection-reference <id>
        copilot solution connection-reference remove -s MySolution -c <id> --force
    """
    try:
        client = get_client()

        if not force:
            confirm = typer.confirm(
                f"Remove connection reference from solution '{solution}'?"
            )
            if not confirm:
                typer.echo("Aborted.")
                raise typer.Exit(0)

        client.remove_connection_reference_from_solution(
            solution_unique_name=solution,
            connection_reference_id=connection_id,
        )
        print_success(f"Connection reference removed from solution '{solution}'.")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@custom_connector_app.command("add")
def add_custom_connector_to_solution(
    solution: Optional[str] = typer.Option(
        None,
        "--solution",
        "-s",
        help="The solution's unique name",
    ),
    solution_id: Optional[str] = typer.Option(
        None,
        "--solution-id",
        help="The solution's ID (GUID)",
    ),
    connector_id: str = typer.Option(
        ...,
        "--connector",
        "-c",
        help="The custom connector's Dataverse entity ID (GUID)",
    ),
    skip_validation: bool = typer.Option(
        False,
        "--skip-validation",
        help="Skip validation for solution composition rules",
    ),
):
    """
    Add a custom connector to a solution.

    IMPORTANT: Custom connectors cannot be in the same solution as cloud flows
    and connection references that use them. You need separate solutions:
    - Solution 1: Custom connector(s)
    - Solution 2: Cloud flows + connection references

    The connector solution must be imported to the target environment before
    importing the flows solution.

    To find the connector's Dataverse entity ID, use:
        copilot custom-connector list --raw

    Look for the 'connectorid' field in the '_dataverse' section.

    Examples:
        copilot solution custom-connector add --solution MyConnectorsSolution --connector <connector-id>
        copilot solution custom-connector add --solution-id <solution-guid> --connector <connector-id>
        copilot solution custom-connector add -s MyConnectorsSolution -c <connector-id>
        copilot solution custom-connector add -s MySolution -c <id> --skip-validation
    """
    try:
        # Validate that exactly one of --solution or --solution-id is provided
        if solution and solution_id:
            typer.echo("Error: Specify either --solution or --solution-id, not both.", err=True)
            raise typer.Exit(1)
        if not solution and not solution_id:
            typer.echo("Error: Either --solution or --solution-id is required.", err=True)
            raise typer.Exit(1)

        client = get_client()

        # Resolve to solution unique name
        solution_identifier = solution or solution_id
        solution_details = client.get_solution(solution_identifier)
        solution_unique_name = solution_details.get("uniquename")
        solution_display_name = solution_details.get("friendlyname", solution_unique_name)

        # Validate solution composition unless skipped
        if not skip_validation:
            is_valid, error_msg = client.validate_solution_for_custom_connector(solution_unique_name)
            if not is_valid:
                typer.echo(f"Error: {error_msg}", err=True)
                raise typer.Exit(1)

        client.add_custom_connector_to_solution(
            solution_unique_name=solution_unique_name,
            connector_id=connector_id,
            add_required_components=False,
        )
        print_success(f"Custom connector added to solution '{solution_display_name}'.")

        typer.echo()
        typer.echo("Note: Custom connectors must be in a separate solution from")
        typer.echo("cloud flows and connection references. Import this solution")
        typer.echo("to target environments before importing flows that use it.")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@custom_connector_app.command("remove")
def remove_custom_connector_from_solution(
    solution: Optional[str] = typer.Option(
        None,
        "--solution",
        "-s",
        help="The solution's unique name",
    ),
    solution_id: Optional[str] = typer.Option(
        None,
        "--solution-id",
        help="The solution's ID (GUID)",
    ),
    connector_id: str = typer.Option(
        ...,
        "--connector",
        "-c",
        help="The custom connector's Dataverse entity ID (GUID)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-F",
        help="Skip confirmation prompt",
    ),
):
    """
    Remove a custom connector from a solution.

    This removes the connector from the solution but does NOT delete the connector itself.

    Examples:
        copilot solution custom-connector remove --solution MySolution --connector <connector-id>
        copilot solution custom-connector remove --solution-id <solution-guid> --connector <connector-id>
        copilot solution custom-connector remove -s MySolution -c <connector-id> --force
    """
    try:
        # Validate that exactly one of --solution or --solution-id is provided
        if solution and solution_id:
            typer.echo("Error: Specify either --solution or --solution-id, not both.", err=True)
            raise typer.Exit(1)
        if not solution and not solution_id:
            typer.echo("Error: Either --solution or --solution-id is required.", err=True)
            raise typer.Exit(1)

        client = get_client()

        # Resolve to solution unique name
        solution_identifier = solution or solution_id
        solution_details = client.get_solution(solution_identifier)
        solution_unique_name = solution_details.get("uniquename")
        solution_display_name = solution_details.get("friendlyname", solution_unique_name)

        if not force:
            confirm = typer.confirm(
                f"Remove custom connector from solution '{solution_display_name}'?"
            )
            if not confirm:
                typer.echo("Aborted.")
                raise typer.Exit(0)

        client.remove_custom_connector_from_solution(
            solution_unique_name=solution_unique_name,
            connector_id=connector_id,
        )
        print_success(f"Custom connector removed from solution '{solution_display_name}'.")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


# Publisher commands
publisher_app = typer.Typer(help="Manage publishers")


def format_publisher_for_display(publisher: dict) -> dict:
    """Format a publisher record for display."""
    return {
        "friendlyname": publisher.get("friendlyname", ""),
        "uniquename": publisher.get("uniquename", ""),
        "publisherid": publisher.get("publisherid", ""),
        "customizationprefix": publisher.get("customizationprefix", ""),
    }


@publisher_app.command("list")
def list_publishers(
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display output as a formatted table instead of JSON",
    ),
    limit: int = typer.Option(
        100,
        "--limit",
        "-l",
        help="Maximum number of results to return",
    ),
    filter: Optional[list[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter results using field:op:value syntax",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of fields to include in output",
    ),
):
    """
    List publishers in the environment.

    Publishers are required when creating solutions. Each solution must be linked
    to a publisher.

    Examples:
        copilot solution publisher list
        copilot solution publisher list --table
    """
    from cli_tools_shared.output import print_error

    try:
        client = get_client()
        publishers = client.list_publishers()

        if not publishers:
            typer.echo("No publishers found.")
            return

        formatted = [format_publisher_for_display(p) for p in publishers]

        # Apply filters
        if filter:
            from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError
            try:
                validate_filters(filter)
                formatted = apply_filters(formatted, filter)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        # Apply limit
        formatted = formatted[:limit]

        # Apply properties filter
        if properties:
            property_list = [p.strip() for p in properties.split(",")]
            formatted = [{k: v for k, v in item.items() if k in property_list} for item in formatted]

        if table:
            print_table(
                formatted,
                columns=["friendlyname", "uniquename", "customizationprefix"],
                headers=["Name", "Unique Name", "Prefix"],
            )
        else:
            print_json(formatted)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@publisher_app.command("get")
def get_publisher(
    publisher: str = typer.Argument(
        ...,
        help="The publisher's unique name or GUID",
    ),
):
    """
    Get details for a specific publisher.

    Examples:
        copilot solution publisher get MyPublisher
        copilot solution publisher get 12345678-1234-1234-1234-123456789abc
    """
    try:
        client = get_client()
        result = client.get_publisher(publisher)
        print_json(result)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@publisher_app.command("create")
def create_publisher(
    name: str = typer.Option(
        ...,
        "--name",
        "-n",
        help="The display name for the publisher",
    ),
    unique_name: str = typer.Option(
        ...,
        "--unique-name",
        "-u",
        help="The unique name for the publisher (no spaces)",
    ),
    prefix: str = typer.Option(
        ...,
        "--prefix",
        "-x",
        help="Customization prefix (2-8 lowercase letters, used for solution components)",
    ),
    option_value_prefix: int = typer.Option(
        ...,
        "--option-prefix",
        "-o",
        help="Option value prefix (10000-99999, used for choice option values)",
    ),
    description: Optional[str] = typer.Option(
        None,
        "--description",
        "-d",
        help="Optional description for the publisher",
    ),
):
    """
    Create a new publisher.

    Publishers are required for creating solutions. The customization prefix is used
    to prefix schema names of solution components.

    Examples:
        copilot solution publisher create --name "My Publisher" --unique-name MyPublisher --prefix mypub --option-prefix 10000
        copilot solution publisher create -n "My Publisher" -u MyPublisher -x mypub -o 10000 -d "My description"
    """
    try:
        client = get_client()

        client.create_publisher(
            unique_name=unique_name,
            friendly_name=name,
            customization_prefix=prefix,
            customization_option_value_prefix=option_value_prefix,
            description=description,
        )

        print_success(f"Publisher '{name}' created successfully.")

        # Fetch the created publisher to display its details
        created_publisher = client.get_publisher(unique_name)
        print_json(format_publisher_for_display(created_publisher))

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@publisher_app.command("delete")
@publisher_app.command("remove")
def delete_publisher(
    publisher: str = typer.Argument(
        ...,
        help="The publisher's unique name or GUID",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Skip confirmation prompt",
    ),
):
    """
    Delete a publisher.

    Publishers cannot be deleted if they have solutions associated with them.
    You must delete all solutions using the publisher first.

    Examples:
        copilot solution publisher delete MyPublisher
        copilot solution publisher delete MyPublisher --force
    """
    try:
        client = get_client()

        # Get publisher details for display
        publisher_details = client.get_publisher(publisher)
        publisher_name = publisher_details.get("friendlyname", publisher)

        if not force:
            confirm = typer.confirm(
                f"Delete publisher '{publisher_name}'? This cannot be undone."
            )
            if not confirm:
                typer.echo("Aborted.")
                raise typer.Exit(0)

        client.delete_publisher(publisher)
        print_success(f"Publisher '{publisher_name}' deleted.")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


# Connection reference listing commands
connection_reference_app = typer.Typer(help="Manage connection references")


@connection_reference_app.command("list")
def list_connection_references(
    agent_id: Optional[str] = typer.Option(
        None,
        "--agent",
        "-a",
        help="Filter to show only the connection reference for a specific agent",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display output as a formatted table instead of JSON",
    ),
    limit: int = typer.Option(
        100,
        "--limit",
        "-l",
        help="Maximum number of results to return",
    ),
    filter: Optional[list[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter results using field:op:value syntax",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of fields to include in output",
    ),
):
    """
    List connection references in the environment.

    Examples:
        copilot solution connection-reference list
        copilot solution connection-reference list --table
        copilot solution connection-reference list --agent <agent-id>
    """
    from cli_tools_shared.output import print_error

    try:
        client = get_client()

        if agent_id:
            # Get the specific agent's provider connection reference
            conn_ref = client.get_bot_connection_reference(agent_id)
            connections = [conn_ref] if conn_ref else []
        else:
            # Get all connection references
            connections = client.list_connection_references()

        if not connections:
            typer.echo("No connection references found.")
            return

        formatted = [
            {
                "name": c.get("connectionreferencedisplayname", ""),
                "id": c.get("connectionreferenceid", ""),
                "connector": c.get("connectorid", ""),
                "status": c.get("statecode@OData.Community.Display.V1.FormattedValue", c.get("statecode", "")),
            }
            for c in connections
        ]

        # Apply filters
        if filter:
            from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError
            try:
                validate_filters(filter)
                formatted = apply_filters(formatted, filter)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        # Apply limit
        formatted = formatted[:limit]

        # Apply properties filter
        if properties:
            property_list = [p.strip() for p in properties.split(",")]
            formatted = [{k: v for k, v in item.items() if k in property_list} for item in formatted]

        if table:
            print_table(
                formatted,
                columns=["name", "id", "connector", "status"],
                headers=["Name", "ID", "Connector", "Status"],
            )
        else:
            print_json(formatted)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@connection_reference_app.command("get")
def get_connection_reference(
    connref_id: str = typer.Argument(..., help="Connection reference ID (GUID)"),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display output as a formatted table",
    ),
):
    """
    Get details for a specific connection reference.

    Returns the full metadata for a connection reference by its ID.

    Examples:
        copilot solution connection-reference get 550e8400-e29b-41d4-a716-446655440000
        copilot solution connection-reference get 550e8400-e29b-41d4-a716-446655440000 --table
    """
    try:
        client = get_client()
        result = client.get_connection_reference(connref_id)

        formatted = {
            "name": result.get("connectionreferencedisplayname", ""),
            "id": result.get("connectionreferenceid", ""),
            "connector": result.get("connectorid", ""),
            "status": result.get("statecode@OData.Community.Display.V1.FormattedValue", result.get("statecode", "")),
        }

        if table:
            print_table(
                [formatted],
                columns=["name", "id", "connector", "status"],
                headers=["Name", "ID", "Connector", "Status"],
            )
        else:
            print_json(result)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


# =========================================================================
# Solution Export/Import Commands
# =========================================================================

@app.command("export")
def export_solution(
    solution: str = typer.Argument(
        ...,
        help="The solution's unique name (not the display name)",
    ),
    output: str = typer.Option(
        ...,
        "--output",
        "-o",
        help="Output file path for the exported solution zip",
    ),
    managed: bool = typer.Option(
        False,
        "--managed",
        "-m",
        help="Export as managed solution (default: unmanaged)",
    ),
    timeout: int = typer.Option(
        300,
        "--timeout",
        "-T",
        help="Maximum time to wait for export in seconds (default: 300)",
    ),
):
    """
    Export a solution as a zip file.

    Exports the solution asynchronously and saves it to the specified output path.
    Use the solution's unique name (schema name), not the display name.

    Examples:
        copilot solution export MySolution -o MySolution.zip
        copilot solution export MySolution --managed -o MySolution_managed.zip
        copilot solution export MySolution -o export.zip --timeout 600
    """
    try:
        client = get_client()

        # Verify solution exists and get its details
        solution_details = client.get_solution(solution)
        solution_name = solution_details.get("uniquename")
        display_name = solution_details.get("friendlyname", solution_name)

        if not solution_name:
            typer.echo(f"Error: Could not determine unique name for solution '{solution}'", err=True)
            raise typer.Exit(1)

        typer.echo(f"Exporting solution '{display_name}' ({solution_name})...")
        if managed:
            typer.echo("Export type: Managed")
        else:
            typer.echo("Export type: Unmanaged")

        # Export the solution
        solution_bytes = client.export_solution_async(
            solution_name=solution_name,
            managed=managed,
            timeout=float(timeout),
        )

        # Write to file
        with open(output, "wb") as f:
            f.write(solution_bytes)

        file_size = len(solution_bytes)
        if file_size >= 1024 * 1024:
            size_str = f"{file_size / (1024 * 1024):.2f} MB"
        elif file_size >= 1024:
            size_str = f"{file_size / 1024:.2f} KB"
        else:
            size_str = f"{file_size} bytes"

        print_success(f"Solution exported to '{output}' ({size_str})")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("import")
def import_solution(
    file: str = typer.Argument(
        ...,
        help="Path to the solution zip file to import",
    ),
    settings_file: Optional[str] = typer.Option(
        None,
        "--settings",
        "-s",
        help="Path to deployment settings JSON file for connection mappings",
    ),
    overwrite: bool = typer.Option(
        False,
        "--overwrite",
        help="Overwrite unmanaged customizations if they exist",
    ),
    publish_workflows: bool = typer.Option(
        False,
        "--publish-workflows",
        help="Publish workflows after import",
    ),
    stage: bool = typer.Option(
        False,
        "--stage",
        help="Stage and validate the solution before importing",
    ),
    upgrade: bool = typer.Option(
        False,
        "--upgrade",
        help="Import as holding solution and apply upgrade",
    ),
    timeout: int = typer.Option(
        600,
        "--timeout",
        "-T",
        help="Maximum time to wait for import in seconds (default: 600)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-F",
        help="Skip confirmation prompt",
    ),
):
    """
    Import a solution from a zip file.

    Imports the solution asynchronously. Use --stage to validate before importing.
    Use --settings to provide connection reference and environment variable mappings.

    Examples:
        copilot solution import MySolution.zip
        copilot solution import MySolution.zip --stage
        copilot solution import MySolution.zip -s settings.json --overwrite
        copilot solution import MySolution.zip --upgrade
    """
    import os

    try:
        # Verify file exists
        if not os.path.isfile(file):
            typer.echo(f"Error: File not found: {file}", err=True)
            raise typer.Exit(1)

        # Load solution file
        with open(file, "rb") as f:
            solution_bytes = f.read()

        file_size = len(solution_bytes)
        if file_size >= 1024 * 1024:
            size_str = f"{file_size / (1024 * 1024):.2f} MB"
        elif file_size >= 1024:
            size_str = f"{file_size / 1024:.2f} KB"
        else:
            size_str = f"{file_size} bytes"

        typer.echo(f"Importing solution from '{file}' ({size_str})...")

        # Load settings if provided
        component_parameters = None
        if settings_file:
            if not os.path.isfile(settings_file):
                typer.echo(f"Error: Settings file not found: {settings_file}", err=True)
                raise typer.Exit(1)

            import json
            with open(settings_file, "r") as f:
                settings = json.load(f)

            component_parameters = _build_component_parameters(settings)
            typer.echo(f"Using deployment settings from '{settings_file}'")

        client = get_client()

        # Stage solution if requested
        stage_solution_upload_id = None
        if stage:
            typer.echo("Staging solution for validation...")
            stage_results = client.stage_solution(solution_bytes)

            # Check for validation errors
            validation_results = stage_results.get("ValidationResults", [])
            has_errors = any(r.get("ErrorCode") for r in validation_results)

            if has_errors:
                typer.echo("Validation errors found:", err=True)
                for result in validation_results:
                    if result.get("ErrorCode"):
                        typer.echo(f"  - {result.get('ErrorMessage', 'Unknown error')}", err=True)
                raise typer.Exit(1)

            # Check for missing dependencies
            missing_deps = stage_results.get("MissingDependencies", [])
            if missing_deps:
                typer.echo(f"Warning: {len(missing_deps)} missing dependencies detected", err=True)
                if not force:
                    confirm = typer.confirm("Continue with import anyway?")
                    if not confirm:
                        typer.echo("Aborted.")
                        raise typer.Exit(0)

            stage_solution_upload_id = stage_results.get("StageSolutionUploadId")
            typer.echo("Solution validation passed.")

        # Confirm import
        if not force:
            confirm_msg = "Proceed with import?"
            if overwrite:
                confirm_msg = "Proceed with import (will overwrite existing customizations)?"
            if upgrade:
                confirm_msg = "Proceed with upgrade import?"

            if not typer.confirm(confirm_msg):
                typer.echo("Aborted.")
                raise typer.Exit(0)

        typer.echo("Importing solution (this may take several minutes)...")

        # Import the solution
        result = client.import_solution_async(
            solution_file=solution_bytes,
            overwrite_unmanaged_customizations=overwrite,
            publish_workflows=publish_workflows,
            component_parameters=component_parameters,
            stage_solution_upload_id=stage_solution_upload_id,
            import_as_holding=upgrade,
            timeout=float(timeout),
        )

        print_success("Solution imported successfully!")
        print_json(result)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


def _build_component_parameters(settings: dict) -> list[dict]:
    """
    Build component parameters list from deployment settings.

    Args:
        settings: Deployment settings dict with ConnectionReferences and EnvironmentVariables

    Returns:
        List of component parameter dicts for ImportSolutionAsync
    """
    params = []

    # Add connection references
    for conn_ref in settings.get("ConnectionReferences", []):
        param = {
            "@odata.type": "Microsoft.Dynamics.CRM.connectionreference",
            "connectionreferencelogicalname": conn_ref.get("LogicalName"),
            "connectionid": conn_ref.get("ConnectionId"),
            "connectorid": conn_ref.get("ConnectorId"),
        }
        params.append(param)

    # Add environment variables
    for env_var in settings.get("EnvironmentVariables", []):
        param = {
            "@odata.type": "Microsoft.Dynamics.CRM.environmentvariablevalue",
            "schemaname": env_var.get("SchemaName"),
            "value": env_var.get("Value"),
        }
        params.append(param)

    return params


@app.command("create-settings")
def create_settings(
    solution_zip: Optional[str] = typer.Option(
        None,
        "--zip",
        "-z",
        help="Path to solution zip file to extract settings from",
    ),
    solution: Optional[str] = typer.Option(
        None,
        "--solution",
        "-s",
        help="Solution name to export and extract settings from",
    ),
    output: str = typer.Option(
        ...,
        "--output",
        "-o",
        help="Output file path for the settings JSON",
    ),
):
    """
    Generate a deployment settings template from a solution.

    Creates a JSON file with connection references and environment variables
    that need to be configured for the target environment. Edit this file
    to map connections and set variable values for the target environment.

    Either --zip (existing solution file) or --solution (export from environment) is required.

    Examples:
        copilot solution create-settings -z MySolution.zip -o settings.json
        copilot solution create-settings -s MySolution -o settings.json
    """
    import os
    import json

    try:
        # Validate input - need either zip or solution
        if not solution_zip and not solution:
            typer.echo("Error: Either --zip or --solution is required", err=True)
            raise typer.Exit(1)

        if solution_zip and solution:
            typer.echo("Error: Specify either --zip or --solution, not both", err=True)
            raise typer.Exit(1)

        solution_bytes = None

        if solution_zip:
            # Read from existing zip file
            if not os.path.isfile(solution_zip):
                typer.echo(f"Error: File not found: {solution_zip}", err=True)
                raise typer.Exit(1)

            with open(solution_zip, "rb") as f:
                solution_bytes = f.read()
            typer.echo(f"Reading solution from '{solution_zip}'...")

        elif solution:
            # Export solution first
            client = get_client()
            typer.echo(f"Exporting solution '{solution}' to extract settings...")
            solution_bytes = client.export_solution_async(
                solution_name=solution,
                managed=False,
            )

        # Parse the solution zip to extract settings
        from ..solution_utils import generate_settings_template

        settings = generate_settings_template(solution_bytes)

        # Write settings to file
        with open(output, "w") as f:
            json.dump(settings, f, indent=2)

        conn_ref_count = len(settings.get("ConnectionReferences", []))
        env_var_count = len(settings.get("EnvironmentVariables", []))

        print_success(f"Settings template saved to '{output}'")
        typer.echo(f"  Connection references: {conn_ref_count}")
        typer.echo(f"  Environment variables: {env_var_count}")

        if conn_ref_count > 0 or env_var_count > 0:
            typer.echo()
            typer.echo("Edit the settings file to configure:")
            if conn_ref_count > 0:
                typer.echo("  - ConnectionId values for each connection reference")
            if env_var_count > 0:
                typer.echo("  - Value for each environment variable")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


# Register subgroups
app.add_typer(publisher_app, name="publisher")
app.add_typer(connection_reference_app, name="connection-reference")


# =========================================================================
# Solution Component Commands
# =========================================================================

@component_app.command("list")
def list_components(
    solution: str = typer.Argument(
        ...,
        help="The solution's unique name or GUID",
    ),
    component_type: Optional[int] = typer.Option(
        None,
        "--type",
        "-t",
        help="Filter by component type (numeric code, e.g., 10001 for Bot)",
    ),
    summary: bool = typer.Option(
        False,
        "--summary",
        "-s",
        help="Show summary grouped by component type instead of full list",
    ),
    environment: Optional[str] = typer.Option(
        None,
        "--environment",
        "--env",
        "-e",
        help="Environment ID to query (defaults to configured environment)",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        help="Display output as a formatted table",
    ),
    limit: int = typer.Option(
        100,
        "--limit",
        "-l",
        help="Maximum number of results to return",
    ),
    filter: Optional[list[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter results using field:op:value syntax",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of fields to include in output",
    ),
):
    """
    List all components in a solution.

    Shows all components (agents, flows, connectors, etc.) that are part of
    the specified solution.

    Examples:
        copilot solution component list MySolution
        copilot solution component list MySolution --summary
        copilot solution component list MySolution --type 10001  # Bots only
        copilot solution component list MySolution --table
        copilot solution component list MySolution --env Default-12345678-1234-1234-1234-123456789012
    """
    from cli_tools_shared.output import print_error

    try:
        # Use environment-specific client if environment is specified
        if environment:
            client = get_client_for_environment(environment)
        else:
            client = get_client()

        # Resolve solution name to ID if needed
        solution_details = client.get_solution(solution)
        solution_id = solution_details.get("solutionid")
        solution_name = solution_details.get("friendlyname", solution)

        if not solution_id:
            typer.echo(f"Error: Could not find solution '{solution}'", err=True)
            raise typer.Exit(1)

        if summary:
            # Get summary grouped by type
            result = client.get_solution_components_summary(solution_id)

            typer.echo(f"\nSolution: {solution_name}")
            typer.echo(f"Total components: {result['total_count']}\n")

            if result["by_type"]:
                summary_data = [
                    {
                        "type": type_name,
                        "count": info["count"],
                        "type_code": info["component_type"],
                    }
                    for type_name, info in result["by_type"].items()
                ]

                # Apply filters
                if filter:
                    from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError
                    try:
                        validate_filters(filter)
                        summary_data = apply_filters(summary_data, filter)
                    except FilterValidationError as e:
                        print_error(str(e))
                        raise typer.Exit(1)

                # Apply limit
                summary_data = summary_data[:limit]

                # Apply properties filter
                if properties:
                    property_list = [p.strip() for p in properties.split(",")]
                    summary_data = [{k: v for k, v in item.items() if k in property_list} for item in summary_data]

                if table:
                    print_table(
                        summary_data,
                        columns=["type", "count", "type_code"],
                        headers=["Component Type", "Count", "Type Code"],
                    )
                else:
                    print_json(summary_data)
            else:
                typer.echo("No components found in this solution.")

        else:
            # Get full component list
            components = client.get_solution_components(
                solution_id,
                component_type=component_type,
                include_type_names=True,
            )

            if not components:
                typer.echo(f"No components found in solution '{solution_name}'")
                if component_type:
                    typer.echo(f"  (filtered by component type: {component_type})")
                return

            # Format for display
            formatted = []
            for comp in components:
                formatted.append({
                    "type": comp.get("componenttype_name", "Unknown"),
                    "type_code": comp.get("componenttype"),
                    "object_id": comp.get("objectid"),
                    "component_id": comp.get("solutioncomponentid"),
                    "root_component": "Yes" if comp.get("rootcomponentbehavior") == 0 else "No",
                })

            # Apply filters
            if filter:
                from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError
                try:
                    validate_filters(filter)
                    formatted = apply_filters(formatted, filter)
                except FilterValidationError as e:
                    print_error(str(e))
                    raise typer.Exit(1)

            # Apply limit
            formatted = formatted[:limit]

            # Apply properties filter
            if properties:
                property_list = [p.strip() for p in properties.split(",")]
                formatted = [{k: v for k, v in item.items() if k in property_list} for item in formatted]

            if table:
                print_table(
                    formatted,
                    columns=["type", "object_id", "root_component", "type_code"],
                    headers=["Type", "Object ID", "Root", "Type Code"],
                )
            else:
                print_json(formatted)

            typer.echo(f"\nTotal: {len(formatted)} component(s)")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@component_app.command("get")
def get_component(
    component_id: str = typer.Argument(..., help="Solution component ID (GUID)"),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display output as a formatted table",
    ),
):
    """
    Get details for a specific solution component.

    Returns the full metadata for a solution component record by its ID.

    Examples:
        copilot solution component get 550e8400-e29b-41d4-a716-446655440000
        copilot solution component get 550e8400-e29b-41d4-a716-446655440000 --table
    """
    try:
        client = get_client()
        result = client.get(f"solutioncomponents({component_id})")

        if table:
            print_table(
                [result],
                columns=list(result.keys())[:6],
                headers=list(result.keys())[:6],
            )
        else:
            print_json(result)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@component_app.command("types")
def list_component_types(
    environment: Optional[str] = typer.Option(
        None,
        "--environment",
        "--env",
        "-e",
        help="Environment ID to query (defaults to configured environment)",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display output as a formatted table",
    ),
):
    """
    List all available solution component types.

    Shows the component type codes and names that can be used with
    the --type filter in other commands.

    Examples:
        copilot solution component types
        copilot solution component types --table
        copilot solution component types --env Default-12345678-1234-1234-1234-123456789012
    """
    try:
        # Use environment-specific client if environment is specified
        if environment:
            client = get_client_for_environment(environment)
        else:
            client = get_client()
        definitions = client.list_solution_component_definitions()

        if not definitions:
            typer.echo("No component type definitions found.")
            return

        # Format for display
        formatted = []
        for defn in definitions:
            formatted.append({
                "type_code": defn.get("solutioncomponenttype"),
                "name": defn.get("name", ""),
                "entity": defn.get("primaryentityname", ""),
                "viewable": "Yes" if defn.get("isviewable") else "No",
            })

        # Sort by type code
        formatted.sort(key=lambda x: x["type_code"] or 0)

        if table:
            print_table(
                formatted,
                columns=["type_code", "name", "entity", "viewable"],
                headers=["Type Code", "Name", "Entity", "Viewable"],
            )
        else:
            print_json(formatted)

        typer.echo(f"\nTotal: {len(formatted)} component type(s)")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


# Common component type aliases for user convenience
# These are standard Dataverse component type codes - some may be dynamically resolved
COMPONENT_TYPE_ALIASES = {
    "workflow": 29,        # Power Automate cloud flows
    "flow": 29,            # Alias for workflow
    "cloudflow": 29,       # Alias for workflow
    "aiproject": 401,      # AI Builder models/prompts (msdyn_aimodel entity)
    "aiplugin": 401,       # Alias for aiproject (AI Builder prompts)
    "prompt": 401,         # Alias for aiproject (AI Builder prompts)
    "bot": 10071,          # Copilot agents (dynamically resolved)
    "agent": 10071,        # Alias for bot (dynamically resolved)
    "connector": 371,      # Custom connectors
    "connectionreference": 10062,  # Connection references (dynamically resolved)
    "envvardef": 380,      # Environment variable definitions
    "envvarval": 381,      # Environment variable values
    "canvasapp": 300,      # Canvas apps
}


def resolve_component_type(client, component_type_input: str) -> int:
    """
    Resolve a component type from either a numeric string or an alias.

    Args:
        client: Dataverse client for dynamic resolution
        component_type_input: Either a numeric type code or a string alias

    Returns:
        The integer component type code

    Raises:
        typer.Exit: If the component type cannot be resolved
    """
    # Try to parse as integer first
    try:
        return int(component_type_input)
    except ValueError:
        pass

    # Try alias lookup (case-insensitive)
    alias_lower = component_type_input.lower()
    if alias_lower in COMPONENT_TYPE_ALIASES:
        # For aliases that may vary by environment, try dynamic resolution first
        # Note: aiplugin/prompt aliases use standard type 401 (AI Project) - no dynamic resolution
        if alias_lower in ("bot", "agent"):
            dynamic_type = client.get_solution_component_type("bot")
            if dynamic_type is not None:
                return dynamic_type
        elif alias_lower == "connectionreference":
            dynamic_type = client.get_solution_component_type("connectionreference")
            if dynamic_type is not None:
                return dynamic_type

        return COMPONENT_TYPE_ALIASES[alias_lower]

    # Try dynamic resolution as entity name
    dynamic_type = client.get_solution_component_type(component_type_input)
    if dynamic_type is not None:
        return dynamic_type

    typer.echo(
        f"Error: Unknown component type '{component_type_input}'.\n"
        f"Use a numeric type code, an alias ({', '.join(sorted(COMPONENT_TYPE_ALIASES.keys()))}), "
        "or an entity logical name.",
        err=True,
    )
    raise typer.Exit(1)


@component_app.command("add")
def add_component_to_solution(
    solution: Optional[str] = typer.Option(
        None,
        "--solution",
        "-s",
        help="The solution's unique name",
    ),
    solution_id: Optional[str] = typer.Option(
        None,
        "--solution-id",
        help="The solution's ID (GUID)",
    ),
    component_type: str = typer.Option(
        ...,
        "--component-type",
        "-t",
        help="Component type: numeric code, alias (workflow, aiplugin, bot, connector), or entity name",
    ),
    component_id: str = typer.Option(
        ...,
        "--component-id",
        "-c",
        help="The component's unique identifier (GUID)",
    ),
    add_required: bool = typer.Option(
        True,
        "--add-required/--no-required",
        help="Add required dependent components (default: True)",
    ),
):
    """
    Add any component type to a solution.

    This is a generic command that can add any component type (workflows, prompts,
    bots, connectors, etc.) to an unmanaged solution. For commonly-used types,
    you can use aliases instead of numeric codes.

    Component type can be specified as:
    - A numeric type code (e.g., 29 for workflow, 401 for AI prompt)
    - An alias: workflow/flow/cloudflow (29), prompt/aiplugin/aiproject (401),
      bot/agent, connector, connectionreference, envvardef, envvarval, canvasapp
    - An entity logical name (e.g., "environmentvariabledefinition")

    Use 'copilot solution component types' to see all available type codes.

    Examples:
        # Add a workflow (cloud flow) by alias
        copilot solution component add -s MySolution -t workflow -c <flow-guid>

        # Add an AI Builder prompt (using msdyn_aimodelid)
        copilot solution component add -s MySolution -t prompt -c <prompt-guid>
        copilot solution component add -s MySolution -t aiplugin -c <prompt-guid>

        # Add a component by numeric type code
        copilot solution component add -s MySolution -t 29 -c <flow-guid>

        # Use solution ID instead of name
        copilot solution component add --solution-id <guid> -t workflow -c <flow-guid>

        # Don't add required dependencies
        copilot solution component add -s MySolution -t workflow -c <flow-guid> --no-required
    """
    try:
        # Validate that exactly one of --solution or --solution-id is provided
        if solution and solution_id:
            typer.echo("Error: Specify either --solution or --solution-id, not both.", err=True)
            raise typer.Exit(1)
        if not solution and not solution_id:
            typer.echo("Error: Either --solution or --solution-id is required.", err=True)
            raise typer.Exit(1)

        client = get_client()

        # Resolve solution unique name
        solution_identifier = solution or solution_id
        solution_details = client.get_solution(solution_identifier)
        solution_unique_name = solution_details.get("uniquename")
        solution_display_name = solution_details.get("friendlyname", solution_unique_name)

        if solution_details.get("ismanaged"):
            typer.echo("Error: Cannot add components to a managed solution.", err=True)
            raise typer.Exit(1)

        # Resolve component type
        resolved_type = resolve_component_type(client, component_type)

        # Get component type name for display
        type_name = client.get_component_type_name(resolved_type) or f"Type {resolved_type}"

        # Add the component
        client.add_solution_component(
            solution_unique_name=solution_unique_name,
            component_id=component_id,
            component_type=resolved_type,
            add_required_components=add_required,
        )

        print_success(f"{type_name} component added to solution '{solution_display_name}'.")

        if add_required:
            typer.echo("Note: Required dependent components were also added.")

    except Exception as e:
        error_str = str(e).lower()
        # Handle "already exists" gracefully
        if "already exists" in error_str or "duplicate" in error_str:
            typer.echo("Component already exists in the solution.", err=True)
            raise typer.Exit(0)  # Not an error - idempotent success
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@component_app.command("remove")
def remove_component_from_solution(
    solution: Optional[str] = typer.Option(
        None,
        "--solution",
        "-s",
        help="The solution's unique name",
    ),
    solution_id: Optional[str] = typer.Option(
        None,
        "--solution-id",
        help="The solution's ID (GUID)",
    ),
    component_type: str = typer.Option(
        ...,
        "--component-type",
        "-t",
        help="Component type: numeric code, alias (workflow, aiplugin, bot, connector), or entity name",
    ),
    component_id: str = typer.Option(
        ...,
        "--component-id",
        "-c",
        help="The component's unique identifier (GUID)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-F",
        help="Skip confirmation prompt",
    ),
):
    """
    Remove any component type from a solution.

    This removes the component from the solution but does NOT delete the component itself.
    The component will remain in the environment.

    Component type can be specified as:
    - A numeric type code (e.g., 29 for workflow, 401 for AI prompt)
    - An alias: workflow/flow/cloudflow (29), prompt/aiplugin/aiproject (401),
      bot/agent, connector, connectionreference, envvardef, envvarval, canvasapp
    - An entity logical name (e.g., "environmentvariabledefinition")

    Use 'copilot solution component types' to see all available type codes.

    Examples:
        # Remove a workflow (cloud flow)
        copilot solution component remove -s MySolution -t workflow -c <flow-guid>

        # Remove an AI Builder prompt (using msdyn_aimodelid)
        copilot solution component remove -s MySolution -t prompt -c <prompt-guid>

        # Skip confirmation
        copilot solution component remove -s MySolution -t workflow -c <flow-guid> --force
    """
    try:
        # Validate that exactly one of --solution or --solution-id is provided
        if solution and solution_id:
            typer.echo("Error: Specify either --solution or --solution-id, not both.", err=True)
            raise typer.Exit(1)
        if not solution and not solution_id:
            typer.echo("Error: Either --solution or --solution-id is required.", err=True)
            raise typer.Exit(1)

        client = get_client()

        # Resolve solution unique name
        solution_identifier = solution or solution_id
        solution_details = client.get_solution(solution_identifier)
        solution_unique_name = solution_details.get("uniquename")
        solution_display_name = solution_details.get("friendlyname", solution_unique_name)

        if solution_details.get("ismanaged"):
            typer.echo("Error: Cannot remove components from a managed solution.", err=True)
            raise typer.Exit(1)

        # Resolve component type
        resolved_type = resolve_component_type(client, component_type)

        # Get component type name for display
        type_name = client.get_component_type_name(resolved_type) or f"Type {resolved_type}"

        if not force:
            confirm = typer.confirm(
                f"Remove {type_name} component from solution '{solution_display_name}'?"
            )
            if not confirm:
                typer.echo("Aborted.")
                raise typer.Exit(0)

        # Remove the component
        client.remove_solution_component(
            solution_unique_name=solution_unique_name,
            component_id=component_id,
            component_type=resolved_type,
        )

        print_success(f"{type_name} component removed from solution '{solution_display_name}'.")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)
