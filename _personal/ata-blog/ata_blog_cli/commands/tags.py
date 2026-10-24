"""Tags commands for ATA Blog CLI, backed by the static site's terms.json."""
import typer
from typing import List, Optional

from cli_tools_shared.filters import apply_filters, apply_limit, apply_properties_filter
from cli_tools_shared.output import command, print_json, print_success, print_table

from ..corpus import TERM_FIELDS, create_term, get_term, list_terms

COMMAND_CREDENTIALS = {
    "list": ["no_auth"],
    "get": ["no_auth"],
    "create": ["no_auth"],
}

TAXONOMY = "tags"

app = typer.Typer(help="Manage static site tags")


@app.command("list")
@command
def tags_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:DevOps, count:gt:10)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """List static site tags."""
    terms = list_terms(TAXONOMY)
    if filter:
        terms = apply_filters(terms, filter)
    if limit:
        terms = apply_limit(terms, limit)
    columns = TERM_FIELDS
    if properties:
        columns = [name.strip() for name in properties.split(",")]
        terms = apply_properties_filter(terms, properties)
    if table:
        print_table(terms, columns=columns, headers=columns)
    else:
        print_json(terms)


@app.command("get")
@command
def tags_get(
    term_id: int = typer.Argument(..., help="Tag ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get tag details."""
    term = get_term(TAXONOMY, term_id)
    if table:
        print_table([term], columns=TERM_FIELDS, headers=TERM_FIELDS)
    else:
        print_json(term)


@app.command("create")
@command
def tags_create(name: str = typer.Argument(..., help="Tag name")):
    """Create a tag in the static site's terms.json."""
    term = create_term(TAXONOMY, name)
    print_success(f"Created tag {term['name']} (id {term['id']})")
    print_json(term)
