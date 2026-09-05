"""WordPress menu commands for ATA Blog CLI (passthrough to wordpress CLI)."""

from __future__ import annotations

import subprocess
from typing import Optional

import typer
from cli_tools_shared.output import command


COMMAND_CREDENTIALS = {
    "add-page": ["custom"],
    "get": ["custom"],
    "items": ["custom"],
    "list": ["custom"],
    "locations": ["custom"],
}

app = typer.Typer(help="Manage WordPress navigation menus")


def _passthrough(args: list[str]):
    """Pass command through to `wordpress menus`."""
    cmd = ["wordpress", "menus"] + args
    result = subprocess.run(cmd)
    raise typer.Exit(result.returncode)


@app.command("list")
@command
def menus_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """List WordPress navigation menus."""
    args = ["list"]
    if table:
        args.append("--table")
    if properties:
        args.extend(["--properties", properties])
    _passthrough(args)


@app.command("get")
@command
def menus_get(
    menu: str = typer.Argument(..., help="Menu ID, slug, or name"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum menu items to return"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """Get a WordPress navigation menu and its items by menu ID, slug, or name."""
    args = ["items", "--menu", menu]
    if table:
        args.append("--table")
    if limit is not None:
        args.extend(["--limit", str(limit)])
    if properties:
        args.extend(["--properties", properties])
    _passthrough(args)


@app.command("locations")
@command
def menu_locations(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """List WordPress navigation menu locations."""
    args = ["locations"]
    if table:
        args.append("--table")
    _passthrough(args)


@app.command("items")
@command
def menu_items(
    menu: Optional[str] = typer.Option(None, "--menu", help="Menu ID, slug, or name"),
    location: Optional[str] = typer.Option(None, "--location", help="Theme menu location"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum menu items to return"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """List items in a WordPress navigation menu."""
    args = ["items"]
    if menu:
        args.extend(["--menu", menu])
    if location:
        args.extend(["--location", location])
    if table:
        args.append("--table")
    if limit is not None:
        args.extend(["--limit", str(limit)])
    if properties:
        args.extend(["--properties", properties])
    _passthrough(args)


@app.command("add-page")
@command
def menu_add_page(
    page_id: int = typer.Argument(..., help="WordPress page ID"),
    menu: Optional[str] = typer.Option(None, "--menu", help="Menu ID, slug, or name"),
    location: Optional[str] = typer.Option(None, "--location", help="Theme menu location"),
    title: Optional[str] = typer.Option(None, "--title", help="Menu item title"),
    menu_order: Optional[int] = typer.Option(None, "--menu-order", help="Menu item order"),
):
    """Add a WordPress page to a navigation menu."""
    args = ["add-page"]
    if menu:
        args.extend(["--menu", menu])
    if location:
        args.extend(["--location", location])
    if title:
        args.extend(["--title", title])
    if menu_order is not None:
        args.extend(["--menu-order", str(menu_order)])
    args.append(str(page_id))
    _passthrough(args)
