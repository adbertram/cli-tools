"""Agent commands for Copilot CLI."""
import inspect
import typer
import httpx
import time
import os
import base64
import json
import mimetypes
from pathlib import Path
from typing import Optional

from ..client import get_client


def _token_cache_path(filename: str) -> Path:
    """Return a user-writable path for an MSAL token cache file.

    Resolves under the active/default cli-tools authentication profile cache.
    """
    from ..config import get_cache_root

    cache_dir = get_cache_root()
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / filename
from cli_tools_shared.output import (
    print_json,
    print_table,
    print_success,
    print_warning,
    print_error,
    handle_error,
    safe_symbol,
)
from ..validation import (
    validate_agent_instructions,
    format_instruction_validation_errors,
)

app = typer.Typer(help="Manage Copilot Studio agents")

COMMAND_CREDENTIALS = {
    "analytics": [
        "custom"
    ],
    "auth": [
        "custom"
    ],
    "channel": [
        "custom"
    ],
    "create": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "knowledge": [
        "custom"
    ],
    "list": [
        "custom"
    ],
    "model": [
        "custom"
    ],
    "permissions": [
        "custom"
    ],
    "prompt": [
        "custom"
    ],
    "publish": [
        "custom"
    ],
    "remove": [
        "custom"
    ],
    "tool": [
        "custom"
    ],
    "topic": [
        "custom"
    ],
    "transcript": [
        "custom"
    ],
    "trigger": [
        "custom"
    ],
    "update": [
        "custom"
    ]
}

# Placeholder for permissions subcommand (coming soon)
permissions_app = typer.Typer(help="Manage agent permissions (coming soon)")


@permissions_app.callback(invoke_without_command=True)
def permissions_placeholder(ctx: typer.Context):
    """Manage agent permissions (grant, revoke, list)."""
    if ctx.invoked_subcommand is None:
        typer.echo("Agent permissions management is coming soon.")
        typer.echo("\nFor now, use the Power Platform admin center to manage agent permissions.")
        raise typer.Exit(0)


app.add_typer(permissions_app, name="permissions")


# Authentication mode mapping
AUTH_MODE_MAP = {
    "none": 1,
    "integrated": 2,
    "custom": 3,
}

AUTH_TRIGGER_MAP = {
    "as-needed": 0,
    "always": 1,
}

# Content moderation level mapping (CLI value -> API value)
CONTENT_MODERATION_LEVELS = {
    "low": "Low",
    "moderate": "Moderate",
    "high": "High",
}

# Warning message for connector tool compatibility
CONNECTOR_AUTH_WARNING = (
    "Using auth-mode 'none' or 'custom' may cause connector tools to fail with error: "
    '"The Topic with Id unknown was not found in the definition. Please check that the '
    'Topic is present and that the Id is correct. Error code: SignInTopicNeededButNotFound". '
    "Use auth-mode 'integrated' to prevent this issue when adding connector tools."
)


# Fields in bot data that contain JSON strings and should be parsed
BOT_JSON_STRING_FIELDS = ["configuration", "synchronizationstatus"]

AGENT_FIELD_ALIASES = {
    "id": "botid",
    "botId": "botid",
    "schemaName": "schemaname",
    "logicalName": "schemaname",
    "stateCode": "statecode",
    "statusCode": "statuscode",
    "publishedOn": "publishedon",
    "createdOn": "createdon",
    "modifiedOn": "modifiedon",
}


def normalize_bot_output(bot: dict) -> dict:
    """
    Normalize bot output by parsing JSON string fields into proper objects.

    Dataverse stores some fields (like configuration, synchronizationstatus) as
    JSON strings. This function parses them into proper JSON objects for cleaner output.

    Args:
        bot: Raw bot data from Dataverse API

    Returns:
        Bot data with JSON string fields parsed into objects
    """
    result = bot.copy()

    for field in BOT_JSON_STRING_FIELDS:
        if field in result and isinstance(result[field], str):
            try:
                result[field] = json.loads(result[field])
            except (json.JSONDecodeError, TypeError):
                # Keep original string if parsing fails
                pass

    return result


def format_bot_for_display(bot: dict) -> dict:
    """
    Format a bot dictionary for display purposes.

    Extracts and formats key fields for table/JSON output.

    Args:
        bot: Raw bot data from Dataverse API

    Returns:
        Formatted bot dictionary with display-friendly fields
    """
    # Map statecode values to human-readable strings
    state_map = {0: "Active", 1: "Inactive"}
    status_map = {1: "Active", 2: "Inactive"}

    statecode = bot.get("statecode")
    statuscode = bot.get("statuscode")
    publishedon = bot.get("publishedon")

    bot_id = bot.get("botid", "")
    schema_name = bot.get("schemaname", "")
    return {
        "id": bot_id,
        "name": bot.get("name", ""),
        "botid": bot_id,
        "schemaname": schema_name,
        "schemaName": schema_name,
        "logicalName": schema_name,
        "statecode": state_map.get(statecode, str(statecode) if statecode is not None else ""),
        "statuscode": status_map.get(statuscode, str(statuscode) if statuscode is not None else ""),
        "published": publishedon is not None,
        "createdon": bot.get("createdon", ""),
        "modifiedon": bot.get("modifiedon", ""),
    }


def format_transcript_for_display(transcript: dict) -> dict:
    """
    Format a transcript dictionary for display purposes.

    Args:
        transcript: Raw transcript data from Dataverse API

    Returns:
        Formatted transcript dictionary with display-friendly fields
    """
    # Get bot name from OData annotation, fall back to ID
    bot_name = transcript.get(
        "_bot_conversationtranscriptid_value@OData.Community.Display.V1.FormattedValue",
        transcript.get("_bot_conversationtranscriptid_value", "Unknown"),
    )

    start_time = transcript.get("conversationstarttime", "")
    if start_time:
        start_time = start_time.replace("T", " ").replace("Z", "")

    return {
        "id": transcript.get("conversationtranscriptid", ""),
        "name": transcript.get("name", ""),
        "agent_name": bot_name,
        "start_time": start_time,
    }


def format_transcript_content(content: str) -> str:
    """
    Format transcript content JSON into a human-readable conversation.

    Args:
        content: JSON string containing transcript activities

    Returns:
        Formatted conversation string
    """
    if not content:
        return "(No content)"

    try:
        data = json.loads(content)
    except (json.JSONDecodeError, TypeError):
        return content

    activities = data.get("activities", [])
    if not activities:
        return "(No activities)"

    lines = []
    for activity in activities:
        activity_type = activity.get("type", "")
        if activity_type != "message":
            continue

        from_info = activity.get("from", {})
        role = from_info.get("role", "unknown")
        text = activity.get("text", "")

        if role == "user":
            prefix = "User"
        elif role == "bot":
            prefix = "Bot"
        else:
            prefix = role.capitalize()

        if text:
            lines.append(f"{prefix}: {text}")

    return "\n".join(lines) if lines else "(No messages)"


@app.command("list")
def list_agents(
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display output as a formatted table instead of JSON",
    ),
    all_fields: bool = typer.Option(
        False,
        "--all",
        "-a",
        help="Include all fields in the output (JSON mode only)",
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
        help="Filter results using field:op:value syntax (e.g., name:eq:MyAgent)",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of fields to include in output",
    ),
):
    """
    List all Copilot Studio agents in the environment.

    Returns agents with their agent_id, name, schema name, and status.

    Examples:
        copilot agent list
        copilot agent list --table
        copilot agent list --all
        copilot agent list --limit 50
        copilot agent list --filter "name:eq:MyAgent"
        copilot agent list --properties "name,botid,statecode"
    """
    try:
        client = get_client()

        # Determine which fields to select
        select_fields = None
        # Map generic/camelCase field names to Dataverse entity fields
        # Fields required by format_bot_for_display to compute derived values
        _display_deps = {"publishedon", "statecode", "statuscode", "createdon", "modifiedon"}
        if properties:
            select_fields = [AGENT_FIELD_ALIASES.get(f.strip(), f.strip()) for f in properties.split(",")]
            # Always fetch fields needed for display formatting (published, statecode labels, etc.)
            for dep in _display_deps:
                if dep not in select_fields:
                    select_fields.append(dep)
        elif not all_fields:
            select_fields = ["name", "botid", "schemaname", "statecode", "statuscode", "publishedon", "createdon", "modifiedon"]

        bots = client.list_bots(
            select=select_fields,
            limit=limit,
            filter=filter,
        )

        if table:
            # Format for table display
            formatted = [format_bot_for_display(bot) for bot in bots]
            if properties:
                # Map aliases back for output filtering
                _reverse_aliases = {v: k for k, v in AGENT_FIELD_ALIASES.items()}
                prop_list = [p.strip() for p in properties.split(",")]
                # Include both alias and original name
                prop_set = set(prop_list)
                for p in prop_list:
                    if p in AGENT_FIELD_ALIASES:
                        prop_set.add(AGENT_FIELD_ALIASES[p])
                    if p in _reverse_aliases:
                        prop_set.add(_reverse_aliases[p])
                formatted = [{k: v for k, v in item.items() if k in prop_set} for item in formatted]
                print_table(formatted, columns=list(prop_set), headers=list(prop_set))
            else:
                print_table(
                    formatted,
                    columns=["name", "botid", "statecode", "published"],
                    headers=["Name", "Agent ID", "State", "Published"],
                )
        else:
            if all_fields:
                print_json(bots)
            else:
                formatted = [format_bot_for_display(bot) for bot in bots]
                if properties:
                    _reverse_aliases = {v: k for k, v in AGENT_FIELD_ALIASES.items()}
                    prop_list = [p.strip() for p in properties.split(",")]
                    prop_set = set(prop_list)
                    for p in prop_list:
                        if p in AGENT_FIELD_ALIASES:
                            prop_set.add(AGENT_FIELD_ALIASES[p])
                        if p in _reverse_aliases:
                            prop_set.add(_reverse_aliases[p])
                    formatted = [{k: v for k, v in item.items() if k in prop_set} for item in formatted]
                print_json(formatted)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("get")
def get_agent(
    agent_id: str = typer.Argument(..., help="The agent's unique identifier (GUID)"),
    include_components: bool = typer.Option(
        False,
        "--components",
        "-c",
        help="Include agent components (topics, triggers, etc.)",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display output as a formatted table instead of JSON",
    ),
):
    """
    Get details for a specific Copilot Studio agent.

    Examples:
        copilot agent get 12345678-1234-1234-1234-123456789abc
        copilot agent get 12345678-1234-1234-1234-123456789abc --components
        copilot agent get 12345678-1234-1234-1234-123456789abc --table
    """
    try:
        client = get_client()
        bot = client.get_bot(agent_id)

        if include_components:
            components = client.get_bot_components(agent_id)
            bot["components"] = components

        # Parse JSON string fields into proper objects
        bot = normalize_bot_output(bot)

        # Fetch instructions from botcomponent (source of truth)
        # The bot's configuration.gPTSettings.systemPrompt may be stale
        # when instructions are edited via Copilot Studio UI
        # Check if Custom GPT component exists first
        gpt_component = client.get_custom_gpt_component(agent_id)
        if gpt_component:
            # Component exists - use its instructions as source of truth
            # This may be None/empty if instructions haven't been set in the component
            actual_instructions = client.get_gpt_instructions(agent_id)
            if "configuration" not in bot:
                bot["configuration"] = {}
            if "gPTSettings" not in bot["configuration"]:
                bot["configuration"]["gPTSettings"] = {}
            # Always use botcomponent instructions (even if empty/None)
            # This ensures Ansible can detect when component needs updating
            bot["configuration"]["gPTSettings"]["systemPrompt"] = actual_instructions or ""

            # Include response formatting instructions if set
            response_instructions = client.get_response_instructions(agent_id)
            if response_instructions:
                bot["configuration"]["gPTSettings"]["responseInstructions"] = response_instructions

        if table:
            formatted = format_bot_for_display(bot)
            print_table(
                [formatted],
                columns=["name", "botid", "statecode", "published"],
                headers=["Name", "Agent ID", "State", "Published"],
            )
        else:
            print_json(bot)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("remove")
def remove_agent(
    agent_id: str = typer.Argument(..., help="The agent's unique identifier (GUID)"),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Skip confirmation prompt",
    ),
    cascade: bool = typer.Option(
        False,
        "--cascade",
        "-c",
        help="Delete all dependent components (topics, tools, etc.) before deleting the agent",
    ),
):
    """
    Remove (delete) a Copilot Studio agent.

    Examples:
        copilot agent remove 12345678-1234-1234-1234-123456789abc
        copilot agent remove 12345678-1234-1234-1234-123456789abc --force
        copilot agent remove 12345678-1234-1234-1234-123456789abc --cascade --force
    """
    try:
        client = get_client()

        # Get agent details first to show name in confirmation
        bot = client.get_bot(agent_id)
        agent_name = bot.get("name", agent_id)

        if not force:
            confirm = typer.confirm(f"Are you sure you want to delete agent '{agent_name}'?")
            if not confirm:
                typer.echo("Aborted.")
                raise typer.Exit(0)

        # If cascade, delete all components first
        if cascade:
            _delete_agent_components(client, agent_id)

        try:
            client.delete_bot(agent_id)
            print_success(f"Agent '{agent_name}' deleted successfully.")
        except Exception as e:
            error_msg = str(e)
            # Check if error is about referenced components
            if "referenced by" in error_msg and "other components" in error_msg:
                # List the dependent components
                typer.echo(f"\nAgent '{agent_name}' cannot be deleted due to dependent components:\n")
                components = client.get_bot_components(agent_id)

                if components:
                    # Group by component type
                    topics = [c for c in components if c.get("componenttype") in (0, 9)]
                    tools = [c for c in components if "InvokeConnectedAgentTaskAction" in (c.get("schemaname") or "")]
                    other = [c for c in components if c not in topics and c not in tools]

                    if topics:
                        typer.echo(f"  Topics ({len(topics)}):")
                        for t in topics[:10]:  # Show first 10
                            typer.echo(f"    - {t.get('name', 'Unknown')}")
                        if len(topics) > 10:
                            typer.echo(f"    ... and {len(topics) - 10} more")

                    if tools:
                        typer.echo(f"\n  Tools ({len(tools)}):")
                        for t in tools[:10]:
                            typer.echo(f"    - {t.get('name', 'Unknown')}")
                        if len(tools) > 10:
                            typer.echo(f"    ... and {len(tools) - 10} more")

                    if other:
                        typer.echo(f"\n  Other components ({len(other)}):")
                        for c in other[:10]:
                            typer.echo(f"    - {c.get('name', 'Unknown')} (type: {c.get('componenttype')})")
                        if len(other) > 10:
                            typer.echo(f"    ... and {len(other) - 10} more")

                typer.echo(f"\nTo delete the agent and all its components, use:")
                typer.echo(f"  copilot agent remove {agent_id} --cascade --force")
                raise typer.Exit(1)
            else:
                raise
    except typer.Exit:
        raise
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


def _delete_agent_components(client, agent_id: str) -> None:
    """Delete all components for an agent before deletion."""
    components = client.get_bot_components(agent_id)
    if not components:
        return

    typer.echo(f"Deleting {len(components)} component(s)...")
    deleted = 0
    for comp in components:
        comp_id = comp.get("botcomponentid")
        comp_name = comp.get("name", "Unknown")
        if comp_id:
            try:
                client.delete(f"botcomponents({comp_id})")
                deleted += 1
            except Exception:
                pass  # Some components may fail, continue with others
    typer.echo(f"Deleted {deleted} component(s).")


@app.command("publish")
def publish_agent(
    agent_id: str = typer.Argument(..., help="The agent's unique identifier (GUID)"),
):
    """
    Publish a Copilot Studio agent.

    Publishing makes the latest changes to your agent available to users.
    This includes changes to topics, knowledge sources, tools, and settings.

    Note: Publishing may take a few minutes to complete.

    Examples:
        copilot agent publish 12345678-1234-1234-1234-123456789abc
    """
    try:
        client = get_client()

        # Get agent details first to show name
        bot = client.get_bot(agent_id)
        agent_name = bot.get("name", agent_id)

        typer.echo(f"Publishing agent '{agent_name}'...")

        result = client.publish_bot(agent_id)

        print_success(f"Agent '{agent_name}' published successfully!")
        if result.get("PublishedBotContentId"):
            typer.echo(f"Published Content ID: {result['PublishedBotContentId']}")
        if result.get("publishedon"):
            typer.echo(f"Published on: {result['publishedon']}")
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("update")
def update_agent(
    agent_id: str = typer.Argument(..., help="The agent's unique identifier (GUID)"),
    name: Optional[str] = typer.Option(
        None,
        "--name",
        "-n",
        help="New display name for the agent",
    ),
    description: Optional[str] = typer.Option(
        None,
        "--description",
        "-d",
        help="New description for the agent",
    ),
    instructions: Optional[str] = typer.Option(
        None,
        "--instructions",
        "-i",
        help="New system instructions/prompt for the agent",
    ),
    instructions_file: Optional[str] = typer.Option(
        None,
        "--instructions-file",
        help="Path to file containing new system instructions",
    ),
    orchestration: Optional[bool] = typer.Option(
        None,
        "--orchestration/--no-orchestration",
        help="Enable/disable generative AI orchestration",
    ),
    auth_mode: Optional[str] = typer.Option(
        None,
        "--auth-mode",
        help="Authentication mode: none, integrated, or custom",
    ),
    auth_trigger: Optional[str] = typer.Option(
        None,
        "--auth-trigger",
        help="Authentication trigger: as-needed or always",
    ),
    content_moderation: Optional[str] = typer.Option(
        None,
        "--content-moderation",
        help="Content moderation level: low, moderate, or high",
    ),
    web_search: Optional[bool] = typer.Option(
        None,
        "--web-search/--no-web-search",
        help="Enable/disable web search (Bing web browsing) capability",
    ),
    response_format: Optional[str] = typer.Option(
        None,
        "--response-format",
        help="Response formatting instructions (controls how the agent crafts responses)",
    ),
    response_format_file: Optional[str] = typer.Option(
        None,
        "--response-format-file",
        help="Path to file containing response formatting instructions",
    ),
):
    """
    Update an existing Copilot Studio agent.

    Note: Model selection must be configured via the model set command.

    Examples:
        copilot agent update <agent-id> --name "New Name"
        copilot agent update <agent-id> --description "New description"
        copilot agent update <agent-id> --instructions "New system prompt"
        copilot agent update <agent-id> --instructions-file ./prompt.txt
        copilot agent update <agent-id> --no-orchestration
        copilot agent update <agent-id> --auth-mode integrated --auth-trigger always
        copilot agent update <agent-id> --content-moderation low
        copilot agent update <agent-id> --web-search
        copilot agent update <agent-id> --no-web-search
        copilot agent update <agent-id> --response-format "Always respond in bullet points"
        copilot agent update <agent-id> --response-format-file ./response-format.txt
    """
    try:
        # Validate and convert auth_mode if provided
        auth_mode_int = None
        if auth_mode is not None:
            auth_mode_lower = auth_mode.lower()
            if auth_mode_lower not in AUTH_MODE_MAP:
                typer.echo(f"Error: Invalid auth-mode '{auth_mode}'. Valid options: none, integrated, custom", err=True)
                raise typer.Exit(1)
            auth_mode_int = AUTH_MODE_MAP[auth_mode_lower]

            # Warn about connector tool compatibility for non-integrated auth modes
            if auth_mode_lower in ("none", "custom"):
                print_warning(CONNECTOR_AUTH_WARNING)

        # Validate and convert auth_trigger if provided
        auth_trigger_int = None
        if auth_trigger is not None:
            auth_trigger_lower = auth_trigger.lower()
            if auth_trigger_lower not in AUTH_TRIGGER_MAP:
                typer.echo(f"Error: Invalid auth-trigger '{auth_trigger}'. Valid options: as-needed, always", err=True)
                raise typer.Exit(1)
            auth_trigger_int = AUTH_TRIGGER_MAP[auth_trigger_lower]

        # Validate content_moderation if provided
        content_moderation_value = None
        if content_moderation is not None:
            content_moderation_lower = content_moderation.lower()
            if content_moderation_lower not in CONTENT_MODERATION_LEVELS:
                typer.echo(f"Error: Invalid content-moderation '{content_moderation}'. Valid options: low, moderate, high", err=True)
                raise typer.Exit(1)
            content_moderation_value = CONTENT_MODERATION_LEVELS[content_moderation_lower]

        # Handle instructions from file if provided
        agent_instructions = instructions
        if instructions_file:
            try:
                with open(instructions_file, "r") as f:
                    agent_instructions = f.read()
            except FileNotFoundError:
                typer.echo(f"Error: Instructions file not found: {instructions_file}", err=True)
                raise typer.Exit(1)
            except IOError as e:
                typer.echo(f"Error reading instructions file: {e}", err=True)
                raise typer.Exit(1)

        # Validate instructions for Power Fx expression issues before API call
        if agent_instructions:
            validation_result = validate_agent_instructions(agent_instructions)
            if not validation_result.is_valid:
                typer.echo(format_instruction_validation_errors(validation_result), err=True)
                raise typer.Exit(1)

        # Handle response format from file if provided
        agent_response_format = response_format
        if response_format_file:
            try:
                with open(response_format_file, "r") as f:
                    agent_response_format = f.read()
            except FileNotFoundError:
                typer.echo(f"Error: Response format file not found: {response_format_file}", err=True)
                raise typer.Exit(1)
            except IOError as e:
                typer.echo(f"Error reading response format file: {e}", err=True)
                raise typer.Exit(1)

        client = get_client()

        # Get current agent name for success message
        current_bot = client.get_bot(agent_id)
        agent_name = name if name else current_bot.get("name", agent_id)

        # Track what was updated for success message
        updates_made = []

        # Update bot settings (name, description, orchestration, content moderation - NOT instructions)
        if name or description or orchestration is not None or content_moderation_value is not None:
            client.update_bot(
                bot_id=agent_id,
                name=name,
                description=description,
                orchestration=orchestration,
                content_moderation=content_moderation_value,
            )
            if name:
                updates_made.append("name")
            if description:
                updates_made.append("description")
            if orchestration is not None:
                updates_made.append("orchestration")
            if content_moderation_value is not None:
                updates_made.append(f"content-moderation={content_moderation_value}")

        # Update instructions via botcomponent API (the correct API)
        if agent_instructions:
            client.update_gpt_instructions(agent_id, agent_instructions)
            updates_made.append("instructions")

        # Update auth settings if provided
        if auth_mode_int is not None or auth_trigger_int is not None:
            client.update_bot_auth(
                bot_id=agent_id,
                mode=auth_mode_int,
                trigger=auth_trigger_int,
            )
            updates_made.append("auth")

        # Update web search (web browsing) if provided
        if web_search is not None:
            client.update_web_search(agent_id, web_search)
            updates_made.append(f"web-search={'enabled' if web_search else 'disabled'}")

        # Update response formatting if provided
        if agent_response_format:
            client.update_response_instructions(agent_id, agent_response_format)
            updates_made.append("response-format")

        if not updates_made:
            typer.echo("No updates specified.", err=True)
            raise typer.Exit(1)

        print_success(f"Agent '{agent_name}' updated successfully ({', '.join(updates_made)}).")
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("create")
def create_agent(
    name: str = typer.Option(
        ...,
        "--name",
        "-n",
        help="Display name for the agent",
    ),
    description: Optional[str] = typer.Option(
        None,
        "--description",
        "-d",
        help="Description for the agent",
    ),
    schema_name: Optional[str] = typer.Option(
        None,
        "--schema-name",
        "-s",
        help="Internal schema name (auto-generated from name if not provided)",
    ),
    instructions: Optional[str] = typer.Option(
        None,
        "--instructions",
        "-i",
        help="System instructions/prompt for the agent",
    ),
    instructions_file: Optional[str] = typer.Option(
        None,
        "--instructions-file",
        help="Path to file containing system instructions",
    ),
    orchestration: bool = typer.Option(
        True,
        "--orchestration/--no-orchestration",
        help="Enable/disable generative AI orchestration (default: enabled)",
    ),
    auth_mode: str = typer.Option(
        "integrated",
        "--auth-mode",
        help="Authentication mode: none, integrated (default), or custom",
    ),
    auth_trigger: str = typer.Option(
        "always",
        "--auth-trigger",
        help="Authentication trigger: as-needed or always (default)",
    ),
    response_format: Optional[str] = typer.Option(
        None,
        "--response-format",
        help="Response formatting instructions (controls how the agent crafts responses)",
    ),
    response_format_file: Optional[str] = typer.Option(
        None,
        "--response-format-file",
        help="Path to file containing response formatting instructions",
    ),
):
    """
    Create a new Copilot Studio agent.

    Note: Model selection must be configured via the model set command.

    Examples:
        copilot agent create --name "My Agent"
        copilot agent create --name "My Agent" --description "A helpful assistant"
        copilot agent create --name "My Agent" --instructions "You are a helpful assistant"
        copilot agent create --name "My Agent" --instructions-file ./prompt.txt
        copilot agent create --name "My Agent" --no-orchestration
        copilot agent create --name "My Agent" --auth-mode none --auth-trigger as-needed
        copilot agent create --name "My Agent" --response-format "Always respond in bullet points"
        copilot agent create --name "My Agent" --response-format-file ./response-format.txt
    """
    try:
        # Validate and convert auth_mode
        auth_mode_lower = auth_mode.lower()
        if auth_mode_lower not in AUTH_MODE_MAP:
            typer.echo(f"Error: Invalid auth-mode '{auth_mode}'. Valid options: none, integrated, custom", err=True)
            raise typer.Exit(1)
        auth_mode_int = AUTH_MODE_MAP[auth_mode_lower]

        # Validate and convert auth_trigger
        auth_trigger_lower = auth_trigger.lower()
        if auth_trigger_lower not in AUTH_TRIGGER_MAP:
            typer.echo(f"Error: Invalid auth-trigger '{auth_trigger}'. Valid options: as-needed, always", err=True)
            raise typer.Exit(1)
        auth_trigger_int = AUTH_TRIGGER_MAP[auth_trigger_lower]

        # Warn about connector tool compatibility for non-integrated auth modes
        if auth_mode_lower in ("none", "custom"):
            print_warning(CONNECTOR_AUTH_WARNING)

        # Handle instructions from file if provided
        agent_instructions = instructions
        if instructions_file:
            try:
                with open(instructions_file, "r") as f:
                    agent_instructions = f.read()
            except FileNotFoundError:
                typer.echo(f"Error: Instructions file not found: {instructions_file}", err=True)
                raise typer.Exit(1)
            except IOError as e:
                typer.echo(f"Error reading instructions file: {e}", err=True)
                raise typer.Exit(1)

        # Validate instructions for Power Fx expression issues before API call
        if agent_instructions:
            validation_result = validate_agent_instructions(agent_instructions)
            if not validation_result.is_valid:
                typer.echo(format_instruction_validation_errors(validation_result), err=True)
                raise typer.Exit(1)

        # Handle response format from file if provided
        agent_response_format = response_format
        if response_format_file:
            try:
                with open(response_format_file, "r") as f:
                    agent_response_format = f.read()
            except FileNotFoundError:
                typer.echo(f"Error: Response format file not found: {response_format_file}", err=True)
                raise typer.Exit(1)
            except IOError as e:
                typer.echo(f"Error reading response format file: {e}", err=True)
                raise typer.Exit(1)

        client = get_client()
        result = client.create_bot(
            name=name,
            schema_name=schema_name,
            instructions=agent_instructions,
            description=description,
            orchestration=orchestration,
            auth_mode=auth_mode_int,
            auth_trigger=auth_trigger_int,
        )

        # Output JSON with agent ID for programmatic use
        bot_id = result.get("botid") or result.get("id") if result else None

        # Set response formatting if provided (requires a post-create update)
        if agent_response_format and bot_id:
            client.update_response_instructions(bot_id, agent_response_format)

        print_json({
            "name": name,
            "botid": bot_id,
            "status": "created"
        })
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


# =============================================================================
# Direct Line API Constants
# =============================================================================

DIRECTLINE_URL = "https://directline.botframework.com/v3/directline"


# =============================================================================
# Power Platform cloud resolution (M365 Agents SDK path)
# =============================================================================
#
# The M365 Agents SDK resolves the Copilot Studio host from the
# ``PowerPlatformCloud`` category. For commercial tenants this is the public
# cloud (``api.powerplatform.com``); sovereign clouds (US Gov, DoD, China) are
# first-class SDK enum values, so a correct cloud is derived deterministically
# from the Dataverse environment host — never hardcoded to a single tenant and
# never forced to ``Other`` (which requires an explicit base address and breaks
# normal commercial environments).
#
# Data-driven: add a sovereign cloud by adding a row here, not a code branch.
# Maps a Dataverse host suffix (the org host in DATAVERSE_URL) to the
# PowerPlatformCloud enum *name*. Commercial hosts are intentionally absent —
# they resolve to the SDK default (public/PROD) via cloud=None.
# Source: Microsoft Learn "Dynamics 365 US Government URLs" and "Discover user
# organizations" (Global Discovery Service per-cloud hosts).
DATAVERSE_HOST_CLOUD_MAP = {
    ".crm.microsoftdynamics.us": "HIGH",      # US Gov GCC High
    ".crm.appsplatform.us": "DOD",            # US Gov DoD
    ".crm9.dynamics.com": "GOV",              # US Gov GCC
    ".crm.dynamics.cn": "MOONCAKE",           # China (operated by 21Vianet)
}

# Commercial Dataverse hosts resolve to the public cloud (cloud=None). Regional
# commercial orgs use ``.crmN.dynamics.com`` (N = region number) plus the
# unnumbered North America ``.crm.dynamics.com``; GCC reuses N=9 and is handled
# above, so any other ``.dynamics.com`` host is commercial.
_COMMERCIAL_DYNAMICS_SUFFIX = ".dynamics.com"

# Optional explicit cloud override for the rare case where the Dataverse host
# cannot be auto-classified (e.g. a private/preview cloud the table does not
# cover). The value is a ``PowerPlatformCloud`` enum *name* understood by the
# installed M365 Agents SDK (case-insensitive), e.g. ``Prod``, ``Gov``,
# ``High``, ``DoD``, ``Mooncake``.
#
# This is intentionally a known cloud category, NOT a free-form base address:
# the SDK's ``Other`` / ``custom_power_platform_cloud`` code path cannot build a
# valid connection URL (it concatenates the raw value into the host), so a
# base-address override would not actually work. The legacy
# ``POWERPLATFORM_CLOUD_URL`` value (a Direct Line island-gateway host) is
# unrelated and is never consulted here.
POWERPLATFORM_CLOUD_ENV = "POWERPLATFORM_CLOUD"


def resolve_power_platform_cloud(dataverse_url, override=None):
    """Resolve the M365 Agents SDK cloud for the active Dataverse environment.

    Returns a ``(cloud, custom_base_address)`` tuple to pass straight to
    ``ConnectionSettings(cloud=..., custom_power_platform_cloud=...)``. The
    second element is always ``None`` — every supported cloud (commercial and
    sovereign) is a first-class SDK enum, so the broken ``Other`` base-address
    path is never used.

    - Commercial tenants -> ``(None, None)`` so the SDK uses the public cloud
      (``api.powerplatform.com``). This is the no-config default.
    - Sovereign clouds (US Gov GCC/GCC High/DoD, China) -> ``(<enum>, None)``
      derived from the Dataverse host; the SDK already knows their hosts.
    - Explicit ``override`` (a ``PowerPlatformCloud`` enum name) -> the matching
      enum, for clouds the host table does not classify.

    Fails loudly (ValueError) for an unknown override name or an unidentifiable
    non-commercial Dataverse host, instead of silently defaulting to public.

    :param dataverse_url: The active environment's Dataverse URL
        (e.g. ``https://org23192677.crm.dynamics.com/``). May be ``None``.
    :param override: Optional ``PowerPlatformCloud`` enum name override.
    :return: ``(cloud, custom_base_address)`` for ConnectionSettings.
    """
    from urllib.parse import urlparse

    from microsoft_agents.copilotstudio.client.power_platform_cloud import (
        PowerPlatformCloud,
    )

    # 1. Explicit operator override wins. It must name a known SDK cloud, since
    #    only enum-based clouds resolve to a usable endpoint in this SDK.
    if override:
        cloud = _coerce_power_platform_cloud(override, PowerPlatformCloud)
        if cloud is None:
            valid = ", ".join(c.value for c in PowerPlatformCloud)
            raise ValueError(
                f"{POWERPLATFORM_CLOUD_ENV}={override!r} is not a known Power "
                f"Platform cloud. Valid values: {valid}."
            )
        return (None if cloud is PowerPlatformCloud.PROD else cloud), None

    # 2. Derive from the Dataverse environment host.
    host = urlparse(dataverse_url).hostname if dataverse_url else None
    if not host:
        # No environment host to classify; let the SDK default to public cloud.
        return None, None

    host = host.lower()
    for suffix, cloud_name in DATAVERSE_HOST_CLOUD_MAP.items():
        if host.endswith(suffix):
            return PowerPlatformCloud[cloud_name], None

    # 3. Commercial Dataverse hosts -> public cloud (SDK default).
    if host.endswith(_COMMERCIAL_DYNAMICS_SUFFIX):
        return None, None

    # 4. Unidentifiable non-commercial host: fail loudly rather than guess.
    raise ValueError(
        f"Could not determine the Power Platform cloud for Dataverse host "
        f"'{host}'. If this is a sovereign cloud, add its Dataverse suffix to "
        f"DATAVERSE_HOST_CLOUD_MAP; otherwise set {POWERPLATFORM_CLOUD_ENV} to a "
        f"known cloud name (e.g. Prod, Gov, High, DoD, Mooncake)."
    )


def _coerce_power_platform_cloud(value, power_platform_cloud_enum):
    """Coerce a string to a PowerPlatformCloud enum member, or None if unknown.

    Accepts either the enum member name (e.g. ``DOD``) or its value
    (e.g. ``DoD``), case-insensitively.
    """
    candidate = value.strip()
    for member in power_platform_cloud_enum:
        if candidate.lower() in (member.name.lower(), member.value.lower()):
            return member
    return None


@app.command("prompt")
def prompt_agent(
    agent_id: str = typer.Argument(
        ...,
        help="The agent's unique identifier (GUID)",
    ),
    message: str = typer.Option(
        ...,
        "--message",
        "-m",
        help="The message/prompt to send to the agent",
    ),
    secret: Optional[str] = typer.Option(
        None,
        "--secret",
        "-s",
        help="Direct Line secret (or set DIRECTLINE_SECRET env var)",
    ),
    entra_id: bool = typer.Option(
        False,
        "--entra-id",
        help="Use Entra ID (Azure AD) authentication instead of Direct Line secret",
    ),
    client_id: Optional[str] = typer.Option(
        None,
        "--client-id",
        help="Entra ID application (client) ID (or set ENTRA_CLIENT_ID env var)",
    ),
    tenant_id: Optional[str] = typer.Option(
        None,
        "--tenant-id",
        help="Entra ID tenant ID (or set ENTRA_TENANT_ID env var)",
    ),
    scope: Optional[str] = typer.Option(
        None,
        "--scope",
        help="OAuth scope (default: https://api.powerplatform.com/.default)",
    ),
    token_endpoint: Optional[str] = typer.Option(
        None,
        "--token-endpoint",
        help="Agent token endpoint URL (from Copilot Studio > Channels > Mobile app)",
    ),
    max_polls: int = typer.Option(
        30,
        "--max-polls",
        help="Maximum number of polling attempts for response",
    ),
    poll_interval: int = typer.Option(
        3,
        "--poll-interval",
        help="Seconds between polling attempts",
    ),
    timeout: int = typer.Option(
        120,
        "--timeout",
        help="Total timeout in seconds for the request",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Show detailed progress and response information",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Output as human-readable text instead of JSON",
    ),
    file: Optional[str] = typer.Option(
        None,
        "--file",
        "-f",
        help="Path to a file to attach (Word, PDF, text, markdown, etc.)",
    ),
):
    """
    Send a prompt to a Copilot Studio agent and get the response.

    Automatically detects the agent's authentication mode and uses the appropriate method:

    1. Direct Line Secret: For agents with "No authentication" or "Authenticate manually"
    2. Entra ID + Direct Line: For manual auth agents using device code flow
    3. M365 Agents SDK: For agents with "Authenticate with Microsoft" (integrated auth)

    AUTHENTICATION MODES:

    The CLI automatically detects the agent's auth mode and handles it appropriately:

    - No Auth / Manual Auth: Uses Direct Line API with --secret or --entra-id
    - Integrated Auth ("Authenticate with Microsoft"): Uses M365 Agents SDK with
      --client-id and --tenant-id (requires microsoft-agents-copilotstudio-client package)

    M365 SDK SETUP (for Integrated Auth agents):

    1. Create an app registration in Azure Portal
    2. Go to Authentication > Enable "Allow public client flows"
    3. Go to API permissions > Add permission > APIs my organization uses
    4. Search for "Power Platform API" (ID: 8578e004-a5c6-46e7-913e-12f58912df43)
    5. Add delegated permission: CopilotStudio.Copilots.Invoke
    6. Grant admin consent for the permission
    7. Set DATAVERSE_ENVIRONMENT_ID, ENTRA_CLIENT_ID, and AZURE_TENANT_ID env vars

    DIRECT LINE SETUP (for No Auth / Manual Auth agents):

    Get your Direct Line secret from: Copilot Studio > Settings > Channels > Direct Line

    For Entra ID authentication with Direct Line, also get the token endpoint from:
    Copilot Studio > Channels > Mobile app > Token Endpoint

    Examples:
        # Integrated auth agent (uses M365 SDK automatically)
        copilot agent prompt <agent-id> -m "Hello" --client-id <app-id> --tenant-id <tenant-id>

        # Using Direct Line secret (no auth / manual auth agents)
        copilot agent prompt <agent-id> --message "Hello" --secret "your-secret"

        # Using Entra ID + Direct Line (manual auth agents)
        copilot agent prompt <agent-id> -m "Hello" --entra-id \\
            --client-id <app-client-id> --tenant-id <tenant-id> \\
            --token-endpoint "https://{ENV}.environment.api.powerplatform.com/..."

        # With file attachment
        copilot agent prompt <agent-id> -m "Review this" --file ./draft.docx --secret "xxx"

    Environment Variables:
        DIRECTLINE_SECRET - Direct Line secret (alternative to --secret)
        ENTRA_CLIENT_ID - Entra ID client ID (alternative to --client-id)
        AZURE_TENANT_ID - Azure tenant ID (alternative to --tenant-id)
        ENTRA_TENANT_ID - Alias for AZURE_TENANT_ID
        DATAVERSE_ENVIRONMENT_ID - Power Platform environment ID (for M365 SDK)
        ENTRA_SCOPE - OAuth scope (default: https://api.powerplatform.com/.default)
        AGENT_TOKEN_ENDPOINT - Agent token endpoint (for Direct Line with Entra ID)
    """
    try:
        # Check agent's authentication mode before attempting Direct Line connection
        # "Authenticate with Microsoft" (Integrated auth, mode=2) is NOT supported via Direct Line
        client = get_client()
        try:
            auth_info = client.get_bot_auth(agent_id)
            auth_mode = auth_info.get("mode", 2)

            if auth_mode == 2:  # Integrated authentication ("Authenticate with Microsoft")
                # Use M365 Agents SDK for integrated auth agents
                if verbose:
                    typer.echo("Agent uses 'Authenticate with Microsoft' - using M365 Agents SDK...")

                try:
                    from microsoft_agents.copilotstudio.client import ConnectionSettings, CopilotClient
                    from microsoft_agents.activity import ActivityTypes
                    import asyncio
                    import msal
                except ImportError as e:
                    typer.echo(f"Error: Required package not found: {e}. Reinstall with: pip install -e .", err=True)
                    raise typer.Exit(1)

                # Get required parameters for M365 SDK
                from copilot_cli.config import Config
                config = Config()

                m365_environment_id = os.environ.get("DATAVERSE_ENVIRONMENT_ID") or os.environ.get("POWERPLATFORM_ENVIRONMENT_ID")
                m365_client_id = client_id or os.environ.get("ENTRA_CLIENT_ID")
                m365_tenant_id = tenant_id or os.environ.get("AZURE_TENANT_ID") or os.environ.get("ENTRA_TENANT_ID")

                if not m365_environment_id:
                    typer.echo("Error: Environment ID required for M365 SDK.", err=True)
                    typer.echo("Set DATAVERSE_ENVIRONMENT_ID or POWERPLATFORM_ENVIRONMENT_ID env var.", err=True)
                    raise typer.Exit(1)

                if not m365_client_id:
                    typer.echo("Error: --client-id or ENTRA_CLIENT_ID env var required for M365 SDK.", err=True)
                    raise typer.Exit(1)

                if not m365_tenant_id:
                    typer.echo("Error: --tenant-id or AZURE_TENANT_ID env var required for M365 SDK.", err=True)
                    raise typer.Exit(1)

                # Get agent's schema name from bot data
                bot = client.get_bot(agent_id)
                agent_schema_name = bot.get("schemaname")
                if not agent_schema_name:
                    typer.echo(f"Error: Could not get schema name for agent {agent_id}", err=True)
                    raise typer.Exit(1)

                if verbose:
                    typer.echo(f"  Environment ID: {m365_environment_id[:20]}...")
                    typer.echo(f"  Agent Schema: {agent_schema_name}")
                    typer.echo(f"  Client ID: {m365_client_id[:8]}...")
                    typer.echo(f"  Tenant ID: {m365_tenant_id[:8]}...")

                # Create connection settings.
                # Derive the Power Platform cloud from the Dataverse environment
                # host so commercial tenants resolve to the public cloud with no
                # config, and sovereign clouds map to their SDK enum. An explicit
                # base-address override is honored for private/unlisted clouds.
                cloud_override = os.environ.get(POWERPLATFORM_CLOUD_ENV)
                try:
                    cloud_setting, custom_cloud_base = resolve_power_platform_cloud(
                        config.dataverse_url,
                        override=cloud_override,
                    )
                except ValueError as cloud_err:
                    typer.echo(f"Error: {cloud_err}", err=True)
                    raise typer.Exit(1)

                settings = ConnectionSettings(
                    environment_id=m365_environment_id,
                    agent_identifier=agent_schema_name,
                    cloud=cloud_setting,
                    copilot_agent_type=None,
                    custom_power_platform_cloud=custom_cloud_base,
                )

                if verbose:
                    if custom_cloud_base:
                        typer.echo(f"  Power Platform cloud: Other ({custom_cloud_base})")
                    elif cloud_setting is not None:
                        typer.echo(f"  Power Platform cloud: {cloud_setting.value}")
                    else:
                        typer.echo("  Power Platform cloud: Public (api.powerplatform.com)")

                # Acquire token using MSAL device code flow
                if verbose:
                    typer.echo("Acquiring token via MSAL...")

                # Persistent token cache under the user's home dir
                cache_file = _token_cache_path(".m365-token-cache.json")
                cache = msal.SerializableTokenCache()

                if cache_file.exists():
                    try:
                        cache.deserialize(cache_file.read_text())
                        if verbose:
                            typer.echo(f"Loaded token cache from {cache_file}")
                    except Exception:
                        pass  # Ignore cache load errors

                pca = msal.PublicClientApplication(
                    client_id=m365_client_id,
                    authority=f"https://login.microsoftonline.com/{m365_tenant_id}",
                    token_cache=cache,
                )

                token_scopes = ["https://api.powerplatform.com/.default"]
                access_token = None
                m365_used_service_principal = False

                # Check for service principal credentials (client secret) for non-interactive auth
                from ..config import get_config as _get_copilot_config
                _cfg = _get_copilot_config()
                m365_client_secret = (
                    _cfg._get("M365_SDK_CLIENT_SECRET")
                    or _cfg._get("AZURE_CLIENT_SECRET")
                )
                if m365_client_secret:
                    m365_used_service_principal = True
                    if verbose:
                        typer.echo("Using service principal (client credentials) authentication...")
                    cca = msal.ConfidentialClientApplication(
                        client_id=m365_client_id,
                        client_credential=m365_client_secret,
                        authority=f"https://login.microsoftonline.com/{m365_tenant_id}",
                    )
                    result = cca.acquire_token_for_client(scopes=token_scopes)
                    if "access_token" in result:
                        access_token = result["access_token"]
                        if verbose:
                            typer.echo("Token acquired via service principal.")
                    else:
                        error_msg = result.get("error_description", result.get("error", "Unknown"))
                        typer.echo(f"Error: Service principal auth failed: {error_msg}", err=True)
                        typer.echo("Check M365_SDK_CLIENT_SECRET and ensure admin consent is granted.", err=True)
                        raise typer.Exit(1)

                # Try silent token acquisition from user cache (device code flow)
                accounts = pca.get_accounts()
                if not access_token and accounts:
                    if verbose:
                        typer.echo("Found cached account, attempting silent token acquisition...")
                    result = pca.acquire_token_silent(token_scopes, account=accounts[0])
                    if result and "access_token" in result:
                        access_token = result["access_token"]
                        if verbose:
                            typer.echo("Token acquired from cache.")

                # Fall back to device code flow if needed
                if not access_token:
                    if verbose:
                        typer.echo("Initiating device code flow...")

                    flow = pca.initiate_device_flow(scopes=token_scopes)
                    if "user_code" not in flow:
                        typer.echo(f"Error: Failed to initiate device flow: {flow.get('error_description', 'Unknown error')}", err=True)
                        raise typer.Exit(1)

                    # Display device code message to user
                    typer.echo("")
                    typer.echo(flow["message"])
                    typer.echo("")

                    # Wait for user to complete authentication
                    result = pca.acquire_token_by_device_flow(flow)

                    if "error" in result:
                        typer.echo(f"Error: Authentication failed: {result.get('error_description', result.get('error'))}", err=True)
                        raise typer.Exit(1)

                    access_token = result["access_token"]
                    if verbose:
                        typer.echo("Authentication successful!")

                # Save token cache if it changed
                if cache.has_state_changed:
                    try:
                        cache_file.write_text(cache.serialize())
                        if verbose:
                            typer.echo(f"Saved token cache to {cache_file}")
                    except Exception as e:
                        if verbose:
                            typer.echo(f"Warning: Could not save token cache: {e}", err=True)

                if not access_token:
                    typer.echo("Error: Failed to acquire access token", err=True)
                    raise typer.Exit(1)

                # Create Copilot client and send message
                copilot_client = CopilotClient(settings, access_token)

                async def prompt_with_m365_sdk():
                    """Send prompt and collect response using M365 SDK."""
                    # Start conversation - this sets _current_conversation_id via x-ms-conversationid header
                    if verbose:
                        typer.echo("Starting conversation...")

                    async for activity in copilot_client.start_conversation(emit_start_conversation_event=True):
                        if verbose:
                            typer.echo(f"Start activity type: {activity.type}")
                        # Process all start activities - the SDK sets conversation ID from response header
                        if copilot_client._current_conversation_id:
                            if verbose:
                                typer.echo(f"Conversation ID set: {copilot_client._current_conversation_id}")
                            break

                    if not copilot_client._current_conversation_id:
                        raise Exception("Failed to obtain conversation ID from server")

                    # Now send the actual message
                    if verbose:
                        typer.echo(f"Sending message: \"{message}\"")

                    responses = []
                    replies = copilot_client.ask_question(message)

                    async for reply in replies:
                        if verbose:
                            typer.echo(f"Reply activity type: {reply.type}")
                        if reply.type == ActivityTypes.message and reply.text:
                            responses.append(reply.text)

                    return "\n".join(responses) if responses else None

                try:
                    bot_response = asyncio.run(prompt_with_m365_sdk())
                except Exception as sdk_error:
                    typer.echo(f"Error: M365 SDK request failed: {sdk_error}", err=True)
                    # A 405 on the Direct-to-Engine conversations endpoint while
                    # using app-only (service principal) auth means the
                    # environment rejects app-only S2S calls. The server body is
                    # "App-only S2S access is not enabled for this environment."
                    if m365_used_service_principal and "405" in str(sdk_error):
                        typer.echo(
                            "Cause: the environment does not allow app-only "
                            "(service principal) access for Copilot Studio "
                            "conversations.",
                            err=True,
                        )
                        typer.echo(
                            "Fix: use delegated (user) auth by removing the "
                            "service-principal secret from the active profile so "
                            "the device-code flow runs, or have an admin enable "
                            "app-only S2S access for this environment.",
                            err=True,
                        )
                    raise typer.Exit(1)

                if not bot_response:
                    typer.echo("Error: No response received from agent", err=True)
                    raise typer.Exit(1)

                # Output the response
                if table:
                    if verbose:
                        typer.echo(f"Response (via M365 Agents SDK):")
                        typer.echo("")
                    typer.echo(bot_response)
                else:
                    result = {
                        "success": True,
                        "response": bot_response,
                        "authMode": "integrated",
                        "sdk": "m365-agents",
                    }
                    print_json(result)

                return  # Exit early - M365 SDK flow complete
        except typer.Exit:
            raise  # Re-raise Exit exceptions
        except Exception as auth_check_error:
            # If we can't check auth mode, continue anyway - the Direct Line call will fail with a clear error
            if verbose:
                typer.echo(f"Warning: Could not verify agent authentication mode: {auth_check_error}", err=True)

        # Determine authentication method
        directline_token = None
        user_id = f"copilot-cli-{int(time.time())}"

        if entra_id:
            # Entra ID authentication flow
            entra_client_id = client_id or os.environ.get("ENTRA_CLIENT_ID")
            entra_tenant_id = tenant_id or os.environ.get("ENTRA_TENANT_ID")
            # Default to Power Platform API scope with CopilotStudio.Copilots.Invoke permission
            entra_scope = scope or os.environ.get("ENTRA_SCOPE") or "https://api.powerplatform.com/.default"
            agent_token_endpoint = token_endpoint or os.environ.get("AGENT_TOKEN_ENDPOINT") or os.environ.get("BOT_TOKEN_ENDPOINT")

            if not entra_client_id:
                typer.echo("Error: --client-id or ENTRA_CLIENT_ID env var required for Entra ID auth", err=True)
                raise typer.Exit(1)
            if not entra_tenant_id:
                typer.echo("Error: --tenant-id or ENTRA_TENANT_ID env var required for Entra ID auth", err=True)
                raise typer.Exit(1)
            if not agent_token_endpoint:
                typer.echo("Error: --token-endpoint or AGENT_TOKEN_ENDPOINT env var required for Entra ID auth", err=True)
                typer.echo("Get endpoint from: Copilot Studio > Channels > Mobile app > Token Endpoint", err=True)
                raise typer.Exit(1)

            if verbose:
                typer.echo("Using Entra ID authentication...")
                typer.echo(f"  Client ID: {entra_client_id[:8]}...")
                typer.echo(f"  Tenant ID: {entra_tenant_id[:8]}...")
                typer.echo(f"  Scope: {entra_scope}")

            # Step 1: Acquire access token using MSAL device code flow
            try:
                import msal
            except ImportError:
                typer.echo("Error: msal package required for Entra ID auth. Install with: pip install msal", err=True)
                raise typer.Exit(1)

            # Persistent token cache under the user's home dir
            cache_file = _token_cache_path(".token-cache.json")
            cache = msal.SerializableTokenCache()

            if cache_file.exists():
                try:
                    cache.deserialize(cache_file.read_text())
                    if verbose:
                        typer.echo(f"Loaded token cache from {cache_file}")
                except Exception:
                    pass  # Ignore cache load errors

            authority = f"https://login.microsoftonline.com/{entra_tenant_id}"
            app = msal.PublicClientApplication(
                client_id=entra_client_id,
                authority=authority,
                token_cache=cache,
            )

            # Check cache for existing tokens
            accounts = app.get_accounts()
            access_token = None

            if accounts:
                if verbose:
                    typer.echo("Found cached account, attempting silent token acquisition...")
                result = app.acquire_token_silent(scopes=[entra_scope], account=accounts[0])
                if result and "access_token" in result:
                    access_token = result["access_token"]
                    if verbose:
                        typer.echo("Token acquired from cache.")

            if not access_token:
                # Initiate device code flow
                if verbose:
                    typer.echo("Initiating device code flow...")

                flow = app.initiate_device_flow(scopes=[entra_scope])
                if "user_code" not in flow:
                    typer.echo(f"Error: Failed to initiate device flow: {flow.get('error_description', 'Unknown error')}", err=True)
                    raise typer.Exit(1)

                # Display device code message to user
                typer.echo("")
                typer.echo(flow["message"])
                typer.echo("")

                # Wait for user to complete authentication
                result = app.acquire_token_by_device_flow(flow)

                if "error" in result:
                    typer.echo(f"Error: Authentication failed: {result.get('error_description', result.get('error'))}", err=True)
                    raise typer.Exit(1)

                access_token = result["access_token"]
                if verbose:
                    typer.echo("Authentication successful!")

            # Save token cache if it changed
            if cache.has_state_changed:
                try:
                    cache_file.write_text(cache.serialize())
                    if verbose:
                        typer.echo(f"Saved token cache to {cache_file}")
                except Exception as e:
                    if verbose:
                        typer.echo(f"Warning: Could not save token cache: {e}", err=True)

            # Step 2: Exchange Entra ID token for Direct Line token
            # The token endpoint returns a Direct Line token when called with Bearer auth
            if verbose:
                typer.echo("Exchanging Entra ID token for Direct Line token...")

            with httpx.Client(timeout=30.0) as token_client:
                token_response = token_client.get(
                    agent_token_endpoint,
                    headers={"Authorization": f"Bearer {access_token}"},
                )

                if verbose:
                    typer.echo(f"Token endpoint response: HTTP {token_response.status_code}")

                if token_response.status_code != 200:
                    typer.echo(f"Error: Failed to get Direct Line token (HTTP {token_response.status_code})", err=True)
                    if verbose:
                        typer.echo(f"Response: {token_response.text}", err=True)
                    raise typer.Exit(1)

                token_data = token_response.json()
                directline_token = token_data.get("token")

                if not directline_token:
                    typer.echo("Error: No token in response", err=True)
                    if verbose:
                        typer.echo(f"Response: {token_data}", err=True)
                    raise typer.Exit(1)

                if verbose:
                    typer.echo("Direct Line token obtained successfully!")

        else:
            # Direct Line secret authentication (original flow)
            from ..config import get_config as _get_copilot_config
            directline_secret = secret or _get_copilot_config()._get("DIRECTLINE_SECRET")
            if directline_secret:
                directline_token = directline_secret
            else:
                # Auto-retrieve Direct Line token via PVA Studio API
                if verbose:
                    typer.echo("No --secret provided. Auto-retrieving Direct Line token...")
                try:
                    bot = client.get_bot(agent_id)
                    schema_name = bot.get("schemaname")
                    if not schema_name:
                        typer.echo(f"Error: Could not get schema name for agent {agent_id}", err=True)
                        raise typer.Exit(1)

                    token_data = client.get_directline_token(schema_name)
                    directline_token = token_data.get("token")

                    if not directline_token:
                        typer.echo("Error: No token returned from Direct Line token endpoint", err=True)
                        raise typer.Exit(1)

                    if verbose:
                        typer.echo("Direct Line token obtained successfully!")
                except typer.Exit:
                    raise
                except Exception as token_err:
                    typer.echo(f"Error: Failed to auto-retrieve Direct Line token: {token_err}", err=True)
                    typer.echo(
                        "Provide a secret manually via --secret or DIRECTLINE_SECRET env var.",
                        err=True,
                    )
                    typer.echo(
                        "Get secret from: Copilot Studio > Settings > Channels > Direct Line",
                        err=True,
                    )
                    raise typer.Exit(1)

        # Handle file attachment (upload via Direct Line upload endpoint)
        file_to_upload = None
        if file:
            file_path = Path(file)
            if not file_path.exists():
                typer.echo(f"Error: File not found: {file}", err=True)
                raise typer.Exit(1)

            file_name = file_path.name
            ext = file_path.suffix.lower()

            # Map file extensions to MIME types
            mime_types = {
                ".txt": "text/plain",
                ".md": "text/markdown",
                ".json": "application/json",
                ".xml": "application/xml",
                ".html": "text/html",
                ".csv": "text/csv",
                ".yaml": "application/x-yaml",
                ".yml": "application/x-yaml",
                ".pdf": "application/pdf",
                ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ".doc": "application/msword",
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".gif": "image/gif",
            }

            content_type = mime_types.get(ext)
            if not content_type:
                typer.echo(f"Error: Unsupported file type: {ext}", err=True)
                typer.echo(f"Supported types: {', '.join(mime_types.keys())}", err=True)
                raise typer.Exit(1)

            # Read file content
            try:
                with open(file_path, "rb") as f:
                    file_content = f.read()
                file_to_upload = {
                    "name": file_name,
                    "content": file_content,
                    "content_type": content_type,
                }
                if verbose:
                    typer.echo(f"Prepared file for upload: {file_name} ({len(file_content)} bytes, {content_type})")
            except IOError as e:
                typer.echo(f"Error reading file: {e}", err=True)
                raise typer.Exit(1)

        # Start conversation via Direct Line API
        if verbose:
            typer.echo(f"Starting conversation with agent {agent_id}...")

        with httpx.Client(timeout=30.0) as client:
            conv_response = client.post(
                f"{DIRECTLINE_URL}/conversations",
                headers={
                    "Authorization": f"Bearer {directline_token}",
                    "Content-Type": "application/json",
                },
            )

            if conv_response.status_code == 403:
                typer.echo("Error: Authentication failed (HTTP 403)", err=True)
                if entra_id:
                    typer.echo("Check that the Entra ID token exchange was successful", err=True)
                else:
                    typer.echo("Check that the Direct Line secret is valid and not expired", err=True)
                raise typer.Exit(1)

            if conv_response.status_code != 201:
                typer.echo(f"Error: Failed to start conversation (HTTP {conv_response.status_code})", err=True)
                if verbose:
                    typer.echo(f"Response: {conv_response.text}", err=True)
                raise typer.Exit(1)

            conv_data = conv_response.json()
            conv_id = conv_data.get("conversationId")

            if not conv_id:
                typer.echo("Error: No conversation ID in response", err=True)
                raise typer.Exit(1)

            if verbose:
                typer.echo(f"Conversation started: {conv_id}")

            # Step 4: Send message (with file upload if applicable)
            if verbose:
                typer.echo(f"Sending message: \"{message}\"")

            if file_to_upload:
                # Use Direct Line upload endpoint for file attachments
                # This uses multipart/form-data with the activity and file
                import json as json_module

                activity_json = json_module.dumps({
                    "type": "message",
                    "from": {"id": user_id, "name": "Copilot CLI"},
                    "text": message,
                })

                # Build multipart form data
                files = {
                    "activity": (None, activity_json, "application/vnd.microsoft.activity"),
                    "file": (file_to_upload["name"], file_to_upload["content"], file_to_upload["content_type"]),
                }

                if verbose:
                    typer.echo(f"Uploading file via Direct Line: {file_to_upload['name']}")

                send_response = client.post(
                    f"{DIRECTLINE_URL}/conversations/{conv_id}/upload?userId={user_id}",
                    headers={
                        "Authorization": f"Bearer {directline_token}",
                    },
                    files=files,
                )
            else:
                # Standard message without file
                send_payload = {
                    "type": "message",
                    "from": {"id": user_id, "name": "Copilot CLI"},
                    "text": message,
                }

                send_response = client.post(
                    f"{DIRECTLINE_URL}/conversations/{conv_id}/activities",
                    headers={
                        "Authorization": f"Bearer {directline_token}",
                        "Content-Type": "application/json",
                    },
                    json=send_payload,
                )

            if send_response.status_code not in (200, 201, 204):
                typer.echo(f"Error: Failed to send message (HTTP {send_response.status_code})", err=True)
                if verbose:
                    typer.echo(f"Response: {send_response.text}", err=True)
                raise typer.Exit(1)

            activity_id = send_response.json().get("id") if send_response.text else None
            if verbose:
                typer.echo(f"Message sent (Activity ID: {activity_id})")

            # Step 5: Poll for response
            if verbose:
                typer.echo(f"Polling for response (max {max_polls} attempts, {poll_interval}s interval)...")

            bot_response = None
            bot_from = None
            watermark = None
            poll_count = 0
            start_time = time.time()

            while bot_response is None and poll_count < max_polls:
                # Check timeout
                if time.time() - start_time > timeout:
                    typer.echo(f"Error: Timeout after {timeout} seconds", err=True)
                    raise typer.Exit(1)

                poll_count += 1
                time.sleep(poll_interval)

                # Build URL with watermark
                activities_url = f"{DIRECTLINE_URL}/conversations/{conv_id}/activities"
                if watermark:
                    activities_url = f"{activities_url}?watermark={watermark}"

                activities_response = client.get(
                    activities_url,
                    headers={"Authorization": f"Bearer {directline_token}"},
                )

                if activities_response.status_code != 200:
                    if verbose:
                        typer.echo(f"Warning: Poll failed (HTTP {activities_response.status_code})", err=True)
                    continue

                activities_data = activities_response.json()
                watermark = activities_data.get("watermark")

                # Find bot messages (exclude our user messages)
                activities = activities_data.get("activities", [])
                bot_messages = [
                    a for a in activities
                    if a.get("type") == "message" and a.get("from", {}).get("id") != user_id
                ]

                if bot_messages:
                    # Get the last bot message
                    last_message = bot_messages[-1]
                    bot_response = last_message.get("text", "")
                    bot_from = last_message.get("from", {}).get("name") or last_message.get("from", {}).get("id")

                if verbose and not bot_response:
                    typer.echo(f"  Polling... attempt {poll_count}/{max_polls}", nl=False)
                    typer.echo("\r", nl=False)

            if verbose:
                typer.echo("")  # Clear the polling line

            if not bot_response:
                typer.echo(f"Error: No response received after {poll_count} polling attempts", err=True)
                typer.echo("Possible causes:", err=True)
                typer.echo("  - Agent is not published", err=True)
                typer.echo("  - Agent is experiencing errors (check Copilot Studio)", err=True)
                typer.echo("  - Direct Line channel is not enabled", err=True)
                raise typer.Exit(1)

            # Check for error responses
            is_error = any(phrase in bot_response for phrase in [
                "something unexpected happened",
                "Error code:",
                "InvalidContent",
                "We're looking into it",
            ])

            # Output the response
            if table:
                if verbose:
                    typer.echo(f"Response from {bot_from} (after {poll_count} poll(s)):")
                    typer.echo("")

                typer.echo(bot_response)

                if is_error:
                    typer.echo("")
                    typer.echo("Warning: Agent returned an error response", err=True)
                    raise typer.Exit(1)
            else:
                result = {
                    "success": not is_error,
                    "response": bot_response,
                    "conversationId": conv_id,
                    "pollCount": poll_count,
                    "respondent": bot_from,
                }
                if is_error:
                    result["error"] = True
                print_json(result)

    except httpx.TimeoutException:
        typer.echo("Error: Request timed out", err=True)
        raise typer.Exit(1)
    except httpx.RequestError as e:
        typer.echo(f"Error: Request failed: {e}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        if isinstance(e, typer.Exit):
            raise
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


# Knowledge source commands as a subgroup
# Usage: copilot agent knowledge list --agent <agent-id>
#        copilot agent knowledge file add --agent <agent-id> ...
#        copilot agent knowledge azure-ai-search add --agent <agent-id> ...

knowledge_app = typer.Typer(help="Manage knowledge sources for an agent")

# Component type mapping
COMPONENT_TYPE_NAMES = {
    14: "file",
    16: "azure-ai-search",
}


def format_knowledge_source(source: dict) -> dict:
    """Format a knowledge source for display."""
    component_type = source.get("componenttype", 14)
    type_name = COMPONENT_TYPE_NAMES.get(component_type, f"unknown({component_type})")
    return {
        "name": source.get("name"),
        "type": type_name,
        "component_id": source.get("botcomponentid"),
        "description": source.get("description"),
    }


@knowledge_app.command("list")
def knowledge_list(
    agent_id: Optional[str] = typer.Argument(
        None,
        help="The agent's unique identifier (GUID)",
    ),
    agent_id_option: Optional[str] = typer.Option(
        None,
        "--agentId",
        "-a",
        help="The agent's unique identifier (GUID) [alternative to positional arg]",
    ),
    source_type: Optional[str] = typer.Option(
        None,
        "--type",
        help="Filter by type: 'file' or 'connector'",
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
    List knowledge sources for an agent.

    Examples:
        copilot agent knowledge list <agent-id>
        copilot agent knowledge list <agent-id> --table
        copilot agent knowledge list --agentId <agent-id> --type file
    """
    # Support both positional argument and --agentId option
    resolved_agent_id = agent_id or agent_id_option
    if not resolved_agent_id:
        typer.echo("Error: Agent ID is required. Provide it as a positional argument or use --agentId.", err=True)
        raise typer.Exit(2)
    try:
        client = get_client()
        sources = client.list_knowledge_sources(resolved_agent_id, source_type=source_type)

        if not sources:
            typer.echo("No knowledge sources found for this agent.")
            return

        formatted = [format_knowledge_source(s) for s in sources]

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
                columns=["name", "type", "component_id", "description"],
                headers=["Name", "Type", "Component ID", "Description"],
            )
        else:
            print_json(formatted)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@knowledge_app.command("remove")
def knowledge_remove(
    component_id: str = typer.Argument(..., help="The knowledge source component's unique identifier (GUID)"),
    disassociate: bool = typer.Option(
        False,
        "--disassociate",
        "-d",
        help="Only remove association with agent (keep knowledge source)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Skip confirmation prompt",
    ),
):
    """
    Remove a knowledge source from an agent.

    By default, this DELETES the knowledge source entirely. Use --disassociate
    to only remove the association while keeping the knowledge source.

    Examples:
        copilot agent knowledge remove <component-id>              # Delete knowledge
        copilot agent knowledge remove <component-id> --disassociate  # Keep knowledge, remove from agent
        copilot agent knowledge remove <component-id> --force
    """
    try:
        if disassociate:
            action = "disassociate"
            prompt = "Remove this knowledge source from its agent (keeping the file)?"
        else:
            action = "delete"
            prompt = "Permanently DELETE this knowledge source?"

        if not force:
            confirm = typer.confirm(prompt)
            if not confirm:
                typer.echo("Aborted.")
                raise typer.Exit(0)

        client = get_client()
        if disassociate:
            client.disassociate_knowledge_from_agent(component_id)
            print_success("Knowledge source disassociated from agent.")
        else:
            client.remove_knowledge_source(component_id)
            print_success("Knowledge source deleted successfully.")
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@knowledge_app.command("add")
def knowledge_add(
    agent_id: Optional[str] = typer.Argument(
        None,
        help="The agent's unique identifier (GUID)",
    ),
    agent_id_option: Optional[str] = typer.Option(
        None,
        "--agentId",
        "-a",
        help="The agent's unique identifier (GUID) [alternative to positional arg]",
    ),
    component_id: str = typer.Option(
        ...,
        "--component",
        "-c",
        help="The knowledge source component ID to associate",
    ),
):
    """
    Associate an existing knowledge source with an agent.

    Note: Knowledge sources in Copilot Studio are per-agent. Use 'upload'
    to create new knowledge sources for an agent.

    Examples:
        copilot agent knowledge add <agent-id> --component <component-id>
        copilot agent knowledge add <agent-id> -c <component-id>
        copilot agent knowledge add --agentId <agent-id> --component <component-id>
    """
    # Support both positional argument and --agentId option
    resolved_agent_id = agent_id or agent_id_option
    if not resolved_agent_id:
        typer.echo("Error: Agent ID is required. Provide it as a positional argument or use --agentId.", err=True)
        raise typer.Exit(2)

    try:
        client = get_client()
        client.associate_knowledge_with_agent(resolved_agent_id, component_id)
        print_success(f"Knowledge source associated with agent successfully.")
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@knowledge_app.command("upload")
def knowledge_upload(
    agent_id: Optional[str] = typer.Argument(
        None,
        help="The agent's unique identifier (GUID)",
    ),
    agent_id_option: Optional[str] = typer.Option(
        None,
        "--agentId",
        "-a",
        help="The agent's unique identifier (GUID) [alternative to positional arg]",
    ),
    file_path: str = typer.Option(
        ...,
        "--file",
        "-f",
        help="Path to the binary file to upload (e.g., .docx, .pdf)",
    ),
    name: str = typer.Option(
        ...,
        "--name",
        "-n",
        help="Display name for the knowledge source",
    ),
    description: Optional[str] = typer.Option(
        None,
        "--description",
        "-d",
        help="Description for the knowledge source (auto-generated if not provided)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-F",
        help="Replace existing knowledge source with the same name",
    ),
):
    """
    Upload a file as a knowledge source for an agent.

    Creates a botcomponent record and uploads the file. Knowledge sources
    in Copilot Studio are per-agent (not shared across agents).

    If a knowledge source with the same name already exists, use --force to replace it.

    Examples:
        copilot agent knowledge upload <agent-id> --file ./guide.docx --name "Style Guide"
        copilot agent knowledge upload <agent-id> -f ./manual.pdf -n "Product Manual"
        copilot agent knowledge upload --agentId <agent-id> -f ./guide.docx -n "Style Guide" --force
    """
    # Support both positional argument and --agentId option
    resolved_agent_id = agent_id or agent_id_option
    if not resolved_agent_id:
        typer.echo("Error: Agent ID is required. Provide it as a positional argument or use --agentId.", err=True)
        raise typer.Exit(2)

    try:
        # Validate file exists
        if not os.path.exists(file_path):
            print_error(f"File not found: {file_path}")
            raise typer.Exit(1)

        file_info = Path(file_path)
        file_size = file_info.stat().st_size

        # Get MIME type
        mime_type, _ = mimetypes.guess_type(file_path)
        if not mime_type:
            mime_type = "application/octet-stream"

        client = get_client()

        # Check if a knowledge source with this name already exists for the agent
        existing_sources = client.list_knowledge_sources(resolved_agent_id, source_type="file")
        existing_source = next(
            (s for s in existing_sources if s.get("name") == name),
            None
        )

        if existing_source:
            existing_id = existing_source.get("botcomponentid")
            if force:
                # Delete the existing knowledge source first
                print_warning(f"Replacing existing knowledge source '{name}' (ID: {existing_id})")
                client.delete(f"botcomponents({existing_id})")
            else:
                print_error(
                    f"A knowledge source named '{name}' already exists for this agent "
                    f"(ID: {existing_id}). Use --force to replace it."
                )
                raise typer.Exit(1)

        # Step 1: Create the botcomponent record
        component_id = client.create_file_knowledge_component(
            name=name,
            file_name=file_info.name,
            bot_id=resolved_agent_id,
            description=description,
        )

        if not component_id:
            print_error("Failed to create knowledge component record")
            raise typer.Exit(1)

        # Step 2: Upload the file to the filedata column
        try:
            with open(file_path, "rb") as f:
                file_data = f.read()

            # Use single request for files < 128MB, chunked for larger
            if file_size < 128 * 1024 * 1024:
                client.upload_file_single(
                    table="botcomponents",
                    record_id=component_id,
                    column="filedata",
                    file_name=file_info.name,
                    file_data=file_data,
                    mime_type=mime_type,
                )
            else:
                client.upload_file_chunked(
                    table="botcomponents",
                    record_id=component_id,
                    column="filedata",
                    file_name=file_info.name,
                    file_data=file_data,
                    mime_type=mime_type,
                )

            action = "replaced" if existing_source else "uploaded"
            print_success(f"Knowledge file '{name}' {action} successfully.")
            print_json({
                "componentId": component_id,
                "name": name,
                "fileName": file_info.name,
                "fileSize": file_size,
                "mimeType": mime_type,
                "agentId": resolved_agent_id,
                "replaced": existing_source is not None,
            })

        except Exception as upload_error:
            # If file upload fails, clean up the component record
            print_warning(f"File upload failed, cleaning up component: {upload_error}")
            try:
                client.delete(f"botcomponents({component_id})")
            except Exception:
                pass
            raise upload_error

    except Exception as e:
        if isinstance(e, typer.Exit):
            raise
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@knowledge_app.command("get")
def knowledge_get(
    component_id: str = typer.Argument(
        ...,
        help="The knowledge source component's unique identifier (GUID)",
    ),
):
    """
    Get details of a specific knowledge source.

    Examples:
        copilot agent knowledge get <component-id>
    """
    try:
        client = get_client()
        component = client.get(f"botcomponents({component_id})")

        if not component:
            print_error(f"Knowledge source not found: {component_id}")
            raise typer.Exit(1)

        print_json(component)
    except Exception as e:
        if isinstance(e, typer.Exit):
            raise
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@knowledge_app.command("download")
def knowledge_download(
    component_id: str = typer.Argument(
        ...,
        help="The knowledge source component's unique identifier (GUID)",
    ),
    output_path: Optional[str] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output file path (defaults to original filename in current directory)",
    ),
):
    """
    Download a knowledge source file.

    Examples:
        copilot agent knowledge download <component-id>
        copilot agent knowledge download <component-id> --output ./downloaded.docx
    """
    try:
        client = get_client()

        # Get component to find the filename
        component = client.get(f"botcomponents({component_id})?$select=name,filedata_name")
        if not component:
            print_error(f"Knowledge source not found: {component_id}")
            raise typer.Exit(1)

        file_name = component.get("filedata_name") or f"{component.get('name', 'download')}"
        save_path = output_path or file_name

        # Download the file
        file_data = client.download_file(
            table="botcomponents",
            record_id=component_id,
            column="filedata",
        )

        with open(save_path, "wb") as f:
            f.write(file_data)

        print_success(f"File downloaded to: {save_path}")
        print_json({
            "componentId": component_id,
            "fileName": file_name,
            "savedTo": save_path,
            "fileSize": len(file_data),
        })

    except Exception as e:
        if isinstance(e, typer.Exit):
            raise
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


# Azure AI Search knowledge source subgroup
azure_search_app = typer.Typer(help="Manage Azure AI Search knowledge sources")


@azure_search_app.command("add")
def azure_search_add(
    agent_id: Optional[str] = typer.Argument(
        None,
        help="The agent's unique identifier (GUID)",
    ),
    agent_id_option: Optional[str] = typer.Option(
        None,
        "--agentId",
        "-a",
        help="The agent's unique identifier (GUID) [alternative to positional arg]",
    ),
    name: str = typer.Option(
        ...,
        "--name",
        "-n",
        help="Display name for the knowledge source",
    ),
    endpoint: str = typer.Option(
        ...,
        "--endpoint",
        "-e",
        help="Azure AI Search endpoint URL (e.g., https://mysearch.search.windows.net)",
    ),
    index: str = typer.Option(
        ...,
        "--index",
        "-i",
        help="Name of the Azure AI Search index",
    ),
    api_key: str = typer.Option(
        ...,
        "--api-key",
        "-k",
        help="Azure AI Search API key (admin or query key)",
    ),
    description: Optional[str] = typer.Option(
        None,
        "--description",
        "-d",
        help="Description for the knowledge source",
    ),
):
    """
    Add an Azure AI Search knowledge source to an agent (EXPERIMENTAL).

    WARNING: This command creates an agent component record but the knowledge source
    may not appear in Copilot Studio UI. Copilot Studio requires a Power Platform
    connection to be properly linked, which involves internal configuration not
    exposed via public APIs.

    RECOMMENDED APPROACH:
    1. Use 'copilot connection create' to create the Power Platform connection
    2. Link the connection to your agent via the Copilot Studio UI

    Examples:
        copilot agent knowledge azure-ai-search add <agent-id> \\
            --name "Product Docs" \\
            --endpoint https://mysearch.search.windows.net \\
            --index products-index \\
            --api-key <your-api-key>

        copilot agent knowledge azure-ai-search add --agentId <agent-id> \\
            --name "Product Docs" \\
            --endpoint https://mysearch.search.windows.net \\
            --index products-index \\
            --api-key <your-api-key>
    """
    # Support both positional argument and --agentId option
    resolved_agent_id = agent_id or agent_id_option
    if not resolved_agent_id:
        typer.echo("Error: Agent ID is required. Provide it as a positional argument or use --agentId.", err=True)
        raise typer.Exit(2)

    try:
        client = get_client()
        component_id = client.add_azure_ai_search_knowledge_source(
            bot_id=resolved_agent_id,
            name=name,
            search_endpoint=endpoint,
            search_index=index,
            api_key=api_key,
            description=description,
        )

        print_success(f"Azure AI Search knowledge source '{name}' added successfully.")
        if component_id:
            typer.echo(f"Component ID: {component_id}")
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


knowledge_app.add_typer(azure_search_app, name="azure-ai-search")


# Register knowledge subgroup
app.add_typer(knowledge_app, name="knowledge")




# =============================================================================
# Transcript Commands
# =============================================================================

transcript_app = typer.Typer(help="View conversation transcripts for troubleshooting")


def _is_guid(value: str) -> bool:
    """Check if a string looks like a GUID."""
    import re
    guid_pattern = r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
    return bool(re.match(guid_pattern, value))


@transcript_app.command("list")
def transcript_list(
    agent: Optional[str] = typer.Option(
        None,
        "--agent",
        "-a",
        help="Filter by agent name or ID",
    ),
    limit: int = typer.Option(
        100,
        "--limit",
        "-l",
        help="Maximum number of transcripts to return",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display output as a formatted table instead of JSON",
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
    List conversation transcripts.

    Shows recent conversation transcripts, optionally filtered by agent name or ID.

    Examples:
        copilot agent transcript list
        copilot agent transcript list --table
        copilot agent transcript list --agent "Writer Draft Reviewer" --limit 10
        copilot agent transcript list --agent 12345678-1234-1234-1234-123456789abc
    """
    try:
        client = get_client()

        # Determine if agent is an ID or name
        agent_id = None
        agent_name = None
        if agent:
            if _is_guid(agent):
                agent_id = agent
            else:
                agent_name = agent

        transcripts = client.list_transcripts(bot_id=agent_id, bot_name=agent_name, limit=limit)

        if not transcripts:
            if table:
                print_table([])
            else:
                print_json([])
            return

        formatted = [format_transcript_for_display(t) for t in transcripts]

        # Apply filters
        if filter:
            from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError
            try:
                validate_filters(filter)
                formatted = apply_filters(formatted, filter)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        # Apply properties filter
        if properties:
            property_list = [p.strip() for p in properties.split(",")]
            formatted = [{k: v for k, v in item.items() if k in property_list} for item in formatted]

        if table:
            print_table(
                formatted,
                columns=["id", "agent_name", "start_time"],
                headers=["ID", "Agent", "Start Time"],
            )
        else:
            print_json(formatted)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@transcript_app.command("get")
def transcript_get(
    transcript_id: str = typer.Argument(
        ...,
        help="The transcript's unique identifier (GUID)",
    ),
    pretty: bool = typer.Option(
        False,
        "--pretty",
        "-p",
        help="Output as formatted conversation instead of JSON",
    ),
):
    """
    Get full transcript content.

    By default, outputs JSON. Use --pretty for a formatted conversation view.

    Examples:
        copilot agent transcript get <transcript-id>
        copilot agent transcript get <transcript-id> --pretty
    """
    try:
        client = get_client()
        transcript = client.get_transcript(transcript_id)

        if not pretty:
            print_json(transcript)
            return

        # Pretty format the transcript
        name = transcript.get("name", "Unknown")
        # Get bot name from OData annotation, fall back to ID
        bot_name = transcript.get(
            "_bot_conversationtranscriptid_value@OData.Community.Display.V1.FormattedValue",
            transcript.get("_bot_conversationtranscriptid_value", "Unknown"),
        )
        start_time = transcript.get("conversationstarttime", "Unknown")
        if start_time:
            start_time = start_time.replace("T", " ").replace("Z", "")
        content = transcript.get("content", "")

        typer.echo(f"Transcript: {name}")
        typer.echo(f"Agent: {bot_name}")
        typer.echo(f"Started: {start_time}")
        typer.echo("")
        typer.echo("--- Conversation ---")
        typer.echo(format_transcript_content(content))

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


# Register transcript subgroup
app.add_typer(transcript_app, name="transcript")


# =============================================================================
# Topic Commands
# =============================================================================

topic_app = typer.Typer(help="Manage agent topics")

# Topic component type mapping
TOPIC_COMPONENT_TYPE_NAMES = {
    0: "Topic",
    9: "Topic (V2)",
}


def format_topic_for_display(topic: dict) -> dict:
    """Format a topic for display."""
    component_type = topic.get("componenttype", 0)
    type_name = TOPIC_COMPONENT_TYPE_NAMES.get(component_type, f"unknown({component_type})")

    return {
        "name": topic.get("name"),
        "component_type": type_name,
        "component_id": topic.get("botcomponentid"),
        "schema_name": topic.get("schemaname"),
        "status": topic.get("statecode@OData.Community.Display.V1.FormattedValue", "Active"),
    }


@topic_app.command("list")
def topic_list(
    agent_id: str = typer.Option(
        ...,
        "--agentId",
        "-a",
        help="The agent's unique identifier (GUID)",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display output as a formatted table instead of JSON",
    ),
    system: bool = typer.Option(
        False,
        "--system",
        "-s",
        help="List only system topics (built-in, managed)",
    ),
    custom: bool = typer.Option(
        False,
        "--custom",
        "-c",
        help="List only custom topics (user-created)",
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
    List topics for an agent.

    Examples:
        copilot agent topic list --agentId <agent-id>
        copilot agent topic list --agentId <agent-id> --table
        copilot agent topic list --agentId <agent-id> --system --table
        copilot agent topic list --agentId <agent-id> --custom --table
    """
    try:
        if system and custom:
            print_error("Cannot specify both --system and --custom")
            raise typer.Exit(1)

        client = get_client()
        topics = client.list_topics(agent_id, system_only=system, custom_only=custom)

        if not topics:
            filter_type = "system " if system else "custom " if custom else ""
            typer.echo(f"No {filter_type}topics found for this agent.")
            return

        formatted = [format_topic_for_display(t) for t in topics]

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
                columns=["name", "component_type", "status", "component_id"],
                headers=["Name", "Component Type", "Status", "Component ID"],
            )
        else:
            print_json(formatted)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@topic_app.command("enable")
def topic_enable(
    topic_id: str = typer.Argument(
        ...,
        help="The topic's component ID (GUID)",
    ),
):
    """
    Enable a topic.

    Sets the topic state to Active so it will be triggered during conversations.

    Examples:
        copilot agent topic enable <topic-id>
    """
    try:
        client = get_client()

        # Get topic name for confirmation message
        topic = client.get_topic(topic_id)
        topic_name = topic.get("name", topic_id)

        client.set_topic_state(topic_id, enabled=True)
        print_success(f"Topic '{topic_name}' enabled successfully.")
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@topic_app.command("delete")
@topic_app.command("remove")
def topic_delete(
    topic_id: str = typer.Argument(
        ...,
        help="The topic's component ID (GUID)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Skip confirmation prompt",
    ),
):
    """
    Delete a topic.

    Permanently removes the topic from the agent. This action cannot be undone.

    Examples:
        copilot agent topic delete <topic-id>
        copilot agent topic delete <topic-id> --force
    """
    try:
        client = get_client()

        # Get topic name for confirmation message
        topic = client.get_topic(topic_id)
        topic_name = topic.get("name", topic_id)

        if not force:
            confirm = typer.confirm(f"Are you sure you want to delete topic '{topic_name}'? This cannot be undone.")
            if not confirm:
                typer.echo("Aborted.")
                raise typer.Exit(0)

        client.delete(f"botcomponents({topic_id})")
        print_success(f"Topic '{topic_name}' deleted successfully.")
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@topic_app.command("disable")
def topic_disable(
    topic_id: str = typer.Argument(
        ...,
        help="The topic's component ID (GUID)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Skip confirmation prompt",
    ),
):
    """
    Disable a topic.

    Sets the topic state to Inactive so it will not be triggered during conversations.

    Examples:
        copilot agent topic disable <topic-id>
        copilot agent topic disable <topic-id> --force
    """
    try:
        client = get_client()

        # Get topic name for confirmation message
        topic = client.get_topic(topic_id)
        topic_name = topic.get("name", topic_id)

        if not force:
            confirm = typer.confirm(f"Are you sure you want to disable topic '{topic_name}'?")
            if not confirm:
                typer.echo("Aborted.")
                raise typer.Exit(0)

        client.set_topic_state(topic_id, enabled=False)
        print_success(f"Topic '{topic_name}' disabled successfully.")
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@topic_app.command("get")
def topic_get(
    topic_id: str = typer.Argument(
        ...,
        help="The topic's component ID (GUID)",
    ),
    yaml_output: bool = typer.Option(
        False,
        "--yaml",
        "-Y",
        help="Output topic content as YAML",
    ),
    output: str = typer.Option(
        None,
        "--output",
        "-o",
        help="Write YAML content to a file",
    ),
):
    """
    Get a topic by ID.

    Retrieves topic details including the YAML content that defines the conversation flow.

    Examples:
        copilot agent topic get <topic-id>
        copilot agent topic get <topic-id> --yaml
        copilot agent topic get <topic-id> --output my-topic.yaml
    """
    try:
        client = get_client()
        topic = client.get_topic(topic_id)

        content = topic.get("data", "")

        if output:
            # Write content to file
            with open(output, "w") as f:
                f.write(content)
            print_success(f"Topic content written to {output}")
        elif yaml_output:
            # Print just the YAML content
            if content:
                typer.echo(content)
            else:
                typer.echo("# No YAML content found for this topic")
        else:
            # Print full topic info as JSON
            print_json({
                "name": topic.get("name"),
                "component_id": topic.get("botcomponentid"),
                "schema_name": topic.get("schemaname"),
                "component_type": TOPIC_COMPONENT_TYPE_NAMES.get(topic.get("componenttype", 0), "unknown"),
                "status": topic.get("statecode@OData.Community.Display.V1.FormattedValue", "Active"),
                "is_managed": topic.get("ismanaged", False),
                "description": topic.get("description", ""),
                "content": content,
            })
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@topic_app.command("create")
def topic_create(
    agent_id: str = typer.Option(
        ...,
        "--agentId",
        "-a",
        help="The agent's unique identifier (GUID)",
    ),
    name: str = typer.Option(
        ...,
        "--name",
        "-n",
        help="Display name for the topic",
    ),
    file: str = typer.Option(
        None,
        "--file",
        "-f",
        help="Path to YAML file containing topic content",
    ),
    triggers: str = typer.Option(
        None,
        "--triggers",
        "-t",
        help="Comma-separated trigger phrases (for simple topics)",
    ),
    message: str = typer.Option(
        None,
        "--message",
        "-m",
        help="Response message (for simple topics)",
    ),
    description: str = typer.Option(
        None,
        "--description",
        "-d",
        help="Optional description for the topic",
    ),
):
    """
    Create a new topic for an agent.

    Topics can be created in two ways:
    1. From a YAML file with --file
    2. Using simple parameters (--triggers and --message) for basic topics

    Examples:
        # Create from YAML file
        copilot agent topic create --agentId <agent-id> --name "My Topic" --file topic.yaml

        # Create simple topic with triggers and message
        copilot agent topic create --agentId <agent-id> --name "Greeting" \\
            --triggers "hello,hi,hey there" --message "Hello! How can I help?"
    """
    try:
        client = get_client()

        # Determine topic content
        if file:
            # Read content from file
            try:
                with open(file, "r") as f:
                    content = f.read()
            except FileNotFoundError:
                print_error(f"File not found: {file}")
                raise typer.Exit(1)
            except Exception as e:
                print_error(f"Error reading file: {e}")
                raise typer.Exit(1)
        elif triggers and message:
            # Generate simple topic YAML
            trigger_list = [t.strip() for t in triggers.split(",")]
            content = client.generate_simple_topic_yaml(name, trigger_list, message)
        else:
            print_error("Must provide either --file or both --triggers and --message")
            raise typer.Exit(1)

        # Create the topic
        try:
            component_id = client.create_topic(
                bot_id=agent_id,
                name=name,
                content=content,
                description=description,
            )
        except ValueError as e:
            # Validation error - display the detailed error message
            print_error(str(e))
            raise typer.Exit(1)

        if component_id:
            print_success(f"Topic '{name}' created successfully.")
            typer.echo(f"Component ID: {component_id}")
        else:
            print_success(f"Topic '{name}' created successfully.")
    except typer.Exit:
        # Re-raise typer.Exit to avoid catching in generic Exception handler
        raise
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@topic_app.command("update")
def topic_update(
    topic_id: str = typer.Argument(
        ...,
        help="The topic's component ID (GUID)",
    ),
    name: str = typer.Option(
        None,
        "--name",
        "-n",
        help="New display name for the topic",
    ),
    file: str = typer.Option(
        None,
        "--file",
        "-f",
        help="Path to YAML file containing updated topic content",
    ),
    triggers: str = typer.Option(
        None,
        "--triggers",
        "-t",
        help="New comma-separated trigger phrases (replaces existing triggers)",
    ),
    message: str = typer.Option(
        None,
        "--message",
        "-m",
        help="New response message (replaces existing message)",
    ),
    description: str = typer.Option(
        None,
        "--description",
        "-d",
        help="New description for the topic",
    ),
):
    """
    Update an existing topic.

    You can update a topic's name, content, or description.
    Content can be updated from a YAML file or using simple parameters.

    Examples:
        # Update from YAML file
        copilot agent topic update <topic-id> --file updated-topic.yaml

        # Update topic name
        copilot agent topic update <topic-id> --name "New Name"

        # Update triggers and message
        copilot agent topic update <topic-id> --triggers "new phrase,another" --message "New response"

        # Update multiple fields
        copilot agent topic update <topic-id> --name "New Name" --description "Updated description"
    """
    try:
        client = get_client()

        # Get current topic for name and validation
        current_topic = client.get_topic(topic_id)
        topic_name = current_topic.get("name", topic_id)

        # Check if this is a system topic
        if current_topic.get("ismanaged", False):
            print_error(f"Cannot update system topic '{topic_name}'. System topics are read-only.")
            raise typer.Exit(1)

        # Determine content update
        content = None
        if file:
            # Read content from file
            try:
                with open(file, "r") as f:
                    content = f.read()
            except FileNotFoundError:
                print_error(f"File not found: {file}")
                raise typer.Exit(1)
            except Exception as e:
                print_error(f"Error reading file: {e}")
                raise typer.Exit(1)
        elif triggers or message:
            if not (triggers and message):
                print_error("When updating triggers/message, both --triggers and --message must be provided")
                raise typer.Exit(1)
            # Generate new simple topic YAML
            display_name = name or topic_name
            trigger_list = [t.strip() for t in triggers.split(",")]
            content = client.generate_simple_topic_yaml(display_name, trigger_list, message)

        # Check if any updates provided
        if not any([name, content, description]):
            print_error("No updates provided. Specify at least one field to update.")
            raise typer.Exit(1)

        # Update the topic
        try:
            client.update_topic(
                component_id=topic_id,
                name=name,
                content=content,
                description=description,
            )
        except ValueError as e:
            # Validation error - display the detailed error message
            print_error(str(e))
            raise typer.Exit(1)

        print_success(f"Topic '{topic_name}' updated successfully.")
    except typer.Exit:
        # Re-raise typer.Exit to avoid catching in generic Exception handler
        raise
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


# Register topic subgroup
app.add_typer(topic_app, name="topic")


# =============================================================================
# Trigger Commands (External Triggers)
# =============================================================================

trigger_app = typer.Typer(help="Manage agent triggers (external event triggers)")


def format_trigger_for_display(trigger: dict) -> dict:
    """Format a trigger for display."""
    import yaml as yaml_lib

    # Parse the data field to extract trigger type info
    data = trigger.get("data", "") or ""
    trigger_type = "External"
    flow_id = None

    if data:
        try:
            parsed = yaml_lib.safe_load(data)
            source = parsed.get("externalTriggerSource", {})
            trigger_type = source.get("kind", "External").replace("ExternalTrigger", "")
            flow_id = source.get("flowId")
            # Try to get connection type from extensionData
            ext_data = parsed.get("extensionData", {})
            conn_type = ext_data.get("triggerConnectionType")
            if conn_type:
                trigger_type = conn_type
        except Exception:
            pass

    return {
        "name": trigger.get("name"),
        "trigger_type": trigger_type,
        "trigger_id": trigger.get("botcomponentid"),
        "flow_id": flow_id,
        "status": trigger.get("statecode@OData.Community.Display.V1.FormattedValue", "Active"),
    }


@trigger_app.command("list")
def trigger_list(
    agent_id: str = typer.Option(
        ...,
        "--agentId",
        "-a",
        help="The agent's unique identifier (GUID)",
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
    List external triggers for an agent.

    External triggers invoke the agent based on events like email arrival,
    scheduled times, or Dataverse row changes.

    Examples:
        copilot agent trigger list --agentId <agent-id>
        copilot agent trigger list --agentId <agent-id> --table
    """
    try:
        client = get_client()
        triggers = client.list_triggers(agent_id)

        if not triggers:
            typer.echo("No triggers found for this agent.")
            return

        formatted = [format_trigger_for_display(t) for t in triggers]

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
                columns=["name", "trigger_type", "status", "trigger_id"],
                headers=["Name", "Type", "Status", "Trigger ID"],
            )
        else:
            print_json(formatted)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@trigger_app.command("get")
def trigger_get(
    trigger_id: str = typer.Argument(
        ...,
        help="The trigger's component ID (GUID)",
    ),
    include_workflow: bool = typer.Option(
        False,
        "--include-workflow",
        "-w",
        help="Include the underlying workflow definition",
    ),
):
    """
    Get details for a specific trigger.

    Examples:
        copilot agent trigger get <trigger-id>
        copilot agent trigger get <trigger-id> --include-workflow
    """
    try:
        client = get_client()
        trigger = client.get_trigger(trigger_id)

        # Verify it's actually a trigger (componenttype=17)
        if trigger.get("componenttype") != 17:
            print_error(f"Component {trigger_id} is not an external trigger (componenttype={trigger.get('componenttype')})")
            raise typer.Exit(1)

        result = trigger

        if include_workflow:
            workflow = client.get_trigger_workflow(trigger_id)
            if workflow:
                result = {
                    "trigger": trigger,
                    "workflow": workflow,
                }

        print_json(result)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@trigger_app.command("enable")
def trigger_enable(
    trigger_id: str = typer.Argument(
        ...,
        help="The trigger's component ID (GUID)",
    ),
):
    """
    Enable a trigger.

    Sets the trigger state to Active so it will fire on events.

    Examples:
        copilot agent trigger enable <trigger-id>
    """
    try:
        client = get_client()

        # Get trigger name for confirmation message
        trigger = client.get_trigger(trigger_id)
        trigger_name = trigger.get("name", trigger_id)

        client.set_trigger_state(trigger_id, enabled=True)
        print_success(f"Trigger '{trigger_name}' enabled successfully.")
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@trigger_app.command("disable")
def trigger_disable(
    trigger_id: str = typer.Argument(
        ...,
        help="The trigger's component ID (GUID)",
    ),
):
    """
    Disable a trigger.

    Sets the trigger state to Inactive so it will not fire on events.

    Examples:
        copilot agent trigger disable <trigger-id>
    """
    try:
        client = get_client()

        # Get trigger name for confirmation message
        trigger = client.get_trigger(trigger_id)
        trigger_name = trigger.get("name", trigger_id)

        client.set_trigger_state(trigger_id, enabled=False)
        print_success(f"Trigger '{trigger_name}' disabled successfully.")
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@trigger_app.command("delete")
@trigger_app.command("remove")
def trigger_delete(
    trigger_id: str = typer.Argument(
        ...,
        help="The trigger's component ID (GUID)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Skip confirmation prompt",
    ),
    keep_workflow: bool = typer.Option(
        False,
        "--keep-workflow",
        help="Keep the underlying Power Automate flow (don't delete it)",
    ),
):
    """
    Delete a trigger.

    Permanently removes the trigger from the agent. By default, also deletes
    the underlying Power Automate flow.

    Examples:
        copilot agent trigger delete <trigger-id>
        copilot agent trigger delete <trigger-id> --force
        copilot agent trigger delete <trigger-id> --keep-workflow
    """
    try:
        client = get_client()

        # Get trigger name for confirmation message
        trigger = client.get_trigger(trigger_id)
        trigger_name = trigger.get("name", trigger_id)

        if not force:
            msg = f"Are you sure you want to delete trigger '{trigger_name}'?"
            if not keep_workflow:
                msg += " This will also delete the underlying workflow."
            confirm = typer.confirm(msg)
            if not confirm:
                typer.echo("Aborted.")
                raise typer.Exit(0)

        client.delete_trigger(trigger_id, delete_workflow=not keep_workflow)
        print_success(f"Trigger '{trigger_name}' deleted successfully.")
    except typer.Exit:
        raise
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


# Register trigger subgroup
app.add_typer(trigger_app, name="trigger")


# =============================================================================
# Tool Commands (Agent Tools / Connected Agents)
# =============================================================================

tool_app = typer.Typer(help="Manage agent tools (connected agents)")


def get_tool_category(schema_name: str, data: str = "") -> str:
    """Determine the tool category from the schema name or data field."""
    # Combine schema_name and data for pattern matching
    # UI-created tools have action kind in data, API-created in schema name
    search_text = (schema_name or "") + " " + (data or "")

    if not search_text.strip():
        return "Unknown"

    # Check for known patterns
    if "InvokeConnectedAgentTaskAction" in search_text:
        return "Agent"
    elif "InvokeFlowTaskAction" in search_text:
        return "Flow"
    elif "InvokePromptTaskAction" in search_text:
        return "Prompt"
    elif "InvokeConnectorTaskAction" in search_text:
        return "Connector"
    elif "InvokeHttpTaskAction" in search_text:
        return "HTTP"
    elif "TaskAction" in search_text:
        # Generic task action - extract the type
        import re
        match = re.search(r'Invoke(\w+)TaskAction', search_text)
        if match:
            return match.group(1)
        return "Action"
    elif ".action." in (schema_name or "").lower():
        # UI-created action without clear type - mark as Action
        return "Action"
    else:
        return "Unknown"


def format_tool_for_display(tool: dict, truncate: bool = False) -> dict:
    """Format an agent tool for display.

    Args:
        tool: The tool dict from the API
        truncate: If True, truncate long values for table display
    """
    schema_name = tool.get("schemaname", "") or ""
    data = tool.get("data", "") or ""

    # Determine category from schema and data
    category = get_tool_category(schema_name, data)

    # Extract description and display name from data if available
    data = tool.get("data", "") or ""
    description = ""
    display_name = ""
    if data:
        # Extract the description and display name from YAML-like data
        lines = data.split("\n")
        for line in lines:
            if line.startswith("modelDescription:"):
                description = line.replace("modelDescription:", "").strip().strip('"')
                if truncate and len(description) > 80:
                    description = description[:77] + "..."
            elif line.startswith("modelDisplayName:"):
                display_name = line.replace("modelDisplayName:", "").strip().strip('"')

    return {
        "name": tool.get("name"),
        "display_name": display_name,
        "category": category,
        "component_id": tool.get("botcomponentid"),
        "description": description,
        "status": tool.get("statecode@OData.Community.Display.V1.FormattedValue", "Active"),
    }


@tool_app.command("list")
def tool_list(
    agent_id: str = typer.Option(
        ...,
        "--agentId",
        "-a",
        help="The agent's unique identifier (GUID) or display name",
    ),
    category: Optional[str] = typer.Option(
        None,
        "--category",
        "-c",
        help="Filter by category: agent, flow, prompt, connector, http",
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
    List tools for an agent.

    Tools include connected agents, flows, prompts, connectors, and HTTP actions
    that the agent can invoke.

    Categories:
      - agent: Connected sub-agents (InvokeConnectedAgentTaskAction)
      - flow: Power Automate flows (InvokeFlowTaskAction)
      - prompt: AI prompts (InvokePromptTaskAction)
      - connector: Connector actions (InvokeConnectorTaskAction)
      - http: HTTP requests (InvokeHttpTaskAction)

    Examples:
        copilot agent tool list --agentId <agent-id>
        copilot agent tool list --agentId "My Custom Agent"
        copilot agent tool list --agentId <agent-id> --table
        copilot agent tool list --agentId <agent-id> --category agent
    """
    try:
        client = get_client()

        # Resolve agent_id: accept GUID or display name
        if not _is_guid(agent_id):
            resolved_id, _bot = _resolve_agent_id(client, agent_id)
            agent_id = resolved_id

        tools = client.list_tools(agent_id, category=category)

        if not tools:
            typer.echo("No agent tools found for this agent.")
            return

        formatted = [format_tool_for_display(t, truncate=table) for t in tools]

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
                columns=["name", "display_name", "category", "status", "component_id"],
                headers=["Name", "Display Name", "Category", "Status", "Component ID"],
            )
        else:
            print_json(formatted)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@tool_app.command("get")
def tool_get(
    component_id: str = typer.Argument(
        ...,
        help="The tool component's unique identifier (GUID)",
    ),
    raw: bool = typer.Option(
        False,
        "--raw",
        "-r",
        help="Show raw component data without parsing",
    ),
    yaml_output: bool = typer.Option(
        False,
        "--yaml",
        "-Y",
        help="Show the tool's YAML definition",
    ),
):
    """
    Get details of a specific tool.

    Shows comprehensive information about an agent tool including its
    configuration, inputs, outputs, and YAML definition.

    Examples:
        copilot agent tool get <component-id>
        copilot agent tool get <component-id> --yaml
        copilot agent tool get <component-id> --raw
    """
    import yaml as yaml_lib

    try:
        client = get_client()
        tool = client.get_tool(component_id)

        if raw:
            print_json(tool)
            return

        if yaml_output:
            data = tool.get("data", "")
            if data:
                typer.echo(data)
            else:
                typer.echo("No YAML definition found for this tool.")
            return

        # Parse the tool data for formatted output
        schema_name = tool.get("schemaname", "") or ""
        data = tool.get("data", "") or ""
        category = get_tool_category(schema_name, data)

        # Extract details from YAML data
        parsed_data = {}
        yaml_parse_error = None
        if data:
            try:
                parsed_data = yaml_lib.safe_load(data) or {}
            except Exception as e:
                yaml_parse_error = str(e)

        # Build display output - Basic Info Section
        typer.echo("=" * 60)
        typer.echo(f"Tool: {tool.get('name', 'Unknown')}")
        typer.echo("=" * 60)
        typer.echo(f"Component ID: {tool.get('botcomponentid', '')}")
        typer.echo(f"Category: {category}")
        typer.echo(f"Schema Name: {schema_name}")
        typer.echo(f"Status: {tool.get('statecode@OData.Community.Display.V1.FormattedValue', 'Active')}")

        # Show entity-level description if present
        entity_description = tool.get("description", "")
        if entity_description:
            typer.echo(f"Entity Description: {entity_description}")
        typer.echo("")

        # Display parsed YAML fields
        if parsed_data:
            typer.echo("--- Configuration ---")
            if parsed_data.get("modelDisplayName"):
                typer.echo(f"Display Name: {parsed_data.get('modelDisplayName')}")
            if parsed_data.get("modelDescription"):
                typer.echo(f"Description: {parsed_data.get('modelDescription')}")

            # Show availability settings
            availability = parsed_data.get("isAvailableForAgentInvocation")
            if availability is not None:
                typer.echo(f"Available for Agent: {availability}")

            # Show confirmation settings
            user_confirm = parsed_data.get("requiresUserConfirmation")
            if user_confirm is not None:
                typer.echo(f"Requires Confirmation: {user_confirm}")
            confirm_msg = parsed_data.get("userConfirmationText")
            if confirm_msg:
                typer.echo(f"Confirmation Message: {confirm_msg}")

            # Show inputs
            inputs = parsed_data.get("inputs") or []
            if inputs:
                typer.echo("")
                typer.echo("--- Inputs ---")
                for inp in inputs:
                    inp_name = inp.get("name", "unknown")
                    inp_type = inp.get("dataType", "unknown")
                    inp_required = inp.get("isRequired", False)
                    inp_desc = inp.get("description", "")
                    default_val = inp.get("defaultValue")
                    visible = inp.get("isVisible", True)
                    req_marker = " [required]" if inp_required else ""
                    vis_marker = " [hidden]" if not visible else ""
                    typer.echo(f"  {inp_name} ({inp_type}){req_marker}{vis_marker}")
                    if inp_desc:
                        typer.echo(f"    Description: {inp_desc}")
                    if default_val is not None:
                        typer.echo(f"    Default: {default_val}")

            # Show outputs (supports both 'name' and 'propertyName' formats)
            outputs = parsed_data.get("outputs") or []
            if outputs:
                typer.echo("")
                typer.echo("--- Outputs ---")
                for out in outputs:
                    out_name = out.get("name") or out.get("propertyName", "unknown")
                    out_type = out.get("dataType", "")
                    out_desc = out.get("description", "")
                    type_suffix = f" ({out_type})" if out_type else ""
                    typer.echo(f"  {out_name}{type_suffix}")
                    if out_desc:
                        typer.echo(f"    Description: {out_desc}")

        elif yaml_parse_error and data:
            # YAML couldn't be parsed, but try to extract key fields with regex
            import re
            typer.echo("--- Configuration ---")
            typer.echo("(Note: YAML data contains formatting issues)")
            # Try to extract modelDisplayName
            display_match = re.search(r'modelDisplayName:\s*(.+?)(?:\n|$)', data)
            if display_match:
                typer.echo(f"Display Name: {display_match.group(1).strip()}")
            # Try to extract modelDescription
            desc_match = re.search(r'modelDescription:\s*(.+?)(?:\noutputs:|$)', data, re.DOTALL)
            if desc_match:
                desc = desc_match.group(1).strip()
                if len(desc) > 200:
                    desc = desc[:200] + "..."
                typer.echo(f"Description: {desc}")

            # Try to extract outputs from raw YAML
            typer.echo("")
            typer.echo("--- Outputs ---")
            output_matches = re.findall(r'propertyName:\s*(\S+)', data)
            for out_name in output_matches:
                typer.echo(f"  {out_name}")

            # Try to extract action details
            typer.echo("")
            typer.echo("--- Action Details ---")
            kind_match = re.search(r'kind:\s*(\S+)', data)
            if kind_match and "TaskDialog" not in kind_match.group(1):
                typer.echo(f"Action Type: {kind_match.group(1)}")
            # Look for action kind specifically
            action_kind_match = re.search(r'action:\s*\n\s*kind:\s*(\S+)', data)
            if action_kind_match:
                typer.echo(f"Action Type: {action_kind_match.group(1)}")

            conn_ref_match = re.search(r'connectionReference:\s*(\S+)', data)
            if conn_ref_match:
                typer.echo(f"Connection Ref: {conn_ref_match.group(1)}")

            op_id_match = re.search(r'operationId:\s*(\S+)', data)
            if op_id_match:
                typer.echo(f"Operation ID: {op_id_match.group(1)}")

        # Show action-specific details - outside of if/elif for parsed data
        if parsed_data:
            # Support both 'actions' (list) and 'action' (single object) formats
            actions = parsed_data.get("actions") or []
            single_action = parsed_data.get("action")
            if single_action:
                actions = [single_action]
            if actions and len(actions) > 0:
                action = actions[0]  # Usually there's one main action
                action_kind = action.get("kind", "")
                typer.echo("")
                typer.echo("--- Action Details ---")
                typer.echo(f"Action Type: {action_kind}")

                # Connector-specific details
                if "Connector" in action_kind:
                    connector_id = action.get("connectorId", "")
                    operation_id = action.get("operationId", "")
                    # Support both connectionReferenceLogicalName and connectionReference
                    conn_ref = action.get("connectionReferenceLogicalName") or action.get("connectionReference", "")
                    if connector_id:
                        typer.echo(f"Connector ID: {connector_id}")
                    if operation_id:
                        typer.echo(f"Operation ID: {operation_id}")
                    if conn_ref:
                        typer.echo(f"Connection Ref: {conn_ref}")

                    # Show connection properties if present
                    conn_props = action.get("connectionProperties") or {}
                    if conn_props:
                        mode = conn_props.get("mode", "")
                        if mode:
                            typer.echo(f"Connection Mode: {mode}")

                    # Show input mappings if present
                    input_params = action.get("inputParameters") or {}
                    if input_params:
                        typer.echo("Input Mappings:")
                        for param_name, param_value in input_params.items():
                            typer.echo(f"  {param_name}: {param_value}")

                    # Show output mappings if present
                    output_params = action.get("outputParameters") or {}
                    if output_params:
                        typer.echo("Output Mappings:")
                        for param_name, param_value in output_params.items():
                            typer.echo(f"  {param_name}: {param_value}")

                # Agent-specific details
                elif "ConnectedAgent" in action_kind:
                    target_id = action.get("agentId", "")
                    if target_id:
                        typer.echo(f"Target Agent ID: {target_id}")
                    include_history = action.get("includeConversationHistory", False)
                    typer.echo(f"Include History: {include_history}")

                # Flow-specific details
                elif "Flow" in action_kind:
                    flow_id = action.get("flowId", "")
                    if flow_id:
                        typer.echo(f"Flow ID: {flow_id}")

                # HTTP-specific details
                elif "Http" in action_kind:
                    url = action.get("url", "")
                    method = action.get("method", "")
                    if url:
                        typer.echo(f"URL: {url}")
                    if method:
                        typer.echo(f"Method: {method}")

        # Show timestamps
        typer.echo("")
        typer.echo("--- Metadata ---")
        created = tool.get("createdon", "")
        modified = tool.get("modifiedon", "")
        if created:
            typer.echo(f"Created: {created}")
        if modified:
            typer.echo(f"Modified: {modified}")

        # Show parent bot info
        parent_bot = tool.get("_parentbotid_value", "")
        if parent_bot:
            typer.echo(f"Parent Bot: {parent_bot}")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@tool_app.command("add")
def tool_add(
    agent_id: str = typer.Option(
        ...,
        "--agentId",
        "-a",
        help="The parent agent's unique identifier (GUID)",
    ),
    tool_type: str = typer.Option(
        ...,
        "--toolType",
        "-T",
        help="Tool type: connector, prompt, flow, http, agent",
    ),
    tool_id: str = typer.Option(
        ...,
        "--id",
        help="Tool identifier (format depends on tool type)",
    ),
    name: Optional[str] = typer.Option(
        None,
        "--name",
        "-n",
        help="Display name for the tool (auto-generated if not provided)",
    ),
    description: Optional[str] = typer.Option(
        None,
        "--description",
        "-d",
        help="Description of when to use this tool (for AI orchestration)",
    ),
    inputs: Optional[str] = typer.Option(
        None,
        "--inputs",
        help="Static input values as JSON, e.g., '{\"workspace\": \"123\"}'. Sets fixed values instead of AI-filled.",
    ),
    outputs: Optional[str] = typer.Option(
        None,
        "--outputs",
        help="Output parameters as JSON string",
    ),
    # Type-specific parameters
    connection_reference_id: Optional[str] = typer.Option(
        None,
        "--connection-reference-id",
        help="Connection reference ID (GUID) from 'copilot connection-references list' (required for connector tools)",
    ),
    no_history: bool = typer.Option(
        False,
        "--no-history",
        help="Don't pass conversation history (for agent tools)",
    ),
    method: str = typer.Option(
        "GET",
        "--method",
        help="HTTP method (for http tools)",
    ),
    headers_json: Optional[str] = typer.Option(
        None,
        "--headers",
        help="HTTP headers as JSON string (for http tools)",
    ),
    body: Optional[str] = typer.Option(
        None,
        "--body",
        help="Request body template (for http tools)",
    ),
    credential: str = typer.Option(
        "maker-provided",
        "--credential",
        "-C",
        help="Credential mode for connector tools: 'maker-provided' (use maker's auth) or 'end-user' (prompt user to auth)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Force adding tool even if operation has internal visibility (may not work correctly)",
    ),
):
    """
    Add a tool to an agent.

    Tool Types:
      - connector: Power Platform connector operation
      - prompt: AI Builder prompt
      - flow: Power Automate flow
      - http: Direct HTTP request
      - agent: Connected Copilot Studio agent

    Tool ID Format (--id):
      - connector: "connector_id:operation_id" (e.g., "shared_asana:GetTask")
      - prompt: Prompt GUID
      - flow: Flow GUID
      - http: URL
      - agent: Target agent GUID

    Credential Modes (--credential):
      - maker-provided: Uses the maker's authenticated connection (default)
      - end-user: Prompts the user to authenticate when using the tool

    Examples:
        # Connector tool with maker's credentials (default)
        copilot agent tool add -a <agent-id> --toolType connector \\
            --id "shared_asana:GetTask" --connection-reference-id <conn-ref-id> --name "Get Task"

        # Connector tool with static input values (pre-filled, not AI-determined)
        copilot agent tool add -a <agent-id> --toolType connector \\
            --id "shared_asana:GetTasks" --connection-reference-id <conn-ref-id> \\
            --inputs '{"project": "1234567890"}' --name "Get Project Tasks"

        # Connector tool requiring end-user authentication
        copilot agent tool add -a <agent-id> --toolType connector \\
            --id "shared_asana:CreateTask" --connection-reference-id <conn-ref-id> \\
            --credential end-user --name "Create Task"

        # Prompt tool
        copilot agent tool add -a <agent-id> --toolType prompt \\
            --id <prompt-guid> --name "Summarize"

        # Flow tool
        copilot agent tool add -a <agent-id> --toolType flow \\
            --id <flow-guid> --name "Process Order"

        # HTTP tool
        copilot agent tool add -a <agent-id> --toolType http \\
            --id "https://api.example.com/data" --method POST

        # Connected agent tool
        copilot agent tool add -a <agent-id> --toolType agent \\
            --id <target-agent-id> --name "Expert Reviewer"
    """
    import json

    # Validate tool type
    valid_types = ['connector', 'prompt', 'flow', 'http', 'agent']
    if tool_type.lower() not in valid_types:
        typer.echo(f"Error: Invalid tool type '{tool_type}'. Must be one of: {', '.join(valid_types)}", err=True)
        raise typer.Exit(1)

    # Validate and map credential mode to internal connection mode
    credential_map = {
        'maker-provided': 'Maker',
        'end-user': 'Invoker',
        # Also accept legacy values for backwards compatibility
        'Maker': 'Maker',
        'Invoker': 'Invoker',
    }
    credential_lower = credential.lower() if credential.lower() in ['maker-provided', 'end-user'] else credential
    if credential_lower not in credential_map and credential not in credential_map:
        typer.echo(f"Error: Invalid credential mode '{credential}'. Must be one of: maker-provided, end-user", err=True)
        raise typer.Exit(1)
    connection_mode = credential_map.get(credential_lower) or credential_map.get(credential)

    # Parse JSON parameters
    inputs_dict = None
    if inputs:
        try:
            inputs_dict = json.loads(inputs)
        except json.JSONDecodeError as e:
            typer.echo(f"Error: Invalid JSON for --inputs: {e}", err=True)
            raise typer.Exit(1)

    outputs_dict = None
    if outputs:
        try:
            outputs_dict = json.loads(outputs)
        except json.JSONDecodeError as e:
            typer.echo(f"Error: Invalid JSON for --outputs: {e}", err=True)
            raise typer.Exit(1)

    headers_dict = None
    if headers_json:
        try:
            headers_dict = json.loads(headers_json)
        except json.JSONDecodeError as e:
            typer.echo(f"Error: Invalid JSON for --headers: {e}", err=True)
            raise typer.Exit(1)

    try:
        client = get_client()

        component_id = client.add_tool(
            bot_id=agent_id,
            tool_type=tool_type,
            tool_id=tool_id,
            name=name,
            description=description,
            inputs=inputs_dict,
            outputs=outputs_dict,
            connection_reference_id=connection_reference_id,
            connection_mode=connection_mode,
            no_history=no_history,
            method=method,
            headers=headers_dict,
            body=body,
            force=force,
        )

        if component_id:
            print_success(f"{tool_type.capitalize()} tool created successfully!")
            typer.echo(f"Component ID: {component_id}")
            typer.echo("")
            typer.echo("Note: You may need to publish the agent for changes to take effect.")
        else:
            typer.echo("Tool created but component ID could not be extracted.")
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@tool_app.command("remove")
def tool_remove(
    component_id: str = typer.Argument(
        ...,
        help="The tool component's unique identifier (GUID)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Skip confirmation prompt",
    ),
):
    """
    Remove a tool from an agent.

    Examples:
        copilot agent tool remove <component-id>
        copilot agent tool remove <component-id> --force
    """
    if not force:
        confirm = typer.confirm(f"Are you sure you want to remove tool {component_id}?")
        if not confirm:
            typer.echo("Operation cancelled.")
            raise typer.Exit(0)

    try:
        client = get_client()
        client.remove_tool(component_id)
        print_success(f"Tool {component_id} removed successfully.")
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@tool_app.command("update")
def tool_update(
    component_id: str = typer.Argument(
        ...,
        help="The tool component's unique identifier (GUID)",
    ),
    name: Optional[str] = typer.Option(
        None,
        "--name",
        "-n",
        help="New display name for the tool",
    ),
    description: Optional[str] = typer.Option(
        None,
        "--description",
        "-d",
        help="New description for the tool (used by AI for orchestration, max 1024 chars)",
    ),
    availability: Optional[bool] = typer.Option(
        None,
        "--available/--not-available",
        help="Allow agent to use tool dynamically (--available) or only from topics (--not-available)",
    ),
    confirmation: Optional[bool] = typer.Option(
        None,
        "--confirm/--no-confirm",
        help="Ask user for confirmation before running the tool",
    ),
    confirmation_message: Optional[str] = typer.Option(
        None,
        "--confirm-message",
        "-m",
        help="Custom message to show when asking for confirmation",
    ),
    inputs: Optional[str] = typer.Option(
        None,
        "--inputs",
        "-i",
        help='Input default values as JSON, e.g., \'{"workspace": "123", "projects": "456"}\'',
    ),
    credential: Optional[str] = typer.Option(
        None,
        "--credential",
        "-C",
        help="Credential mode for connector tools: 'maker-provided' (use maker's auth) or 'end-user' (prompt user to auth)",
    ),
):
    """
    Update a tool's attributes.

    The description field is especially important as it's used by the AI agent
    to determine when to use this tool. Make it descriptive and explicit about
    when the tool should be used.

    Tool Availability:
      --available      Agent may use this tool at any time (generative orchestration)
      --not-available  Only use when explicitly referenced by topics or agents

    User Confirmation:
      --confirm        Ask end user for approval before running
      --no-confirm     Run without asking (default)
      --confirm-message  Custom confirmation prompt text

    Input Defaults:
      --inputs         Set default values for tool inputs as JSON

    Credential Mode (connector tools only):
      --credential     'maker-provided' (use maker's auth) or 'end-user' (prompt user)

    Examples:
        # Update name and description
        copilot agent tool update <component-id> --name "New Tool Name"
        copilot agent tool update <component-id> --description "Use this tool when..."

        # Configure availability
        copilot agent tool update <component-id> --available      # Allow dynamic use
        copilot agent tool update <component-id> --not-available  # Only from topics

        # Configure user confirmation
        copilot agent tool update <component-id> --confirm        # Enable confirmation
        copilot agent tool update <component-id> --no-confirm     # Disable confirmation
        copilot agent tool update <component-id> --confirm --confirm-message "Proceed with action?"

        # Set input default values
        copilot agent tool update <component-id> --inputs '{"workspace": "123456", "projects": "789012"}'

        # Change credential mode (connector tools)
        copilot agent tool update <component-id> --credential maker-provided  # Use maker's credentials
        copilot agent tool update <component-id> --credential end-user        # Prompt user to auth

        # Combined update
        copilot agent tool update <component-id> -n "Name" -d "Description" --available --confirm
    """
    if not any([name, description, availability is not None, confirmation is not None, confirmation_message, inputs, credential]):
        typer.echo("Error: At least one option must be provided.", err=True)
        typer.echo("Options: --name, --description, --available/--not-available, --confirm/--no-confirm, --confirm-message, --inputs, --credential")
        raise typer.Exit(1)

    # Validate and map credential mode to internal connection mode
    connection_mode = None
    if credential:
        credential_map = {
            'maker-provided': 'Maker',
            'end-user': 'Invoker',
            # Also accept legacy values for backwards compatibility
            'Maker': 'Maker',
            'Invoker': 'Invoker',
        }
        credential_lower = credential.lower() if credential.lower() in ['maker-provided', 'end-user'] else credential
        if credential_lower not in credential_map and credential not in credential_map:
            typer.echo(f"Error: Invalid credential mode '{credential}'. Must be one of: maker-provided, end-user", err=True)
            raise typer.Exit(1)
        connection_mode = credential_map.get(credential_lower) or credential_map.get(credential)

    # Validate description length
    if description and len(description) > 1024:
        typer.echo(f"Error: Description exceeds 1024 character limit ({len(description)} chars).", err=True)
        raise typer.Exit(1)

    # Parse inputs JSON if provided
    inputs_dict = None
    if inputs:
        try:
            inputs_dict = json.loads(inputs)
            if not isinstance(inputs_dict, dict):
                typer.echo("Error: --inputs must be a JSON object (dict)", err=True)
                raise typer.Exit(1)
        except json.JSONDecodeError as e:
            typer.echo(f"Error: Invalid JSON for --inputs: {e}", err=True)
            raise typer.Exit(1)

    try:
        client = get_client()
        result = client.update_tool(
            component_id=component_id,
            name=name,
            description=description,
            availability=availability,
            confirmation=confirmation,
            confirmation_message=confirmation_message,
            inputs=inputs_dict,
            connection_mode=connection_mode,
        )
        print_success(f"Tool updated successfully!")
        typer.echo(f"Name: {result.get('name', 'N/A')}")
        if result.get('description'):
            desc = result['description']
            if len(desc) > 100:
                desc = desc[:100] + "..."
            typer.echo(f"Description: {desc}")

        # Show additional settings if they were updated
        data = result.get('data', '')
        if availability is not None:
            status = "Available for dynamic use" if availability else "Only available from topics"
            typer.echo(f"Availability: {status}")
        if confirmation is not None or confirmation_message:
            if 'confirmation:' in data:
                typer.echo(f"User Confirmation: Enabled")
            else:
                typer.echo(f"User Confirmation: Disabled")
        if inputs_dict:
            typer.echo(f"Input defaults updated: {', '.join(inputs_dict.keys())}")
        if connection_mode:
            mode_display = "Maker-provided" if connection_mode == "Maker" else "End-user"
            typer.echo(f"Credential mode: {mode_display}")
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


# Register tool subgroup
app.add_typer(tool_app, name="tool")


# =============================================================================
# Analytics (Application Insights) Commands
# =============================================================================

analytics_app = typer.Typer(help="Manage Application Insights telemetry for agents")


@analytics_app.command("list")
def analytics_list(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of agents to return"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter: Optional[list[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """
    List all agents with their Application Insights analytics status.

    Shows each agent's analytics configuration including whether App Insights
    is enabled and activity logging settings.

    Examples:
        copilot agent analytics list
        copilot agent analytics list --table
        copilot agent analytics list --filter "analytics_enabled:eq:true"
        copilot agent analytics list --properties "name,analytics_enabled"
    """
    try:
        client = get_client()
        bots = client.list_bots(limit=limit)

        results = []
        for bot in bots:
            bot_id = bot.get("botid", "")
            bot_name = bot.get("name", "")
            try:
                config = client.get_bot_app_insights(bot_id)
                results.append({
                    "id": bot_id,
                    "name": bot_name,
                    "analytics_enabled": config["enabled"],
                    "log_activities": config["logActivities"],
                })
            except Exception:
                results.append({
                    "id": bot_id,
                    "name": bot_name,
                    "analytics_enabled": False,
                    "log_activities": False,
                })

        # Apply filters
        if filter:
            from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError
            try:
                validate_filters(filter)
                results = apply_filters(results, filter)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        # Apply limit
        results = results[:limit]

        # Apply properties filter
        if properties:
            property_list = [p.strip() for p in properties.split(",")]
            results = [{k: v for k, v in item.items() if k in property_list} for item in results]

        if table:
            print_table(
                results,
                columns=["name", "analytics_enabled", "log_activities", "id"],
                headers=["Name", "Enabled", "Log Activities", "ID"],
            )
        else:
            print_json(results)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@analytics_app.command("get")
def analytics_get(
    agent_id: str = typer.Argument(..., help="The agent's unique identifier (GUID)"),
):
    """
    Get Application Insights configuration for an agent.

    Shows the current App Insights connection string and logging settings.

    Examples:
        copilot agent analytics get 12345678-1234-1234-1234-123456789abc
    """
    try:
        client = get_client()

        # Get agent name for display
        bot = client.get_bot(agent_id)
        agent_name = bot.get("name", agent_id)

        config = client.get_bot_app_insights(agent_id)

        print_json({
            "id": agent_id,
            "agent_id": agent_id,
            "agent_name": agent_name,
            "enabled": config["enabled"],
            "connectionString": config.get("connectionString", ""),
            "logActivities": config["logActivities"],
            "logSensitiveProperties": config["logSensitiveProperties"],
        })

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@analytics_app.command("enable")
def analytics_enable(
    agent_id: str = typer.Argument(..., help="The agent's unique identifier (GUID)"),
    connection_string: str = typer.Option(
        ...,
        "--connection-string",
        "-c",
        help="App Insights connection string (from Azure portal)",
    ),
    log_activities: bool = typer.Option(
        False,
        "--log-activities",
        "-l",
        help="Enable logging of incoming/outgoing messages and events",
    ),
    log_sensitive: bool = typer.Option(
        False,
        "--log-sensitive",
        "-s",
        help="Enable logging of sensitive properties (userid, name, text, speak)",
    ),
):
    """
    Enable Application Insights telemetry for an agent.

    Configures the agent to send telemetry to an existing App Insights instance.
    Multiple agents can share the same App Insights instance.

    The connection string can be found in your Azure Application Insights
    resource under Settings > Properties or in the Overview section.

    Examples:
        copilot agent analytics enable <agent-id> -c "InstrumentationKey=xxx;..."
        copilot agent analytics enable <agent-id> -c "..." --log-activities
        copilot agent analytics enable <agent-id> -c "..." --log-activities --log-sensitive
    """
    try:
        client = get_client()

        # Get agent name for display
        bot = client.get_bot(agent_id)
        agent_name = bot.get("name", agent_id)

        typer.echo(f"Enabling Application Insights for '{agent_name}'...")

        client.update_bot_app_insights(
            bot_id=agent_id,
            connection_string=connection_string,
            log_activities=log_activities,
            log_sensitive_properties=log_sensitive,
        )

        print_success(f"Application Insights enabled for '{agent_name}'!")
        typer.echo("")
        typer.echo("Settings applied:")
        typer.echo(f"  Log Activities:           {log_activities}")
        typer.echo(f"  Log Sensitive Properties: {log_sensitive}")
        typer.echo("")
        typer.echo("Note: Telemetry data will appear in your App Insights Logs section.")
        typer.echo("      You may need to republish the agent for changes to take effect.")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@analytics_app.command("disable")
def analytics_disable(
    agent_id: str = typer.Argument(..., help="The agent's unique identifier (GUID)"),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Skip confirmation prompt",
    ),
):
    """
    Disable Application Insights telemetry for an agent.

    Removes the App Insights connection string and disables all logging.

    Examples:
        copilot agent analytics disable <agent-id>
        copilot agent analytics disable <agent-id> --force
    """
    try:
        client = get_client()

        # Get agent name for display
        bot = client.get_bot(agent_id)
        agent_name = bot.get("name", agent_id)

        if not force:
            confirm = typer.confirm(
                f"Are you sure you want to disable Application Insights for '{agent_name}'?"
            )
            if not confirm:
                typer.echo("Operation cancelled.")
                raise typer.Exit(0)

        typer.echo(f"Disabling Application Insights for '{agent_name}'...")

        client.update_bot_app_insights(bot_id=agent_id, disable=True)

        print_success(f"Application Insights disabled for '{agent_name}'.")
        typer.echo("")
        typer.echo("Note: You may need to republish the agent for changes to take effect.")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@analytics_app.command("update")
def analytics_update(
    agent_id: str = typer.Argument(..., help="The agent's unique identifier (GUID)"),
    log_activities: Optional[bool] = typer.Option(
        None,
        "--log-activities/--no-log-activities",
        help="Enable/disable logging of messages and events",
    ),
    log_sensitive: Optional[bool] = typer.Option(
        None,
        "--log-sensitive/--no-log-sensitive",
        help="Enable/disable logging of sensitive properties",
    ),
):
    """
    Update Application Insights logging options for an agent.

    Use this to change logging settings without modifying the connection string.

    Examples:
        copilot agent analytics update <agent-id> --log-activities
        copilot agent analytics update <agent-id> --no-log-activities
        copilot agent analytics update <agent-id> --log-sensitive
        copilot agent analytics update <agent-id> --log-activities --log-sensitive
    """
    if log_activities is None and log_sensitive is None:
        typer.echo("Error: Please specify at least one option to update.")
        typer.echo("Use --log-activities/--no-log-activities or --log-sensitive/--no-log-sensitive")
        raise typer.Exit(1)

    try:
        client = get_client()

        # Get agent name for display
        bot = client.get_bot(agent_id)
        agent_name = bot.get("name", agent_id)

        typer.echo(f"Updating Application Insights settings for '{agent_name}'...")

        client.update_bot_app_insights(
            bot_id=agent_id,
            log_activities=log_activities,
            log_sensitive_properties=log_sensitive,
        )

        print_success(f"Application Insights settings updated for '{agent_name}'!")

        # Show what was updated
        updates = []
        if log_activities is not None:
            updates.append(f"Log Activities: {log_activities}")
        if log_sensitive is not None:
            updates.append(f"Log Sensitive Properties: {log_sensitive}")

        if updates:
            typer.echo("")
            typer.echo("Updated settings:")
            for update in updates:
                typer.echo(f"  {update}")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


def _convert_timespan(timespan: str) -> str:
    """
    Convert user-friendly timespan to ISO 8601 duration.

    Examples:
        1h → PT1H
        24h → PT24H
        7d → P7D
        30d → P30D
    """
    timespan = timespan.lower().strip()

    # Already ISO 8601 format
    if timespan.startswith("p"):
        return timespan.upper()

    # Parse number and unit
    import re
    match = re.match(r"^(\d+)([hd])$", timespan)
    if not match:
        raise ValueError(f"Invalid timespan format: {timespan}. Use format like '24h' or '7d'")

    value = match.group(1)
    unit = match.group(2)

    if unit == "h":
        return f"PT{value}H"
    elif unit == "d":
        return f"P{value}D"

    raise ValueError(f"Unknown time unit: {unit}")


@analytics_app.command("query")
def analytics_query(
    agent_id: str = typer.Argument(..., help="The agent's unique identifier (GUID)"),
    timespan: str = typer.Option(
        "24h",
        "--timespan",
        "-t",
        help="Time range to query (e.g., 1h, 24h, 7d, 30d)",
    ),
    events_only: bool = typer.Option(
        False,
        "--events",
        "-e",
        help="Query only customEvents table (faster)",
    ),
    table: bool = typer.Option(
        False,
        "--table",
        help="Output as human-readable format instead of JSON",
    ),
    limit: int = typer.Option(
        100,
        "--limit",
        "-l",
        help="Maximum number of rows to display",
    ),
):
    """
    Query Application Insights telemetry for an agent.

    Retrieves telemetry data from the Application Insights instance
    configured for this agent. Requires App Insights to be enabled.

    Examples:
        copilot agent analytics query <agent-id>
        copilot agent analytics query <agent-id> --timespan 7d
        copilot agent analytics query <agent-id> --events --table
        copilot agent analytics query <agent-id> -t 1h -l 50
    """
    try:
        # Convert timespan to ISO 8601
        try:
            iso_timespan = _convert_timespan(timespan)
        except ValueError as e:
            typer.echo(f"Error: {e}")
            raise typer.Exit(1)

        client = get_client()

        # Get agent name for display
        bot = client.get_bot(agent_id)
        agent_name = bot.get("name", agent_id)

        typer.echo(f"Querying Application Insights for '{agent_name}'...")
        typer.echo(f"Time range: {timespan}")
        typer.echo("")

        # Execute query
        result = client.get_bot_telemetry(
            bot_id=agent_id,
            timespan=iso_timespan,
            events_only=events_only,
        )

        # Handle output format - JSON is default per cli-tools standards
        if not table:
            print_json(result)
            return

        # Parse and display results as human-readable table format
        tables = result.get("tables", [])
        if not tables:
            typer.echo("No telemetry data found for the specified time range.")
            return

        result_table = tables[0]
        columns = [col["name"] for col in result_table.get("columns", [])]
        rows = result_table.get("rows", [])

        if not rows:
            typer.echo("No telemetry data found for the specified time range.")
            return

        typer.echo(f"Found {len(rows)} records (showing up to {limit}):")
        typer.echo("")

        # Display as formatted output
        displayed = 0
        for row in rows:
            if displayed >= limit:
                typer.echo(f"\n... and {len(rows) - limit} more records. Use --limit to see more.")
                break

            # Create a dict for this row
            row_data = dict(zip(columns, row))

            timestamp = row_data.get("timestamp", "")
            if timestamp:
                # Format timestamp for display
                timestamp = timestamp.replace("T", " ").split(".")[0]

            table_name = row_data.get("_table", "event")
            name = row_data.get("name", "")
            message = row_data.get("message", "")

            # Format the line
            line = f"[{timestamp}] [{table_name}]"
            if name:
                line += f" {name}"
            if message:
                line += f": {message}"

            typer.echo(line)

            # Show custom dimensions if present (condensed)
            custom_dims = row_data.get("customDimensions")
            if custom_dims and isinstance(custom_dims, dict):
                # Show key fields from customDimensions
                key_fields = ["TopicName", "Kind", "text", "channelId", "fromName"]
                dim_parts = []
                for field in key_fields:
                    if field in custom_dims and custom_dims[field]:
                        dim_parts.append(f"{field}={custom_dims[field]}")
                if dim_parts:
                    typer.echo(f"    {', '.join(dim_parts)}")

            displayed += 1

        typer.echo("")
        print_success(f"Query complete. Retrieved {len(rows)} records.")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


# Register analytics subgroup
app.add_typer(analytics_app, name="analytics")


# =============================================================================
# Authentication Commands
# =============================================================================

auth_app = typer.Typer(help="Manage agent authentication configuration")

# Authentication mode mapping for display
AUTH_MODE_NAMES = {
    1: "None",
    2: "Integrated",
    3: "Custom Azure AD",
}


@auth_app.command("get")
def auth_get(
    agent_id: str = typer.Argument(..., help="The agent's unique identifier (GUID)"),
):
    """
    Get authentication configuration for an agent.

    Shows the current authentication mode and settings.

    Authentication Modes:
      - 1 = None (no authentication required)
      - 2 = Integrated (Microsoft Entra ID integrated)
      - 3 = Custom Azure AD (manual configuration)

    Examples:
        copilot agent auth get 12345678-1234-1234-1234-123456789abc
    """
    try:
        client = get_client()

        # Get agent name for display
        bot = client.get_bot(agent_id)
        agent_name = bot.get("name", agent_id)

        auth_config = client.get_bot_auth(agent_id)

        print_json({
            "id": agent_id,
            "agent_id": agent_id,
            "agent_name": agent_name,
            "mode": auth_config["mode"],
            "mode_name": auth_config["mode_name"],
            "trigger": auth_config["trigger"],
            "trigger_name": auth_config["trigger_name"],
            "configuration": auth_config.get("configuration"),
        })

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@auth_app.command("set")
def auth_set(
    agent_id: str = typer.Argument(..., help="The agent's unique identifier (GUID)"),
    mode: Optional[int] = typer.Option(
        None,
        "--mode",
        "-m",
        help="Authentication mode: 1=None, 2=Integrated, 3=Custom Azure AD",
    ),
    trigger: Optional[int] = typer.Option(
        None,
        "--trigger",
        help="Authentication trigger: 0=As Needed, 1=Always",
    ),
):
    """
    Set authentication mode and/or trigger for an agent.

    Authentication Modes:
      - 1 = None (no authentication required)
      - 2 = Integrated (Microsoft Entra ID integrated - default for new agents)
      - 3 = Custom Azure AD (manual Microsoft Entra ID configuration)

    Authentication Triggers:
      - 0 = As Needed (authenticate only when required)
      - 1 = Always (require authentication for all conversations)

    Examples:
        copilot agent auth set <agent-id> --mode 1
        copilot agent auth set <agent-id> --mode 1 --trigger 0
        copilot agent auth set <agent-id> --trigger 0
    """
    try:
        if mode is None and trigger is None:
            typer.echo("Error: Must specify at least --mode or --trigger", err=True)
            raise typer.Exit(1)

        if mode is not None and mode not in AUTH_MODE_NAMES:
            typer.echo(f"Error: Invalid mode {mode}. Valid modes: 1=None, 2=Integrated, 3=Custom Azure AD", err=True)
            raise typer.Exit(1)

        if trigger is not None and trigger not in (0, 1):
            typer.echo(f"Error: Invalid trigger {trigger}. Valid triggers: 0=As Needed, 1=Always", err=True)
            raise typer.Exit(1)

        client = get_client()

        # Get agent name for display
        bot = client.get_bot(agent_id)
        agent_name = bot.get("name", agent_id)

        updates = []
        if mode is not None:
            updates.append(f"mode to {mode} ({AUTH_MODE_NAMES[mode]})")
        if trigger is not None:
            trigger_name = "As Needed" if trigger == 0 else "Always"
            updates.append(f"trigger to {trigger} ({trigger_name})")

        typer.echo(f"Setting authentication for '{agent_name}': {', '.join(updates)}...")

        client.update_bot_auth(bot_id=agent_id, mode=mode, trigger=trigger)

        print_success(f"Authentication updated for '{agent_name}'!")
        typer.echo("")
        typer.echo("Note: You may need to republish the agent for changes to take effect.")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@auth_app.command("list")
def auth_list(
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
    List authentication modes for all agents.

    Shows the authentication mode for each agent in the environment.

    Examples:
        copilot agent auth list
        copilot agent auth list --table
    """
    try:
        client = get_client()
        bots = client.list_bots(
            select=["name", "botid", "authenticationmode", "statecode"]
        )

        if not bots:
            typer.echo("No agents found.")
            return

        # Format for display
        formatted = []
        for bot in bots:
            auth_mode = bot.get("authenticationmode", 2)
            bot_id = bot.get("botid")
            formatted.append({
                "id": bot_id,
                "name": bot.get("name"),
                "bot_id": bot_id,
                "auth_mode": auth_mode,
                "auth_mode_name": AUTH_MODE_NAMES.get(auth_mode, f"Unknown({auth_mode})"),
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
                columns=["name", "auth_mode", "auth_mode_name", "bot_id"],
                headers=["Name", "Mode", "Mode Name", "Bot ID"],
            )
        else:
            print_json(formatted)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


# Register auth subgroup
app.add_typer(auth_app, name="auth")


# =============================================================================
# Model Subcommands
# =============================================================================

model_app = typer.Typer(help="Manage agent AI model configuration")

# Known models based on Microsoft Copilot Studio documentation
# https://learn.microsoft.com/en-us/microsoft-copilot-studio/authoring-select-agent-model
KNOWN_MODELS = [
    {
        "id": "gpt-4o",
        "name": "GPT-4o",
        "category": "General",
        "availability": "Retired",
        "cost": "Standard",
        "description": "General-purpose model. Good for most tasks. Context up to 128K tokens.",
    },
    {
        "id": "gpt-4o-mini",
        "name": "GPT-4o mini",
        "category": "General",
        "availability": "Listed",
        "cost": "Basic",
        "description": "Cost-effective model. Good for simple tasks. Context up to 128K tokens.",
    },
    {
        "id": "gpt-4.1-mini",
        "name": "GPT-4.1 mini",
        "category": "General",
        "availability": "Listed",
        "cost": "Basic",
        "description": "Smaller GPT-4.1 variant. Context up to 128K tokens.",
    },
    {
        "id": "gpt-4.1",
        "name": "GPT-4.1",
        "category": "General",
        "availability": "Default",
        "cost": "Standard",
        "description": "Superior for complex tasks. Context up to 128K tokens.",
    },
    {
        "id": "gpt-5-chat",
        "name": "GPT-5 Chat",
        "category": "General",
        "availability": "GA",
        "cost": "Standard",
        "description": "Highest accuracy and document understanding. Context up to 400K tokens.",
    },
    {
        "id": "gpt-5-reasoning",
        "name": "GPT-5 Reasoning",
        "category": "Deep",
        "availability": "Preview",
        "cost": "Premium",
        "description": "Optimized for complex reasoning and analysis. Context up to 400K tokens.",
    },
    {
        "id": "claude-sonnet-4.5",
        "name": "Claude Sonnet 4.5",
        "category": "General",
        "availability": "Experimental",
        "cost": "Standard",
        "description": "External model from Anthropic. Context up to 200K tokens.",
    },
    {
        "id": "claude-opus-4.1",
        "name": "Claude Opus 4.1",
        "category": "Deep",
        "availability": "Experimental",
        "cost": "Premium",
        "description": "External model from Anthropic. Context up to 200K tokens.",
    },
]

# Canonical model IDs to configuration hint mapping.
# These are the pairs the CLI will write back to Dataverse.
MODEL_CONFIG_MAP = {
    "gpt-4o": {"kind": "DefaultModels", "modelNameHint": "GPT4o"},
    "gpt-4o-mini": {"kind": "DefaultModels", "modelNameHint": "GPT4o-mini"},
    "gpt-4.1-mini": {"kind": "DefaultModels", "modelNameHint": "GPT4.1-mini"},
    "gpt-4.1": {"kind": "DefaultModels", "modelNameHint": "GPT4.1"},
    "gpt-5-chat": {"kind": "ChatPreviewModels", "modelNameHint": "GPT5Chat"},
    "gpt-5-reasoning": {"kind": "ReasoningPreviewModels", "modelNameHint": "GPT5Reasoning"},
    "claude-sonnet-4.5": {"kind": "ExternalModels", "modelNameHint": "ClaudeSonnet45"},
    "claude-opus-4.1": {"kind": "ExternalModels", "modelNameHint": "ClaudeOpus41"},
}

MODEL_ID_ALIASES = {
    "gpt-41-mini": "gpt-4.1-mini",
    "gpt-41": "gpt-4.1",
    "claude-sonnet-45": "claude-sonnet-4.5",
    "claude-opus-41": "claude-opus-4.1",
}

KNOWN_MODELS_BY_ID = {model["id"]: model for model in KNOWN_MODELS}
MODEL_PAIR_TO_ID = {
    (config["kind"].lower(), config["modelNameHint"].lower()): model_id
    for model_id, config in MODEL_CONFIG_MAP.items()
}
CURRENT_DEFAULT_MODEL_ID = "gpt-4.1"


def _normalize_model_id(model_id: str) -> str:
    """Normalize a model ID or alias to the canonical model ID."""
    normalized = model_id.strip().lower()
    return MODEL_ID_ALIASES.get(normalized, normalized)


def _format_model_pair(model_kind: Optional[str], model_hint: Optional[str]) -> Optional[str]:
    """Render a raw kind:hint pair when both values are present."""
    if model_kind and model_hint:
        return f"{model_kind}:{model_hint}"
    return None


def _get_current_default_model() -> dict:
    """Return the current default model from the documented catalog."""
    default_model = KNOWN_MODELS_BY_ID.get(CURRENT_DEFAULT_MODEL_ID)
    if not default_model:
        raise RuntimeError(f"Current default model '{CURRENT_DEFAULT_MODEL_ID}' is not in KNOWN_MODELS")
    return default_model


def _resolve_stored_model(model_kind: Optional[str], model_hint: Optional[str]) -> dict:
    """
    Resolve a stored Dataverse kind:hint pair to a known Copilot Studio model.

    When the stored pair is invalid but the kind is `DefaultModels`, resolve to
    the currently documented default model because Copilot Studio surfaces the
    default model in the UI for that category.
    """
    result = {
        "rawKind": model_kind,
        "rawModelNameHint": model_hint,
        "rawPair": _format_model_pair(model_kind, model_hint),
        "modelId": None,
        "modelName": None,
        "resolution": "missing",
        "isKnownPair": False,
        "issues": [],
    }

    if not model_kind and not model_hint:
        return result

    if not model_kind or not model_hint:
        result["resolution"] = "incomplete"
        result["issues"].append("Stored model configuration is incomplete; both kind and modelNameHint are required.")
        return result

    pair_key = (model_kind.lower(), model_hint.lower())
    model_id = MODEL_PAIR_TO_ID.get(pair_key)
    if model_id:
        model = KNOWN_MODELS_BY_ID.get(model_id, {"id": model_id, "name": model_id})
        result.update(
            {
                "modelId": model_id,
                "modelName": model["name"],
                "resolution": "exact",
                "isKnownPair": True,
            }
        )
        return result

    if model_kind == "DefaultModels":
        default_model = _get_current_default_model()
        result.update(
            {
                "modelId": default_model["id"],
                "modelName": default_model["name"],
                "resolution": "default-category",
            }
        )
        result["issues"].append(
            f"Stored pair {model_kind}:{model_hint} is not a recognized model mapping. "
            f"Copilot Studio currently documents {default_model['name']} as the default model, "
            "so the CLI resolves this pair to that model."
        )
        return result

    result["resolution"] = "unknown"
    result["issues"].append(
        f"Stored pair {model_kind}:{model_hint} does not match any canonical model mapping known to the CLI."
    )
    return result


def _parse_requested_model(model: str) -> dict:
    """Parse a user-provided model ID or canonical kind:hint pair."""
    raw_value = model.strip()
    if not raw_value:
        raise ValueError("Model value cannot be empty.")

    if ":" in raw_value:
        model_kind, model_hint = [part.strip() for part in raw_value.split(":", 1)]
        if not model_kind or not model_hint:
            raise ValueError("Invalid model format. Expected kind:hint.")

        model_id = MODEL_PAIR_TO_ID.get((model_kind.lower(), model_hint.lower()))
        if not model_id:
            raise ValueError(
                f"Unknown or invalid model pair: {model_kind}:{model_hint}. "
                "Use a model ID from 'copilot agent model list' or a canonical kind:hint pair."
            )

        config = MODEL_CONFIG_MAP[model_id]
        model_meta = KNOWN_MODELS_BY_ID.get(model_id, {"id": model_id, "name": model_id})
        return {
            "modelId": model_id,
            "modelName": model_meta["name"],
            "kind": config["kind"],
            "modelNameHint": config["modelNameHint"],
        }

    model_id = _normalize_model_id(raw_value)
    config = MODEL_CONFIG_MAP.get(model_id)
    if not config:
        raise ValueError(
            f"Unknown model ID: {raw_value}. Use 'copilot agent model list' to see supported model IDs."
        )

    model_meta = KNOWN_MODELS_BY_ID.get(model_id, {"id": model_id, "name": model_id})
    return {
        "modelId": model_id,
        "modelName": model_meta["name"],
        "kind": config["kind"],
        "modelNameHint": config["modelNameHint"],
    }


_MODEL_DOCS_URL = "https://learn.microsoft.com/en-us/microsoft-copilot-studio/authoring-select-agent-model"


def _fetch_model_catalog() -> list[dict]:
    """Fetch available models from the Microsoft Learn docs page."""
    import re
    import urllib.request

    try:
        req = urllib.request.Request(_MODEL_DOCS_URL, headers={"User-Agent": "copilot-cli/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8")
    except Exception as e:
        raise RuntimeError(f"Failed to fetch model catalog from {_MODEL_DOCS_URL}: {e}")

    # Find the "Public availability" table — it's the first large table after that heading
    # Parse HTML table rows: each row has <td> cells for Model, Tag/Category, then regions
    # We only need columns 0 (Model) and 1 (Tag/Category) plus any region to get availability
    table_match = re.search(
        r'<h3[^>]*>\s*Public availability\s*</h3>.*?<table[^>]*>(.*?)</table>',
        html, re.DOTALL | re.IGNORECASE
    )
    if not table_match:
        raise RuntimeError("Could not find Public availability table in docs page")

    table_html = table_match.group(1)
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table_html, re.DOTALL)

    models = []
    for row in rows[1:]:  # skip header row
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
        if len(cells) < 3:
            continue

        name = re.sub(r'<[^>]+>', '', cells[0]).strip()
        # Clean up footnote references like "(see important note below)"
        name = re.sub(r'\s*\(see\s+.*?\)', '', name, flags=re.IGNORECASE).strip()
        category = re.sub(r'<[^>]+>', '', cells[1]).strip()

        # Determine availability from US column (last) or first non-empty region
        us_status = re.sub(r'<[^>]+>', '', cells[-1]).strip() if len(cells) > 2 else ""

        # Normalize availability to a simple tag
        status_lower = us_status.lower()
        if "default" in status_lower:
            availability = "Default"
        elif "retired" in status_lower:
            availability = "Retired"
        elif "experimental" in status_lower:
            availability = "Experimental"
        elif "preview" in status_lower:
            availability = "Preview"
        elif "ga" in status_lower:
            availability = "GA"
        elif "unavailable" in status_lower:
            availability = "Unavailable"
        else:
            availability = us_status

        if not name:
            continue

        models.append({
            "name": name,
            "category": category,
            "availability": availability,
        })

    return models


def _discover_hints_from_agents() -> dict:
    """Scan agents to discover modelKind:modelNameHint for models in use."""
    client = get_client()
    result = client.get(
        "botcomponents?$filter=componenttype eq 15"
        "&$select=botcomponentid,name,data"
    )

    # Map display-name-like keys to kind:hint
    hints = {}  # lowercase model name -> {"modelKind": ..., "modelNameHint": ...}
    for comp in result.get("value", []):
        parsed = client.parse_gpt_component_yaml(comp.get("data", ""))
        kind = parsed.get("model_kind")
        hint = parsed.get("model_hint")
        if kind and hint:
            hints[hint] = {"modelKind": kind, "modelNameHint": hint}

    return hints


def _match_hint_to_model(model_name: str, hints: dict) -> Optional[dict]:
    """Match a model display name to a discovered kind:hint from agents.

    Uses compact string matching: strips spaces, dots, hyphens and checks
    if the hint is a substring of the name or vice versa.
    e.g. "GPT5Reasoning" matches "GPT-5 Reasoning", "ClaudeOpus45" matches "Claude Opus 4.5"
    """
    import re

    # Compact: lowercase, strip separators
    def compact(s):
        return re.sub(r'[\s.\-_]', '', s.lower())

    name_c = compact(model_name)

    for hint_key, hint_val in hints.items():
        hint_c = compact(hint_key)

        # Direct compact match (handles "GPT5Reasoning" <-> "gpt5reasoning")
        if hint_c in name_c or name_c in hint_c:
            return hint_val

        # Model-family match: extract the family word (opus, sonnet, grok, gpt)
        # and qualifier words (reasoning, chat, auto) from both
        hint_words = re.findall(r'[a-z]{3,}', hint_c)  # e.g. ["gpt", "reasoning"] from "gpt5reasoning"
        name_words = re.findall(r'[a-z]{3,}', name_c)  # e.g. ["gpt", "reasoning"] from "gpt5reasoning"

        if not hint_words:
            continue

        # The hint's primary family word must appear in the model name
        primary = hint_words[0]
        if primary not in name_c:
            continue

        # ALL hint words must appear in the model name (prevents "gpt5reasoning" matching "GPT-5 Chat")
        if not all(w in name_c for w in hint_words):
            continue

        # Extract version-like digit sequences from both
        hint_digits = re.findall(r'\d+', hint_key)  # e.g. ["4", "1"] from "opus4-1"
        name_digits = re.findall(r'\d+', model_name)  # e.g. ["4", "6"] from "Claude Opus 4.6"

        # Version match: first digit group must match (major version)
        if hint_digits and name_digits and hint_digits[0] == name_digits[0]:
            return hint_val

    return None


@model_app.command("list")
def model_list(
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
    List available AI models for Copilot Studio agents.

    Fetches the current model catalog from Microsoft Learn documentation and
    enriches with kind:hint values discovered from agents in your environment.

    The kind:hint column shows the value to use with 'copilot agent model set'.
    Models not in use by any agent show '-' for kind:hint (set one to discover it).

    Examples:
        copilot agent model list
        copilot agent model list --table
        copilot agent model list -f category:eq:Deep
    """
    try:
        # Fetch catalog from docs + discover hints from agents in parallel-ish
        catalog = _fetch_model_catalog()
        hints = _discover_hints_from_agents()

        # Enrich catalog with kind:hint from discovered agents
        for model in catalog:
            matched_hint = _match_hint_to_model(model["name"], hints)
            model["id"] = model["name"]
            model["kind_hint"] = f"{matched_hint['modelKind']}:{matched_hint['modelNameHint']}" if matched_hint else "-"

        # Apply filters
        if filter:
            from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError
            try:
                validate_filters(filter)
                catalog = apply_filters(catalog, filter)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        # Apply limit
        catalog = catalog[:limit]

        # Apply properties filter
        if properties:
            property_list = [p.strip() for p in properties.split(",")]
            catalog = [{k: v for k, v in item.items() if k in property_list} for item in catalog]

        if table:
            print_table(
                catalog,
                columns=["name", "category", "availability", "kind_hint"],
                headers=["Model", "Category", "Availability", "kind:hint"],
            )
        else:
            print_json(catalog)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@model_app.command("get")
def model_get(
    agent_id: str = typer.Argument(..., help="Agent ID (GUID) or model name"),
):
    """
    Get the current AI model configuration for an agent.

    Reads both model stores used by Copilot Studio:
    1. The bot runtime configuration (`configuration.aISettings.model`)
    2. The Custom GPT botcomponent YAML (componenttype=15)

    The raw `modelKind` / `modelNameHint` fields reflect the stored runtime
    configuration when present. The `resolvedModelId` / `resolvedModelName`
    fields are the CLI's interpretation of what Copilot Studio will show for
    that stored pair.

    Examples:
        copilot agent model get <agent-id>
    """
    try:
        if not _is_guid(agent_id):
            catalog = _fetch_model_catalog()
            for model in catalog:
                if model["name"].casefold() == agent_id.casefold():
                    model["id"] = model["name"]
                    print_json(model)
                    return
            # Fall through to client lookup so tests and any non-GUID bot IDs
            # still resolve through the live agent path.

        client = get_client()
        bot = client.get_bot(agent_id)

        if not bot:
            typer.echo(f"Agent not found: {agent_id}", err=True)
            raise typer.Exit(1)

        runtime_model = client.get_bot_runtime_model(bot)

        # Get the Custom GPT component (componenttype=15) which contains editor model config
        gpt_component = client.get_custom_gpt_component(agent_id)
        component_kind = None
        component_hint = None
        component_id = None
        component_name = None

        if gpt_component:
            yaml_data = gpt_component.get("data", "")
            parsed_config = client.parse_gpt_component_yaml(yaml_data)
            component_kind = parsed_config.get("model_kind")
            component_hint = parsed_config.get("model_hint")
            component_id = gpt_component.get("botcomponentid")
            component_name = gpt_component.get("name")

        runtime_kind = runtime_model.get("model_kind")
        runtime_hint = runtime_model.get("model_hint")
        runtime_resolved = _resolve_stored_model(runtime_kind, runtime_hint)
        component_resolved = _resolve_stored_model(component_kind, component_hint)
        effective_kind = runtime_kind or component_kind
        effective_hint = runtime_hint or component_hint
        effective_source = "runtime" if runtime_kind and runtime_hint else "component"
        effective_resolved = runtime_resolved if effective_source == "runtime" else component_resolved

        if not effective_kind or not effective_hint:
            typer.echo(f"No model configuration found for agent {agent_id}", err=True)
            raise typer.Exit(1)

        synchronization_status = bot.get("synchronizationstatus", {})
        if isinstance(synchronization_status, str):
            try:
                synchronization_status = json.loads(synchronization_status)
            except json.JSONDecodeError:
                synchronization_status = {}

        last_publish = synchronization_status.get("lastFinishedPublishOperation", {})
        current_sync_state = synchronization_status.get("currentSynchronizationState", {})
        issues = []
        issues.extend(runtime_resolved["issues"])
        issues.extend(component_resolved["issues"])
        if last_publish.get("status") == "Failed":
            issues.append("The last publish attempt failed; the live published model may not match the current draft model.")

        result = {
            "id": agent_id,
            "agent_id": agent_id,
            "agent_name": bot.get("name"),
            "resolvedModelId": effective_resolved["modelId"],
            "resolvedModelName": effective_resolved["modelName"],
            "resolvedSource": effective_source,
            "resolvedBy": effective_resolved["resolution"],
            "modelKind": effective_kind,
            "modelNameHint": effective_hint,
            "source": effective_source,
            "runtimeModelKind": runtime_kind,
            "runtimeModelNameHint": runtime_hint,
            "runtimeOptInUseLatestModels": runtime_model.get("opt_in_use_latest_models"),
            "runtimeResolvedModelId": runtime_resolved["modelId"],
            "runtimeResolvedModelName": runtime_resolved["modelName"],
            "runtimeResolution": runtime_resolved["resolution"],
            "runtimeIsKnownPair": runtime_resolved["isKnownPair"],
            "componentModelKind": component_kind,
            "componentModelNameHint": component_hint,
            "componentResolvedModelId": component_resolved["modelId"],
            "componentResolvedModelName": component_resolved["modelName"],
            "componentResolution": component_resolved["resolution"],
            "componentIsKnownPair": component_resolved["isKnownPair"],
            "component_id": component_id,
            "component_name": component_name,
            "syncState": current_sync_state.get("state"),
            "lastPublishOperationStatus": last_publish.get("status"),
            "lastPublishedOnUtc": synchronization_status.get("lastPublishedOnUtc"),
            "mismatch": bool(
                runtime_kind
                and runtime_hint
                and component_kind
                and component_hint
                and (runtime_kind != component_kind or runtime_hint != component_hint)
            ),
            "issues": issues,
        }

        print_json(result)

    except typer.Exit:
        raise
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@model_app.command("set")
def model_set(
    agent_id: str = typer.Argument(..., help="Agent ID (GUID)"),
    model: str = typer.Argument(
        ...,
        help="Model ID or canonical kind:hint (for example: gpt-4.1, gpt-5-chat, DefaultModels:GPT4.1, ChatPreviewModels:GPT5Chat). Use 'copilot agent model list' to see supported models.",
    ),
    publish: bool = typer.Option(
        True,
        "--publish/--no-publish",
        help="Publish the agent after updating (default: True)",
    ),
):
    """
    Set the AI model for an agent.

    Updates both model stores used by Copilot Studio:
    1. The bot runtime configuration (`configuration.aISettings.model`)
    2. The Custom GPT botcomponent YAML (componenttype=15)

    Setting an explicit model also disables `optInUseLatestModels` so the runtime
    does not silently override the selected model.

    Use 'copilot agent model list' to discover models in use across your agents.
    Use 'copilot agent model get <agent-id>' to see an agent's current model.

    Examples:
        copilot agent model set <agent-id> ExternalModels:opus4-1
        copilot agent model set <agent-id> DefaultModels:GPT4.1 --no-publish
        copilot agent model set <agent-id> ReasoningPreviewModels:GPT5Reasoning
    """
    try:
        requested_model = _parse_requested_model(model)
        model_kind = requested_model["kind"]
        model_hint = requested_model["modelNameHint"]
        client = get_client()
        bot = client.get_bot(agent_id)

        if not bot:
            typer.echo(f"Agent not found: {agent_id}", err=True)
            raise typer.Exit(1)

        runtime_model = client.get_bot_runtime_model(bot)

        # Get the Custom GPT component (componenttype=15) which contains editor model config
        gpt_component = client.get_custom_gpt_component(agent_id)
        component_changed = False
        runtime_changed = client.update_bot_model(
            agent_id,
            model_kind=model_kind,
            model_hint=model_hint,
            opt_in_use_latest_models=False,
        )

        if not gpt_component:
            # Create the Custom GPT component with the model settings
            typer.echo(f"Creating Custom GPT component for agent...")
            client.create_custom_gpt_component(
                agent_id,
                model_kind=model_kind,
                model_hint=model_hint,
            )
            component_changed = True
            typer.echo(f"Setting model: {model_kind}:{model_hint}")
        else:
            component_id = gpt_component.get("botcomponentid")

            # Get current config for logging and to preserve instructions
            current_yaml = gpt_component.get("data", "")
            current_config = client.parse_gpt_component_yaml(current_yaml)
            current_hint = (
                runtime_model.get("model_hint")
                or current_config.get("model_hint")
                or "unknown"
            )
            current_instructions = current_config.get("instructions")
            current_response_instructions = current_config.get("response_instructions")
            current_web_browsing = current_config.get("web_browsing")

            typer.echo(f"Updating model: {current_hint} -> {requested_model['modelName']}")

            # Build new YAML with updated model but preserve existing GPT settings.
            build_yaml_kwargs = {
                "instructions": current_instructions,
                "response_instructions": current_response_instructions,
                "model_kind": model_kind,
                "model_hint": model_hint,
                "web_browsing": current_web_browsing,
            }
            supported_yaml_args = set(
                inspect.signature(client.build_gpt_component_yaml).parameters
            )
            new_yaml = client.build_gpt_component_yaml(
                **{
                    key: value
                    for key, value in build_yaml_kwargs.items()
                    if key in supported_yaml_args
                }
            )

            if new_yaml != current_yaml:
                # PATCH the botcomponent with new data
                client.patch(f"botcomponents({component_id})", {"data": new_yaml})
                component_changed = True

        if not runtime_changed and not component_changed:
            typer.echo(f"Agent model already set to: {model_kind}:{model_hint}")
            return

        print_success(
            f"Updated agent model to: {requested_model['modelName']} ({model_kind}:{model_hint})"
        )

        if publish:
            typer.echo("Publishing agent...")
            client.publish_bot(agent_id)
            print_success("Agent published successfully")
        else:
            print_warning("Agent not published. Changes won't be live until published.")

    except typer.Exit:
        raise
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


# Register model subgroup
app.add_typer(model_app, name="model")


# =============================================================================
# Channel Commands
# =============================================================================

channel_app = typer.Typer(help="Manage agent channels")


def _resolve_agent_id(client, agent_id: str) -> tuple[str, dict]:
    """
    Resolve an agent identifier to a bot ID and bot record.

    Accepts either a GUID or a bot name. If the value doesn't look like a GUID,
    searches for a bot by name.

    Args:
        client: DataverseClient instance
        agent_id: GUID or display name of the agent

    Returns:
        Tuple of (resolved_bot_id, bot_record)
    """
    import re

    # Simple GUID check: 8-4-4-4-12 hex pattern
    guid_pattern = re.compile(
        r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
    )

    if guid_pattern.match(agent_id):
        bot = client.get_bot(agent_id)
        return agent_id, bot

    # Search by name
    bots = client.list_bots(
        filter=[f"name:eq:{agent_id}"],
        select=["botid", "name", "schemaname"],
    )
    if not bots:
        typer.echo(f"Error: No agent found with name '{agent_id}'.", err=True)
        raise typer.Exit(1)
    if len(bots) > 1:
        typer.echo(f"Error: Multiple agents found with name '{agent_id}':", err=True)
        for b in bots:
            typer.echo(f"  - {b.get('botid')} ({b.get('name')})", err=True)
        typer.echo("Please use the agent GUID instead.", err=True)
        raise typer.Exit(1)

    bot = bots[0]
    bot_id = bot.get("botid")
    # Fetch full bot record
    full_bot = client.get_bot(bot_id)
    return bot_id, full_bot


@channel_app.command("get-token")
def channel_get_token(
    agent_id: str = typer.Argument(..., help="Agent ID (GUID) or name"),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display as table",
    ),
):
    """
    Get a Direct Line token for an agent.

    Retrieves a short-lived Direct Line token that can be used to start
    conversations with the agent programmatically.

    Examples:
        copilot agent channel get-token <agent-id>
        copilot agent channel get-token "Search Expert" --table
    """
    try:
        client = get_client()
        bot_id, bot = _resolve_agent_id(client, agent_id)

        schema_name = bot.get("schemaname")
        if not schema_name:
            typer.echo(f"Error: Could not get schema name for agent {bot_id}", err=True)
            raise typer.Exit(1)

        token_data = client.get_directline_token(schema_name)

        if table:
            agent_name = bot.get("name", bot_id)
            typer.echo(f"\nDirect Line Token for '{agent_name}':\n")
            typer.echo(f"  Token:           {token_data.get('token', 'N/A')[:40]}...")
            typer.echo(f"  Conversation ID: {token_data.get('conversationId', 'N/A')}")
            typer.echo(f"  Expires In:      {token_data.get('expires_in', 'N/A')} seconds")
            typer.echo("")
        else:
            print_json(token_data)

    except Exception as e:
        if isinstance(e, typer.Exit):
            raise
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@channel_app.command("list")
def channel_list(
    agent_id: str = typer.Argument(..., help="Agent ID (GUID) or name"),
    limit: int = typer.Option(
        100,
        "--limit",
        "-l",
        help="Maximum number of channels to return",
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
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display as table",
    ),
):
    """
    List channels available for an agent.

    Shows configured and available channels including Direct Line, Teams,
    and Web Chat.

    Examples:
        copilot agent channel list <agent-id>
        copilot agent channel list "Search Expert" --table
    """
    try:
        client = get_client()
        bot_id, bot = _resolve_agent_id(client, agent_id)

        channel_info = client.get_bot_channel_info(bot_id)
        channels = channel_info.get("channels", [])

        if filter:
            from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError
            try:
                validate_filters(filter)
                channels = apply_filters(channels, filter)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        channels = channels[:limit]

        if properties:
            property_list = [p.strip() for p in properties.split(",")]
            channels = [
                {k: v for k, v in item.items() if k in property_list}
                for item in channels
            ]
            channel_info = {**channel_info, "channels": channels}

        if table:
            agent_name = channel_info.get("bot_name", bot_id)
            typer.echo(f"\nChannels for '{agent_name}':\n")

            if not channels:
                typer.echo("  No channels found.")
            else:
                rows = []
                for ch in channels:
                    rows.append({
                        "Name": ch.get("name", ""),
                        "Type": ch.get("type", ""),
                        "Status": ch.get("status", ""),
                        "Description": ch.get("description", ""),
                    })
                print_table(rows)
            typer.echo("")
        else:
            print_json(channel_info)

    except Exception as e:
        if isinstance(e, typer.Exit):
            raise
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@channel_app.command("get")
def channel_get(
    agent_id: str = typer.Argument(..., help="Agent ID (GUID) or name"),
    channel_name: str = typer.Argument(..., help="Channel name (e.g., 'directline', 'msteams')"),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Display as table",
    ),
):
    """
    Get details for a specific channel of an agent.

    Examples:
        copilot agent channel get <agent-id> directline
        copilot agent channel get "Search Expert" msteams --table
    """
    try:
        client = get_client()
        bot_id, bot = _resolve_agent_id(client, agent_id)

        channel_info = client.get_bot_channel_info(bot_id)
        channels = channel_info.get("channels", [])

        target = channel_name.lower()
        match = next(
            (ch for ch in channels if ch.get("name", "").lower() == target
             or ch.get("type", "").lower() == target),
            None,
        )
        if match is None:
            print_error(
                f"Channel '{channel_name}' not found for agent '{bot_id}'. "
                f"Use 'copilot agent channel list {agent_id}' to see available channels."
            )
            raise typer.Exit(1)

        if table:
            agent_name = channel_info.get("bot_name", bot_id)
            typer.echo(f"\nChannel '{match.get('name', channel_name)}' for '{agent_name}':\n")
            print_table([{
                "Name": match.get("name", ""),
                "Type": match.get("type", ""),
                "Status": match.get("status", ""),
                "Description": match.get("description", ""),
            }])
            typer.echo("")
        else:
            print_json(match)

    except Exception as e:
        if isinstance(e, typer.Exit):
            raise
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


# Register channel subgroup
app.add_typer(channel_app, name="channel")
