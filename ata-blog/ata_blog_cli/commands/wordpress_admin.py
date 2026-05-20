"""WordPress admin commands for ATA Blog CLI."""
import subprocess
from typing import List, Optional

import typer

COMMAND_CREDENTIALS = {
    "plugins": ["custom"],
    "plugins list": ["custom"],
    "plugins get": ["custom"],
    "plugins activate": ["custom"],
    "plugins deactivate": ["custom"],
    "plugins delete": ["custom"],
    "plugins install": ["custom"],
    "plugins upgrade": ["custom"],
}

app = typer.Typer(help="Manage WordPress admin operations", no_args_is_help=True)
plugins_app = typer.Typer(help="Manage WordPress plugins", no_args_is_help=True)
app.add_typer(plugins_app, name="plugins")


def _run_wordpress(args: List[str]) -> None:
    """Run a wordpress admin command and forward its output."""
    result = subprocess.run(["wordpress", "admin"] + args, capture_output=True, text=True)
    if result.stdout:
        typer.echo(result.stdout, nl=False)
    if result.stderr:
        typer.echo(result.stderr, err=True, nl=False)
    raise typer.Exit(result.returncode)


@plugins_app.command("list")
def plugins_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum plugins to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Forwarded filter expressions for wordpress admin"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status (active, inactive)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
) -> None:
    """List installed WordPress plugins."""
    args = ["plugins", "list"]
    if table:
        args.append("--table")
    if limit is not None:
        args.extend(["--limit", str(limit)])
    if filter:
        for value in filter:
            args.extend(["--filter", value])
    if status:
        args.extend(["--status", status])
    if properties:
        args.extend(["--properties", properties])
    _run_wordpress(args)


@plugins_app.command("get")
def plugins_get(
    plugin: str = typer.Argument(..., help="Plugin identifier"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
) -> None:
    """Get details for a specific WordPress plugin."""
    args = ["plugins", "get", plugin]
    if table:
        args.append("--table")
    if properties:
        args.extend(["--properties", properties])
    _run_wordpress(args)


@plugins_app.command("activate")
def plugins_activate(plugin: str = typer.Argument(..., help="Plugin identifier")) -> None:
    """Activate a WordPress plugin."""
    _run_wordpress(["plugins", "activate", plugin])


@plugins_app.command("deactivate")
def plugins_deactivate(plugin: str = typer.Argument(..., help="Plugin identifier")) -> None:
    """Deactivate a WordPress plugin."""
    _run_wordpress(["plugins", "deactivate", plugin])


@plugins_app.command("delete")
def plugins_delete(plugin: str = typer.Argument(..., help="Plugin identifier")) -> None:
    """Delete an inactive WordPress plugin."""
    _run_wordpress(["plugins", "delete", plugin])


@plugins_app.command("install")
def plugins_install(
    slug: str = typer.Argument(..., help="Plugin slug from wordpress.org"),
    activate: bool = typer.Option(False, "--activate", "-a", help="Activate after installation"),
) -> None:
    """Install a plugin from wordpress.org."""
    args = ["plugins", "install", slug]
    if activate:
        args.append("--activate")
    _run_wordpress(args)


@plugins_app.command("upgrade")
def plugins_upgrade(plugin: str = typer.Argument(..., help="Plugin identifier")) -> None:
    """Upgrade a plugin through the WordPress CLI's native updater path."""
    _run_wordpress(["plugins", "upgrade", plugin])
