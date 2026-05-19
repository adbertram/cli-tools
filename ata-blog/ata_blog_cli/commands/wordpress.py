"""WordPress commands for ATA Blog CLI (passthrough to wordpress CLI)."""
import subprocess
import typer
from typing import List, Optional

app = typer.Typer(help="Manage WordPress posts (passthrough to wordpress CLI)")


def _passthrough(resource: str, args: List[str]):
    """Pass command through to wordpress CLI with full output."""
    cmd = ["wordpress", resource] + args
    result = subprocess.run(cmd)
    raise typer.Exit(result.returncode)


@app.command("list", context_settings={"allow_extra_args": True, "allow_interspersed_args": False})
def posts_list(
    ctx: typer.Context,
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(None, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """List WordPress posts. All options passed to: wordpress posts list"""
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
    _passthrough("posts", args)


@app.command("get", context_settings={"allow_extra_args": True, "allow_interspersed_args": False})
def posts_get(
    ctx: typer.Context,
    post_id: int = typer.Argument(..., help="Post ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get WordPress post details. All options passed to: wordpress posts get"""
    args = ["get", str(post_id)]
    if table:
        args.append("--table")
    args.extend(ctx.args)
    _passthrough("posts", args)


@app.command("create", context_settings={"allow_extra_args": True, "allow_interspersed_args": False})
def posts_create(ctx: typer.Context):
    """Create WordPress post. All options passed to: wordpress posts create"""
    _passthrough("posts", ["create"] + ctx.args)


@app.command("update", context_settings={"allow_extra_args": True, "allow_interspersed_args": False})
def posts_update(ctx: typer.Context, post_id: int = typer.Argument(...)):
    """Update WordPress post. All options passed to: wordpress posts update"""
    _passthrough("posts", ["update", str(post_id)] + ctx.args)


@app.command("schedule")
def posts_schedule(
    post_id: int = typer.Argument(..., help="WordPress post ID to schedule"),
    date: Optional[str] = typer.Option(None, "--date", "-d", help="Schedule date (ISO 8601)"),
    auto_schedule: bool = typer.Option(False, "--auto-schedule", help="Auto-find next available slot"),
):
    """Schedule an existing WordPress draft post for publication."""
    if not date and not auto_schedule:
        typer.echo("Error: Provide --date or --auto-schedule", err=True)
        raise typer.Exit(1)
    args = ["update", str(post_id), "--status", "future"]
    if auto_schedule:
        args.append("--auto-schedule")
    elif date:
        args.extend(["--date", date])
    _passthrough("posts", args)


@app.command("delete", context_settings={"allow_extra_args": True, "allow_interspersed_args": False})
def posts_delete(ctx: typer.Context, post_id: int = typer.Argument(...)):
    """Delete WordPress post. All options passed to: wordpress posts delete"""
    _passthrough("posts", ["delete", str(post_id)] + ctx.args)
