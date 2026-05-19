"""Marketplace (browser-automation instruction) commands for Impact CLI.

Impact's Publisher API has no marketplace/discovery endpoint. These commands
return structured JSON instructions that another agent (using the
``playwright-cli`` skill) can follow to drive the partner portal browser UI.

No Impact credentials are needed to generate the instructions themselves —
the eventual browser automation will use credentials from the ``lastpass``
CLI at runtime.
"""
COMMAND_CREDENTIALS = {
    "search": ["no_auth"],
    "apply": ["no_auth"],
    "list-categories": ["no_auth"],
}

from typing import Optional

import typer

from cli_tools_shared.output import handle_error, print_json, print_info

from ..models.marketplace_instructions import (
    build_apply_instruction,
    build_list_categories_instruction,
    build_search_instruction,
    render_text,
)


app = typer.Typer(
    help=(
        "Generate browser-automation instructions for Impact marketplace flows. "
        "Returns structured JSON for downstream playwright-cli execution."
    ),
    no_args_is_help=True,
)


def _emit(instruction, text: bool):
    if text:
        print_info(render_text(instruction))
        return
    print_json(instruction)


@app.command("search")
def marketplace_search(
    keyword: Optional[str] = typer.Option(None, "--keyword", help="Optional search keyword to type into the marketplace search box"),
    category: Optional[str] = typer.Option(None, "--category", help="Optional category label to apply as a filter"),
    text: bool = typer.Option(False, "--text", help="Emit a human-readable plain-text rendering instead of the default machine-parseable JSON"),
):
    """Emit playwright-cli instructions to discover Impact marketplace programs."""
    try:
        instruction = build_search_instruction(keyword=keyword, category=category)
        _emit(instruction, text)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("apply")
def marketplace_apply(
    program_id: str = typer.Argument(..., help="Impact program identifier discovered via `marketplace search`"),
    text: bool = typer.Option(False, "--text", help="Emit a human-readable plain-text rendering instead of the default machine-parseable JSON"),
):
    """Emit playwright-cli instructions to apply to a specific Impact program."""
    try:
        instruction = build_apply_instruction(program_id=program_id)
        _emit(instruction, text)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("list-categories")
def marketplace_list_categories(
    text: bool = typer.Option(False, "--text", help="Emit a human-readable plain-text rendering instead of the default machine-parseable JSON"),
):
    """Emit playwright-cli instructions to harvest Impact marketplace category labels."""
    try:
        instruction = build_list_categories_instruction()
        _emit(instruction, text)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
