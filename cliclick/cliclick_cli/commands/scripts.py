"""Script management commands for cliclick CLI wrapper."""
import sys
from typing import List, Optional

import typer

from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import handle_error, print_error, print_json, print_success, print_table

from ..client import get_client, ClientError

app = typer.Typer(help="Manage automation scripts", no_args_is_help=True)


@app.command("list")
def scripts_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of scripts to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
):
    """
    List all automation scripts.

    Scripts are stored as .cliclick files in the package's scripts directory.

    Example:
        cliclick scripts list
        cliclick scripts list --table
        cliclick scripts list --filter "name:test"
    """
    try:
        client = get_client()
        scripts = client.list_scripts(limit=limit)

        # Convert to dicts for filtering/output
        data = [s.model_dump() for s in scripts]

        # Apply filters if provided
        if filter:
            data = apply_filters(data, filter)

        # Filter properties if requested
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            data = [{k: v for k, v in item.items() if k in fields} for item in data]

        if table:
            if data:
                columns = list(data[0].keys())
                headers = [c.replace("_", " ").title() for c in columns]
                print_table(data, columns, headers)
            else:
                print_error("No scripts found")
        else:
            print_json(data)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def scripts_get(
    name: str = typer.Argument(..., help="Script name (without .cliclick extension)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    content: bool = typer.Option(False, "--content", "-c", help="Show script content"),
):
    """
    Get script details.

    Example:
        cliclick scripts get my-script
        cliclick scripts get my-script --content
    """
    try:
        client = get_client()
        script = client.get_script(name)

        data = script.model_dump()

        # Add content if requested
        if content:
            from pathlib import Path
            data["content"] = Path(script.path).read_text()

        if table:
            rows = [{"field": k, "value": str(v)} for k, v in data.items()]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(data)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def scripts_create(
    name: str = typer.Argument(..., help="Script name (without .cliclick extension)"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Script description"),
    content: Optional[str] = typer.Option(None, "--content", "-c", help="Script content (commands, one per line)"),
):
    """
    Create a new automation script.

    Provide content via --content or pipe from stdin.

    Example:
        cliclick scripts create my-script --content "c:100,200\nw:500\nt:hello"
        echo "c:100,200" | cliclick scripts create my-script --description "Click test"
    """
    try:
        client = get_client()

        # Get content from stdin if not provided
        if content is None:
            if sys.stdin.isatty():
                print_error("Provide script content via --content or pipe from stdin")
                raise typer.Exit(1)
            content = sys.stdin.read()

        # Handle escaped newlines in content
        content = content.replace("\\n", "\n")

        script = client.create_script(name, content, description=description)
        print_success(f"Created script: {name}")
        print_json(script.model_dump())

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("run")
def scripts_run(
    name: str = typer.Argument(..., help="Script name (without .cliclick extension)"),
    var: Optional[List[str]] = typer.Option(None, "--var", help="Template variable (e.g., --var x=100)"),
    verbose: bool = typer.Option(False, "--verbose", "-V", help="Verbose output from cliclick"),
    test: bool = typer.Option(False, "--test", "-T", help="Test mode (no actual execution)"),
    no_restore: bool = typer.Option(False, "--no-restore", help="Don't restore mouse position"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Run an automation script.

    Template variables in the script ({{var}}) are replaced with values
    provided via --var flags.

    Example:
        cliclick scripts run my-script
        cliclick scripts run my-script --test
        cliclick scripts run click-template --var x=100 --var y=200
    """
    try:
        client = get_client()

        # Parse variables
        variables = {}
        if var:
            for v in var:
                if "=" in v:
                    key, value = v.split("=", 1)
                    variables[key.strip()] = value.strip()
                else:
                    print_error(f"Invalid variable format: {v} (use key=value)")
                    raise typer.Exit(1)

        result = client.run_script(
            name,
            variables=variables if variables else None,
            verbose=verbose,
            test_mode=test,
            restore=not no_restore,
        )

        if table:
            rows = [
                {"field": "success", "value": str(result.success)},
                {"field": "commands_executed", "value": str(result.commands_executed)},
                {"field": "duration_ms", "value": f"{result.duration_ms:.2f}" if result.duration_ms else "N/A"},
            ]
            if result.output:
                rows.append({"field": "output", "value": result.output[:60]})
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(result.model_dump())

        if not result.success:
            raise typer.Exit(1)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("run-stdin")
def scripts_run_stdin(
    verbose: bool = typer.Option(False, "--verbose", "-V", help="Verbose output from cliclick"),
    test: bool = typer.Option(False, "--test", "-T", help="Test mode (no actual execution)"),
    no_restore: bool = typer.Option(False, "--no-restore", help="Don't restore mouse position"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Run cliclick commands from stdin.

    Example:
        echo "c:100,200\nw:500" | cliclick scripts run-stdin
        cat commands.cliclick | cliclick scripts run-stdin --test
    """
    try:
        if sys.stdin.isatty():
            print_error("No input from stdin. Pipe commands to this command.")
            raise typer.Exit(1)

        commands = sys.stdin.read()
        client = get_client()

        result = client.run_stdin(
            commands,
            verbose=verbose,
            test_mode=test,
            restore=not no_restore,
        )

        if table:
            rows = [
                {"field": "success", "value": str(result.success)},
                {"field": "commands_executed", "value": str(result.commands_executed)},
                {"field": "duration_ms", "value": f"{result.duration_ms:.2f}" if result.duration_ms else "N/A"},
            ]
            if result.output:
                rows.append({"field": "output", "value": result.output[:60]})
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(result.model_dump())

        if not result.success:
            raise typer.Exit(1)

    except ClientError as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def scripts_delete(
    name: str = typer.Argument(..., help="Script name (without .cliclick extension)"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
):
    """
    Delete an automation script.

    Example:
        cliclick scripts delete my-script
        cliclick scripts delete my-script --yes
    """
    try:
        client = get_client()

        # Confirm deletion unless --yes is provided
        if not yes:
            confirm = typer.confirm(f"Delete script '{name}'?")
            if not confirm:
                print_error("Cancelled")
                raise typer.Exit(0)

        client.delete_script(name)
        print_success(f"Deleted script: {name}")

    except ClientError as e:
        raise typer.Exit(handle_error(e))
