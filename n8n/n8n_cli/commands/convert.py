"""Convert command - convert a CLI tool into an n8n node package."""
import typer
from typing import Optional

from ..client import get_client
from cli_tools_shared.output import print_error, print_json, print_success, handle_error


def _check_node_name_collision(effective_name: str) -> None:
    """Check if the generated node name would collide with a built-in n8n node.

    Queries the n8n server for default nodes and compares short names.
    Raises typer.Exit(1) on collision. Silently returns if the server is
    unreachable (offline/not configured).
    """
    from ..n8n_api import get_n8n_api_client, N8nApiError

    # Build the camelCase name the same way generator.py does
    pascal = "".join(w.title() for w in effective_name.replace("-", "_").split("_"))
    camel = pascal[0].lower() + pascal[1:] if pascal else ""

    try:
        api = get_n8n_api_client()
        default_nodes = api.list_nodes(node_type="default")
    except (N8nApiError, Exception):
        return  # Server unreachable — skip check

    for node in default_nodes:
        full_name = node.get("name", "")
        # Extract short name (part after last dot, e.g., "n8n" from "n8n-nodes-base.n8n")
        short_name = full_name.rsplit(".", 1)[-1] if "." in full_name else full_name
        if short_name == camel:
            print_error(
                f"Name collision: built-in node '{full_name}' uses name '{camel}'. "
                f"Use --name to pick a different name (e.g., --name {effective_name}-manager)"
            )
            raise typer.Exit(1)


def convert_cli_tool(
    cli_name: str = typer.Argument(..., help="CLI tool name to convert"),
    output_dir: Optional[str] = typer.Option(None, "--output-dir", "-o", help="Override output directory"),
    force: bool = typer.Option(False, "--force", "-F", help="Overwrite existing package"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="Override package/node name (avoids name conflicts)"),
    display_name: Optional[str] = typer.Option(None, "--display-name", "-d", help="Override display name in n8n UI"),
):
    """
    Convert a CLI tool into an n8n community node package.

    Parses the CLI tool's commands, parameters, and credentials, then generates
    a complete n8n node package with TypeScript source, credentials, README, and
    a bundled copy of the CLI tool source (under cli/). The CLI venv is created
    on the server during deploy.

    Example:
        n8n nodes create brickowl
        n8n nodes create shippo --output-dir ./output
        n8n nodes create brickowl --force
        n8n nodes create slack --name slack-custom --display-name "Slack (Custom)"
    """
    try:
        effective_name = name or cli_name
        _check_node_name_collision(effective_name)

        client = get_client()
        pkg_path = client.generate(cli_name, output_dir=output_dir, force=force, name_override=name, display_name_override=display_name)
        print_success(f"Generated n8n node package at: {pkg_path}")

        metadata = client.get_tool(cli_name)
        total_ops = sum(len(g.commands) for g in metadata.command_groups)

        # Build PascalCase name for the icon path (use override if provided)
        effective_name = name or cli_name
        pascal_name = "".join(w.title() for w in effective_name.replace("-", "_").split("_"))
        icon_path = f"{pkg_path}/nodes/{pascal_name}/{effective_name}.svg"

        summary = {
            "package": effective_name,
            "path": pkg_path,
            "resources": len(metadata.command_groups),
            "operations": total_ops,
            "credentials": len(metadata.credentials),
            "pending_tasks": [
                {
                    "task": "Generate SVG icon",
                    "description": (
                        f"The node references icon 'file:{cli_name}.svg' but no SVG exists yet. "
                        f"Generate the icon NOW using these steps:\n"
                        f"1. Web search for '{metadata.display_name} logo' and '{metadata.display_name} icon'\n"
                        f"2. Find the official logo/icon image — visit the service's homepage if needed\n"
                        f"3. Study the logo's exact colors (hex values), shapes, and distinctive elements\n"
                        f"4. Recreate the logo as a clean 60x60 SVG using vector paths, circles, rects — match the real logo as closely as possible\n"
                        f"5. Use the service's actual brand colors (web search for '{metadata.display_name} brand colors' if uncertain)\n"
                        f"6. Write the SVG to: {icon_path}\n"
                        f"The SVG must be a valid standalone SVG file with xmlns attribute, 60x60 viewBox. "
                        f"Do NOT use a generic letter icon — always reproduce the actual service logo."
                    ),
                    "target_path": icon_path,
                },
            ],
        }
        print_json(summary)

    except Exception as e:
        raise typer.Exit(handle_error(e))
