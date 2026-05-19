"""WordPress page commands for ATA Blog CLI (passthrough to wordpress CLI)."""
import subprocess
import typer
from typing import List, Optional

COMMAND_CREDENTIALS = {
    "list": ["custom"],
    "get": ["custom"],
    "create": ["custom"],
    "update": ["custom"],
    "delete": ["custom"],
}

app = typer.Typer(help="Manage WordPress pages")


def _passthrough(args: List[str]):
    """Pass command through to `wordpress pages`."""
    cmd = ["wordpress", "pages"] + args
    result = subprocess.run(cmd)
    raise typer.Exit(result.returncode)


def _extra_args(ctx: typer.Context) -> List[str]:
    """Return passthrough args without Typer's separator marker."""
    return [arg for arg in ctx.args if arg != "--"]


@app.command("list", context_settings={"allow_extra_args": True, "allow_interspersed_args": False})
def pages_list(
    ctx: typer.Context,
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(None, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """List WordPress pages."""
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
    args.extend(_extra_args(ctx))
    _passthrough(args)


@app.command("get", context_settings={"allow_extra_args": True, "allow_interspersed_args": False})
def pages_get(
    ctx: typer.Context,
    page_id: int = typer.Argument(..., help="Page ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get page details."""
    args = ["get"]
    if table:
        args.append("--table")
    args.extend(_extra_args(ctx))
    args.append(str(page_id))
    _passthrough(args)


@app.command("create", context_settings={"allow_extra_args": True, "allow_interspersed_args": False})
def pages_create(
    ctx: typer.Context,
    title: Optional[str] = typer.Option(None, "--title", help="Page title"),
    content: Optional[str] = typer.Option(None, "--content", help="Page content"),
    status: str = typer.Option("draft", "--status", help="Page status (publish, draft, pending, private, future)"),
    slug: Optional[str] = typer.Option(None, "--slug", help="URL slug"),
    from_docx: Optional[str] = typer.Option(None, "--from-docx", help="Path to DOCX file to convert"),
    from_markdown: Optional[str] = typer.Option(None, "--from-markdown", help="Path to Markdown file to convert"),
    date: Optional[str] = typer.Option(None, "--date", help="Schedule date (ISO 8601)"),
    parent: Optional[int] = typer.Option(None, "--parent", help="Parent page ID"),
    menu_order: Optional[int] = typer.Option(None, "--menu-order", help="Order in menus"),
    template: Optional[str] = typer.Option(None, "--template", help="Page template slug"),
    excerpt: Optional[str] = typer.Option(None, "--excerpt", help="Page excerpt"),
):
    """Create a page."""
    args = ["create"]
    if title:
        args.extend(["--title", title])
    if content:
        args.extend(["--content", content])
    args.extend(["--status", status])
    if slug:
        args.extend(["--slug", slug])
    if from_docx:
        args.extend(["--from-docx", from_docx])
    if from_markdown:
        args.extend(["--from-markdown", from_markdown])
    if date:
        args.extend(["--date", date])
    if parent is not None:
        args.extend(["--parent", str(parent)])
    if menu_order is not None:
        args.extend(["--menu-order", str(menu_order)])
    if template:
        args.extend(["--template", template])
    if excerpt:
        args.extend(["--excerpt", excerpt])
    args.extend(_extra_args(ctx))
    _passthrough(args)


@app.command("update", context_settings={"allow_extra_args": True, "allow_interspersed_args": False})
def pages_update(ctx: typer.Context, page_id: int = typer.Argument(...)):
    """Update a page."""
    _passthrough(["update"] + _extra_args(ctx) + [str(page_id)])


@app.command("delete", context_settings={"allow_extra_args": True, "allow_interspersed_args": False})
def pages_delete(ctx: typer.Context, page_id: int = typer.Argument(...)):
    """Delete a page."""
    _passthrough(["delete"] + _extra_args(ctx) + [str(page_id)])
