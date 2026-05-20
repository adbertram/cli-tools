"""Prompt commands for managing AI Builder prompts available as agent tools."""
import typer
from typing import Optional

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, print_success, handle_error
from ..permissions import create_permissions_app


app = typer.Typer(help="Manage AI Builder prompts (available as agent tools)")

COMMAND_CREDENTIALS = {
    "auth": [
        "custom"
    ],
    "create": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ],
    "permissions": [
        "custom"
    ],
    "publish": [
        "custom"
    ],
    "remove": [
        "custom"
    ],
    "run": [
        "custom"
    ],
    "update": [
        "custom"
    ]
}

# Add permissions subcommand group
permissions_app = create_permissions_app("prompt")
app.add_typer(permissions_app, name="permissions", help="Manage prompt permissions")

# GptPowerPrompt template ID - identifies AI Builder prompts
GPT_POWER_PROMPT_TEMPLATE_ID = "edfdb190-3791-45d8-9a6c-8f90a37c278a"

# AI Configuration status code mapping (msdyn_aiconfiguration.statuscode)
AI_CONFIG_STATUS_MAP = {
    0: "Draft",
    1: "Training",
    2: "Trained",
    3: "TrainingFailed",
    4: "Unpublishing",
    5: "Unpublished",
    6: "Validating",
    7: "Published",
    8: "Scheduling",
    9: "Scheduled",
    10: "PublishFailed",
    11: "Unscheduling",
}

# AI Model state code mapping (msdyn_aimodel.statecode)
AI_MODEL_STATE_MAP = {
    0: "Inactive",
    1: "Active",
}


def get_friendly_status(status_code: int) -> str:
    """Get friendly status name from status code."""
    return AI_CONFIG_STATUS_MAP.get(status_code, f"Unknown ({status_code})")


def get_friendly_state(state_code: int) -> str:
    """Get friendly state name from state code."""
    return AI_MODEL_STATE_MAP.get(state_code, f"Unknown ({state_code})")


def format_prompt_for_display(prompt: dict) -> dict:
    """Format a prompt for display."""
    name = prompt.get("msdyn_name", "")
    prompt_id = prompt.get("msdyn_aimodelid", "")

    # Determine type (Custom vs System based on ismanaged)
    is_managed = prompt.get("ismanaged", False)
    prompt_type = "System" if is_managed else "Custom"

    # Get state (use helper for consistent mapping)
    state_code = prompt.get("statecode", 0)
    state = get_friendly_state(state_code)

    # Get owner
    owner = prompt.get("_ownerid_value@OData.Community.Display.V1.FormattedValue", "")

    # Get created/modified dates
    created = prompt.get("createdon", "")
    if created:
        created = created.split("T")[0]  # Just the date part

    modified = prompt.get("modifiedon", "")
    if modified:
        modified = modified.split("T")[0]

    return {
        "name": name,
        "type": prompt_type,
        "id": prompt_id,
        "state": state,
        "owner": owner,
        "created": created,
        "modified": modified,
    }


@app.command("list")
def prompt_list(
    custom: bool = typer.Option(
        False,
        "--custom",
        "-c",
        help="Show only custom (user-created) prompts",
    ),
    system: bool = typer.Option(
        False,
        "--system",
        "-s",
        help="Show only system (managed) prompts",
    ),
    filter: Optional[list[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter: field:op:value (e.g., name:ilike:%classify%)",
    ),
    limit: int = typer.Option(
        100,
        "--limit",
        "-l",
        help="Maximum number of prompts to return",
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
    List all AI Builder prompts available as agent tools.

    AI Builder prompts are custom prompts that can be attached to
    Copilot Studio agents as tools. They use GPT models to perform
    specific tasks like classification, extraction, or content generation.

    Prompt Types:
      - Custom: User-created prompts in the environment
      - System: Built-in Microsoft prompts (AI Classify, AI Summarize, etc.)

    Examples:
        copilot prompt list
        copilot prompt list --table
        copilot prompt list --custom --table
        copilot prompt list --system --table
        copilot prompt list --filter "name:ilike:%classify%" --table
        copilot prompt list --limit 50
        copilot prompt list --properties "name,id,type"
    """
    from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError

    if custom and system:
        typer.echo("Error: Cannot specify both --custom and --system", err=True)
        raise typer.Exit(1)

    try:
        client = get_client()
        prompts = client.list_prompts()

        if not prompts:
            use_table = table or output == "table"
            if use_table:
                typer.echo("No prompts found.")
            else:
                print_json([])
            return

        # Filter by custom/system
        if custom:
            prompts = [p for p in prompts if not p.get("ismanaged", False)]
        elif system:
            prompts = [p for p in prompts if p.get("ismanaged", False)]

        # Apply filters using standard field:op:value syntax
        if filter:
            try:
                validate_filters(filter)
                prompts = apply_filters(prompts, filter)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        if not prompts:
            use_table = table or output == "table"
            if use_table:
                typer.echo("No prompts match the filter criteria.")
            else:
                print_json([])
            return

        # Apply limit
        prompts = prompts[:limit]

        formatted = [format_prompt_for_display(p) for p in prompts]

        # Sort by name
        formatted.sort(key=lambda x: x["name"].lower())

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
                    columns=["name", "type", "state", "owner", "modified", "id"],
                    headers=["Name", "Type", "State", "Owner", "Modified", "ID"],
                )
        else:
            print_json(formatted)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("create")
def prompt_create(
    name: str = typer.Argument(
        ...,
        help="Display name for the prompt",
    ),
    text: Optional[str] = typer.Option(
        None,
        "--text",
        "-t",
        help="The prompt instruction text",
    ),
    text_file: Optional[str] = typer.Option(
        None,
        "--file",
        "-f",
        help="Read prompt text from a file",
    ),
    input_def: Optional[list[str]] = typer.Option(
        None,
        "--input",
        "-i",
        help="Define an input: ID[:TYPE] (e.g., 'content' or 'content:text'). Can be repeated.",
    ),
    content_input: bool = typer.Option(
        False,
        "--content",
        "-c",
        help="Add a 'content' text input (shorthand for -i content:text)",
    ),
    model: str = typer.Option(
        "gpt-41-mini",
        "--model",
        "-m",
        help="Model type (gpt-41-mini, gpt-41, gpt-5-chat, gpt-5-reasoning)",
    ),
    temperature: Optional[float] = typer.Option(
        None,
        "--temperature",
        "-T",
        help="Model temperature (0.0-1.0). Default: 0",
    ),
    max_tokens: Optional[int] = typer.Option(
        None,
        "--max-tokens",
        help="Maximum tokens in response. Default: 2000",
    ),
    top_p: Optional[float] = typer.Option(
        None,
        "--top-p",
        help="Top-p (nucleus) sampling (0.0-1.0). Default: 1.0",
    ),
    response_format: str = typer.Option(
        "text",
        "--response-format",
        "-r",
        help="Response format (text or json)",
    ),
):
    """
    Create a new AI Builder prompt.

    Creates a prompt that can be used as a tool in Copilot Studio agents.
    The prompt text can be provided directly via --text or read from a file
    via --file.

    Input variables can be defined using --input. Each input has an ID and
    optional type (text or document). Use placeholders like {{content}} in
    your prompt text to reference inputs.

    Use --content as a shorthand to add a standard 'content' text input.

    Examples:
        copilot prompt create "Classify Content" --file prompt.txt --content

        copilot prompt create "Classify" --text "Classify: {{content}}" -i content

        copilot prompt create "Summarize" --file prompt.txt -i document:document

        copilot prompt create "Extract" --file extract.txt --content --temperature 0.7
    """
    # Validate input
    if not text and not text_file:
        typer.echo("Error: Must provide --text or --file", err=True)
        raise typer.Exit(1)

    if text and text_file:
        typer.echo("Error: Cannot specify both --text and --file", err=True)
        raise typer.Exit(1)

    # Validate temperature
    if temperature is not None and (temperature < 0.0 or temperature > 1.0):
        typer.echo("Error: Temperature must be between 0.0 and 1.0", err=True)
        raise typer.Exit(1)

    # Validate top_p
    if top_p is not None and (top_p < 0.0 or top_p > 1.0):
        typer.echo("Error: Top-p must be between 0.0 and 1.0", err=True)
        raise typer.Exit(1)

    # Validate max_tokens
    if max_tokens is not None and max_tokens < 1:
        typer.echo("Error: Max tokens must be at least 1", err=True)
        raise typer.Exit(1)

    # Read prompt text from file if specified
    prompt_text = text
    if text_file:
        try:
            with open(text_file, "r") as f:
                prompt_text = f.read()
        except FileNotFoundError:
            typer.echo(f"Error: File not found: {text_file}", err=True)
            raise typer.Exit(1)
        except IOError as e:
            typer.echo(f"Error reading file: {e}", err=True)
            raise typer.Exit(1)

    # Parse input definitions
    inputs = []

    # Add content input if --content flag is set
    if content_input:
        inputs.append({
            "id": "content",
            "displayName": "Content",
            "type": "text",
        })

    # Add inputs from --input options
    if input_def:
        for inp in input_def:
            if ":" in inp:
                input_id, input_type = inp.split(":", 1)
            else:
                input_id = inp
                input_type = "text"

            if input_type not in ("text", "document"):
                typer.echo(f"Error: Invalid input type '{input_type}'. Must be 'text' or 'document'", err=True)
                raise typer.Exit(1)

            # Skip if already added via --content
            if input_id.strip() == "content" and content_input:
                continue

            inputs.append({
                "id": input_id.strip(),
                "displayName": input_id.strip().title(),
                "type": input_type.strip(),
            })

    # Validate response format
    if response_format not in ("text", "json"):
        typer.echo(f"Error: Invalid response format '{response_format}'. Must be 'text' or 'json'", err=True)
        raise typer.Exit(1)

    try:
        client = get_client()

        typer.echo(f"Creating prompt '{name}'...")

        result = client.create_prompt(
            name=name,
            prompt_text=prompt_text,
            inputs=inputs if inputs else None,
            model_type=model,
            temperature=temperature,
            max_tokens=max_tokens,
            top_p=top_p,
            response_format=response_format,
        )

        print_success(f"Created prompt '{name}'")
        typer.echo(f"  ID: {result['model_id']}")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("remove")
def prompt_remove(
    prompt_id: str = typer.Argument(
        ...,
        help="The prompt's unique identifier (GUID)",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Skip confirmation prompt",
    ),
):
    """
    Remove a custom prompt from the environment.

    Permanently deletes a custom AI Builder prompt. This action cannot be undone.
    System (managed) prompts cannot be deleted.

    Examples:
        copilot prompt remove 12345678-1234-1234-1234-123456789abc
        copilot prompt remove 12345678-1234-1234-1234-123456789abc --force
    """
    try:
        client = get_client()

        # Get prompt info for confirmation
        prompt = client.get_prompt(prompt_id)
        prompt_name = prompt.get("msdyn_name", prompt_id)

        # Check if managed (system prompt)
        if prompt.get("ismanaged", False):
            typer.echo("Error: Cannot delete system/managed prompts.", err=True)
            raise typer.Exit(1)

        # Confirm deletion
        if not force:
            typer.confirm(
                f"Are you sure you want to delete prompt '{prompt_name}'? This cannot be undone.",
                abort=True,
            )

        # Delete the prompt
        client.delete_prompt(prompt_id)
        print_success(f"Deleted prompt '{prompt_name}'")

    except typer.Abort:
        typer.echo("Aborted.")
        raise typer.Exit(0)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("get")
def prompt_get(
    prompt_id: str = typer.Argument(
        ...,
        help="The prompt's unique identifier (GUID)",
    ),
    show_text: bool = typer.Option(
        False,
        "--text",
        "-t",
        help="Show the prompt text content instead of raw metadata",
    ),
    table: bool = typer.Option(
        False,
        "--table",
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
    Get details for a specific prompt.

    Examples:
        copilot prompt get 12345678-1234-1234-1234-123456789abc
        copilot prompt get 12345678-1234-1234-1234-123456789abc --text
        copilot prompt get 12345678-1234-1234-1234-123456789abc --table
    """
    try:
        client = get_client()

        use_table = table or output == "table"

        if show_text:
            # Get the prompt configuration with actual prompt text
            config = client.get_prompt_configuration(prompt_id)
            # Add friendly status name
            status_code = config.get("status", 0)
            config["status_name"] = get_friendly_status(status_code)
            print_json(config)
        else:
            # Get the raw prompt metadata
            prompt = client.get_prompt(prompt_id)
            # Add friendly state name
            state_code = prompt.get("statecode", 0)
            prompt["state_name"] = get_friendly_state(state_code)

            if use_table:
                formatted = format_prompt_for_display(prompt)
                print_table(
                    [formatted],
                    columns=["name", "type", "state", "owner", "modified", "id"],
                    headers=["Name", "Type", "State", "Owner", "Modified", "ID"],
                )
            else:
                print_json(prompt)
    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("update")
def prompt_update(
    prompt_id: str = typer.Argument(
        ...,
        help="The prompt's unique identifier (GUID)",
    ),
    text: Optional[str] = typer.Option(
        None,
        "--text",
        "-t",
        help="New prompt text (replaces existing prompt text)",
    ),
    text_file: Optional[str] = typer.Option(
        None,
        "--file",
        "-f",
        help="Read prompt text from a file",
    ),
    model: Optional[str] = typer.Option(
        None,
        "--model",
        "-m",
        help="Model type (gpt-41-mini, gpt-41, gpt-5-chat, gpt-5-reasoning)",
    ),
    temperature: Optional[float] = typer.Option(
        None,
        "--temperature",
        "-T",
        help="Model temperature (0.0-1.0) for controlling response randomness",
    ),
    input_type: Optional[list[str]] = typer.Option(
        None,
        "--input-type",
        "-i",
        help="Change input type: INPUT_ID=TYPE (e.g., content=text). Valid types: text, document. Can be repeated.",
    ),
    code_interpreter: Optional[bool] = typer.Option(
        None,
        "--code-interpreter",
        "-C",
        help="Enable or disable code interpreter for this prompt (true/false)",
    ),
    no_publish: bool = typer.Option(
        False,
        "--no-publish",
        help="Skip republishing after update (changes won't be live)",
    ),
):
    """
    Update an AI Builder prompt's text, model, temperature, input types, or code interpreter setting.

    The prompt text can be provided directly via --text or read from a file
    via --file. Input variables from the original prompt are preserved.

    Input types can be changed using --input-type. This is useful when the
    prompt receives plain text but the input was mistakenly configured as
    "document" type (which requires mimetype information).

    Code interpreter enables Python code execution for data analysis and
    file processing. When enabled, prompts can be invoked via the Dataverse
    Predict API. Standard prompts (without code interpreter) can only be
    run through Power Automate flows.

    By default, the prompt is automatically republished after updating.
    Use --no-publish to skip republishing.

    Examples:
        copilot prompt update <id> --text "Classify this content into categories..."
        copilot prompt update <id> --file prompt.txt
        copilot prompt update <id> --model gpt-4o
        copilot prompt update <id> --temperature 0.5
        copilot prompt update <id> --input-type content=text
        copilot prompt update <id> -i content=text -i summary=document
        copilot prompt update <id> --file prompt.txt --model gpt-4o
        copilot prompt update <id> --file prompt.txt --no-publish
        copilot prompt update <id> --code-interpreter   # Enable code interpreter
    """
    # Validate input
    if text and text_file:
        typer.echo("Error: Cannot specify both --text and --file", err=True)
        raise typer.Exit(1)

    if not text and not text_file and not model and temperature is None and not input_type and code_interpreter is None:
        typer.echo("Error: Must provide --text, --file, --model, --temperature, --input-type, or --code-interpreter", err=True)
        raise typer.Exit(1)

    # Validate temperature range
    if temperature is not None and (temperature < 0.0 or temperature > 1.0):
        typer.echo("Error: Temperature must be between 0.0 and 1.0", err=True)
        raise typer.Exit(1)

    # Read prompt text from file if specified
    prompt_text = text
    if text_file:
        try:
            with open(text_file, "r") as f:
                prompt_text = f.read()
        except FileNotFoundError:
            typer.echo(f"Error: File not found: {text_file}", err=True)
            raise typer.Exit(1)
        except IOError as e:
            typer.echo(f"Error reading file: {e}", err=True)
            raise typer.Exit(1)

    # Parse input type options (format: INPUT_ID=TYPE)
    input_types = None
    if input_type:
        input_types = {}
        for it in input_type:
            if "=" not in it:
                typer.echo(f"Error: Invalid --input-type format '{it}'. Expected: INPUT_ID=TYPE", err=True)
                raise typer.Exit(1)
            input_id, type_value = it.split("=", 1)
            input_types[input_id.strip()] = type_value.strip()

    try:
        client = get_client()

        # Get prompt name for confirmation message
        prompt_info = client.get_prompt(prompt_id)
        prompt_name = prompt_info.get("msdyn_name", prompt_id)

        typer.echo(f"Updating prompt '{prompt_name}'...")

        # Update the prompt (handles unpublish/update/republish workflow)
        client.update_prompt(
            prompt_id,
            prompt_text=prompt_text,
            model_type=model,
            temperature=temperature,
            input_types=input_types,
            code_interpreter=code_interpreter,
            publish=not no_publish
        )

        # Build update summary
        updates = []
        if prompt_text:
            updates.append("prompt text")
        if model:
            updates.append(f"model type ({model})")
        if temperature is not None:
            updates.append(f"temperature ({temperature})")
        if input_types:
            type_changes = [f"{k}={v}" for k, v in input_types.items()]
            updates.append(f"input types ({', '.join(type_changes)})")
        if code_interpreter is not None:
            updates.append(f"code interpreter ({'enabled' if code_interpreter else 'disabled'})")

        if no_publish:
            print_success(f"Updated {', '.join(updates)} for prompt '{prompt_name}' (not published)")
            typer.echo("\nUse AI Builder to publish when ready.")
        else:
            print_success(f"Updated and published {', '.join(updates)} for prompt '{prompt_name}'")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("publish")
def prompt_publish(
    prompt_id: str = typer.Argument(
        ...,
        help="The prompt's unique identifier (GUID)",
    ),
):
    """
    Publish an AI Builder prompt to make it available for use.

    Prompts must be published before they can be used in flows or agents.
    This command publishes an unpublished prompt configuration.

    Examples:
        copilot prompt publish 12345678-1234-1234-1234-123456789abc
    """
    try:
        client = get_client()

        # Get prompt name for confirmation message
        prompt_info = client.get_prompt(prompt_id)
        prompt_name = prompt_info.get("msdyn_name", prompt_id)

        typer.echo(f"Publishing prompt '{prompt_name}'...")

        result = client.publish_prompt(prompt_id)

        if result.get("status") == "already_published":
            typer.echo(f"Prompt '{prompt_name}' is already published")
        else:
            print_success(f"Prompt '{prompt_name}' published successfully")

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)


@app.command("run")
def prompt_run(
    prompt_id: str = typer.Argument(
        ...,
        help="The prompt's unique identifier (GUID)",
    ),
    input_values: Optional[list[str]] = typer.Option(
        None,
        "--input",
        "-i",
        help="Input value: NAME=VALUE (can be repeated). Example: -i content='Hello world'",
    ),
    input_file: Optional[str] = typer.Option(
        None,
        "--input-file",
        "-f",
        help="Read input value from file: NAME=@FILEPATH. Content becomes the input value.",
    ),
    json_input: Optional[str] = typer.Option(
        None,
        "--json",
        "-j",
        help="JSON object with input values: '{\"content\": \"value\"}'",
    ),
    background: bool = typer.Option(
        False,
        "--background",
        "-b",
        help="Run asynchronously and return immediately with polling info",
    ),
    timeout: float = typer.Option(
        300.0,
        "--timeout",
        "-T",
        help="Maximum seconds to wait for completion (default: 300)",
    ),
    raw: bool = typer.Option(
        False,
        "--raw",
        "-r",
        help="Output raw API response instead of formatted result",
    ),
    show_inputs: bool = typer.Option(
        False,
        "--show-inputs",
        help="Show the prompt's expected inputs and exit (no execution)",
    ),
):
    """
    Run an AI Builder prompt with the specified inputs.

    Executes the prompt using the Dataverse Predict API and returns
    the generated response. Requires the prompt to be published.

    IMPORTANT: This command currently works best with code-interpreter-enabled
    prompts. Standard GPT prompts may encounter "Source is null" errors due to
    undocumented API requirements. For standard prompts, use Power Automate
    flows or Power Apps as the execution environment.

    Input Methods:
      - Use -i NAME=VALUE for simple text inputs
      - Use -f NAME=@FILEPATH to read input from a file
      - Use -j '{"name": "value"}' for JSON input
      - Combine methods: -i category=news -f content=@article.txt

    Background Execution:
      Use --background to run asynchronously. Returns polling information
      that can be used to check status later. Useful for long-running prompts.

    Examples:
        # Simple text input
        copilot prompt run <id> -i content="Classify this text"

        # Read content from file
        copilot prompt run <id> -f content=@document.txt

        # Multiple inputs
        copilot prompt run <id> -i category=news -i content="Article text..."

        # JSON input
        copilot prompt run <id> -j '{"content": "Hello", "format": "brief"}'

        # Background execution
        copilot prompt run <id> -i content="Long text..." --background

        # Show expected inputs
        copilot prompt run <id> --show-inputs
    """
    try:
        client = get_client()

        # Handle --show-inputs flag
        if show_inputs:
            prompt_inputs = client.get_prompt_inputs(prompt_id)
            if not prompt_inputs:
                typer.echo("This prompt has no defined inputs.")
            else:
                typer.echo("Expected inputs:")
                for inp in prompt_inputs:
                    input_id = inp.get("id", "unknown")
                    input_type = inp.get("type", "text")
                    display_name = inp.get("displayName", input_id)
                    description = inp.get("description", "")

                    line = f"  - {input_id} ({input_type})"
                    if display_name != input_id:
                        line += f" [{display_name}]"
                    if description:
                        line += f": {description}"
                    typer.echo(line)
            return

        # Build inputs dictionary from various sources
        inputs = {}

        # Parse JSON input first (lowest priority - can be overridden)
        if json_input:
            import json as json_module
            try:
                json_inputs = json_module.loads(json_input)
                if not isinstance(json_inputs, dict):
                    typer.echo("Error: --json must be a JSON object", err=True)
                    raise typer.Exit(1)
                inputs.update(json_inputs)
            except json_module.JSONDecodeError as e:
                typer.echo(f"Error: Invalid JSON input: {e}", err=True)
                raise typer.Exit(1)

        # Parse file inputs (middle priority)
        if input_file:
            if "=@" not in input_file:
                typer.echo("Error: --input-file format must be NAME=@FILEPATH", err=True)
                raise typer.Exit(1)
            name, filepath = input_file.split("=@", 1)
            try:
                with open(filepath, "r") as f:
                    inputs[name.strip()] = f.read()
            except FileNotFoundError:
                typer.echo(f"Error: File not found: {filepath}", err=True)
                raise typer.Exit(1)
            except IOError as e:
                typer.echo(f"Error reading file: {e}", err=True)
                raise typer.Exit(1)

        # Parse command-line inputs (highest priority)
        if input_values:
            for inp in input_values:
                if "=" not in inp:
                    typer.echo(f"Error: Invalid input format '{inp}'. Expected NAME=VALUE", err=True)
                    raise typer.Exit(1)
                name, value = inp.split("=", 1)

                # Handle file reference in -i as well (e.g., -i content=@file.txt)
                if value.startswith("@"):
                    filepath = value[1:]
                    try:
                        with open(filepath, "r") as f:
                            value = f.read()
                    except FileNotFoundError:
                        typer.echo(f"Error: File not found: {filepath}", err=True)
                        raise typer.Exit(1)
                    except IOError as e:
                        typer.echo(f"Error reading file: {e}", err=True)
                        raise typer.Exit(1)

                inputs[name.strip()] = value

        if not inputs:
            typer.echo("Error: No inputs provided. Use -i, -f, or -j to specify inputs.", err=True)
            typer.echo("Use --show-inputs to see expected inputs for this prompt.", err=True)
            raise typer.Exit(1)

        # Run the prompt
        if not background:
            typer.echo("Running prompt...", err=True)

        result = client.run_prompt(
            prompt_id=prompt_id,
            inputs=inputs,
            wait=not background,
            timeout=timeout,
        )

        # Output the result
        if raw:
            print_json(result.get("raw_response", result))
        elif result.get("status") == "Pending":
            # Background execution - show polling info
            output = {
                "status": "Pending",
                "message": "Prompt execution started in background",
                "poll_url": result.get("poll_url", ""),
                "retry_after": result.get("retry_after", 2.0),
            }
            print_json(output)
        elif result.get("status") == "Success":
            # Successful execution - output the text
            text = result.get("text", "")
            mimetype = result.get("mimetype", "")

            if mimetype in ("application/json", "text/json"):
                # Try to parse and pretty-print JSON response
                import json as json_module
                try:
                    parsed = json_module.loads(text)
                    print_json(parsed)
                except json_module.JSONDecodeError:
                    print(text)
            else:
                print(text)

            # Show additional info if present
            if result.get("files"):
                typer.echo(f"\n[{len(result['files'])} file(s) generated]", err=True)
            if result.get("code"):
                typer.echo("\n[Code execution performed]", err=True)
        else:
            # Other status - output full result
            print_json(result)

    except Exception as e:
        exit_code = handle_error(e)
        raise typer.Exit(exit_code)
