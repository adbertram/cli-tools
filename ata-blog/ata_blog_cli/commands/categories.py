"""Categories commands for ATA Blog CLI (passthrough to wordpress CLI)."""
import subprocess
import typer
from typing import List, Optional

COMMAND_CREDENTIALS = {
    "list": ["custom"],
    "get": ["custom"],
    "create": ["custom"],
}

app = typer.Typer(help="Manage WordPress categories")


def _passthrough(resource: str, args: List[str]):
    """Pass command through to wordpress CLI with full output."""
    cmd = ["wordpress", resource] + args
    result = subprocess.run(cmd)
    raise typer.Exit(result.returncode)


@app.command("list", context_settings={"allow_extra_args": True, "allow_interspersed_args": False})
def categories_list(
    ctx: typer.Context,
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(None, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """List WordPress categories."""
    args = ["list"]
    if table:
        args.append("--table")
    if limit:
        args.extend(["--limit", str(limit)])
    if filter:
        for f in filter:
            args.extend(["--filter", f])
    if properties:
        args.extend(["--properties", properties])
    args.extend(ctx.args)
    _passthrough("categories", args)


@app.command("get", context_settings={"allow_extra_args": True, "allow_interspersed_args": False})
def categories_get(
    ctx: typer.Context,
    cat_id: int = typer.Argument(..., help="Category ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get category details."""
    args = ["get", str(cat_id)]
    if table:
        args.append("--table")
    args.extend(ctx.args)
    _passthrough("categories", args)


@app.command("create", context_settings={"allow_extra_args": True, "allow_interspersed_args": False})
def categories_create(ctx: typer.Context, name: str = typer.Argument(...)):
    """Create a category."""
    _passthrough("categories", ["create", name] + ctx.args)
