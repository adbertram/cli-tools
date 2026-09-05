"""Media commands for ATA Blog CLI (passthrough to wordpress CLI)."""
import subprocess
import typer
from cli_tools_shared.output import command
from typing import List, Optional

COMMAND_CREDENTIALS = {
    "list": ["custom"],
    "get": ["custom"],
    "upload": ["custom"],
    "delete": ["custom"],
}

app = typer.Typer(help="Manage WordPress media (passthrough to wordpress CLI)")


def _passthrough(resource: str, args: List[str]):
    """Pass command through to wordpress CLI with full output."""
    cmd = ["wordpress", resource] + args
    result = subprocess.run(cmd)
    raise typer.Exit(result.returncode)


@app.command("list", context_settings={"allow_extra_args": True, "allow_interspersed_args": False})
@command
def media_list(
    ctx: typer.Context,
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(None, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """List WordPress media. All options passed to: wordpress media list"""
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
    _passthrough("media", args)


@app.command("get", context_settings={"allow_extra_args": True, "allow_interspersed_args": False})
@command
def media_get(
    ctx: typer.Context,
    media_id: int = typer.Argument(..., help="Media ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get media details. All options passed to: wordpress media get"""
    args = ["get", str(media_id)]
    if table:
        args.append("--table")
    args.extend(ctx.args)
    _passthrough("media", args)


@app.command("upload", context_settings={"allow_extra_args": True, "allow_interspersed_args": False})
@command
def media_upload(ctx: typer.Context, file_path: str = typer.Argument(...)):
    """Upload media file. All options passed to: wordpress media upload"""
    _passthrough("media", ["upload", file_path] + ctx.args)


@app.command("delete", context_settings={"allow_extra_args": True, "allow_interspersed_args": False})
@command
def media_delete(ctx: typer.Context, media_id: int = typer.Argument(...)):
    """Delete media. All options passed to: wordpress media delete"""
    _passthrough("media", ["delete", str(media_id)] + ctx.args)
