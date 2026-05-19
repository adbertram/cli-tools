"""Convert command - convert a CLI tool into an n8n node package."""
import typer
from typing import Optional

from ..client import get_client
from ..output import print_json, print_success, handle_error


def convert_cli_tool(
    cli_name: str = typer.Argument(..., help="CLI tool name to convert"),
    output_dir: Optional[str] = typer.Option(None, "--output-dir", "-o", help="Override output directory"),
    force: bool = typer.Option(False, "--force", "-F", help="Overwrite existing package"),
):
    """
    Convert a CLI tool into an n8n community node package.

    Parses the CLI tool's commands, parameters, and credentials, then generates
    a complete n8n node package with TypeScript source, credentials, README, and
    a bundled copy of the CLI tool source (under cli/). The CLI venv is created
    on the server during deploy.

    Example:
        n8n-node convert-cli-tool brickowl
        n8n-node convert-cli-tool shippo --output-dir ./output
        n8n-node convert-cli-tool brickowl --force
    """
    try:
        client = get_client()
        pkg_path = client.generate(cli_name, output_dir=output_dir, force=force)
        print_success(f"Generated n8n node package at: {pkg_path}")

        metadata = client.get_tool(cli_name)
        total_ops = sum(len(g.commands) for g in metadata.command_groups)

        # Build PascalCase name for the icon path
        pascal_name = "".join(w.title() for w in cli_name.replace("-", "_").split("_"))
        icon_path = f"{pkg_path}/nodes/{pascal_name}/{cli_name}.svg"

        summary = {
            "package": f"n8n-nodes-{cli_name}",
            "path": pkg_path,
            "resources": len(metadata.command_groups),
            "operations": total_ops,
            "credentials": len(metadata.credentials),
            "pending_tasks": [
                {
                    "task": "Add SVG icon",
                    "description": (
                        f"The node references icon 'file:{cli_name}.svg' but no SVG exists yet. "
                        f"Download the official {metadata.display_name} logo as SVG, or create a simple SVG icon. "
                        f"Place it at: {icon_path}"
                    ),
                    "target_path": icon_path,
                },
            ],
        }
        print_json(summary)

    except Exception as e:
        raise typer.Exit(handle_error(e))
