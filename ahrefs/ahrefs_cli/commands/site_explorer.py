"""Site Explorer commands for Ahrefs CLI."""
from typing import List, Optional

import typer
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import command, print_json, print_table

from ..client import get_client, cache_disabled

COMMAND_CREDENTIALS = {
    "overview": [
        "browser_session"
    ],
    "top-pages": [
        "browser_session"
    ]
}

app = typer.Typer(help="Site Explorer operations", no_args_is_help=True)


@app.command("overview")
@command
def site_explorer_overview(
    domain: str = typer.Argument(..., help="Target domain (e.g. example.com)"),
    refresh: bool = typer.Option(False, "--refresh", "-r", help="Force fresh fetch, bypass cache"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated list of properties to display"
    ),
):
    """
    Get Site Explorer overview metrics for a domain.

    Returns Domain Rating (DR), estimated monthly organic traffic, number of
    ranking organic keywords, referring domains, and backlinks.

    Example:
        ahrefs site-explorer overview adamtheautomator.com
        ahrefs site-explorer overview adamtheautomator.com --table
        ahrefs site-explorer overview adamtheautomator.com --refresh
    """
    client = get_client()
    with cache_disabled(refresh):
        overview = client.get_domain_overview(domain)
    client.close()

    overview_dict = overview.model_dump()

    if properties:
        props = [p.strip() for p in properties.split(",")]
        overview_dict = {k: v for k, v in overview_dict.items() if k in props}

    if table:
        rows = [{"metric": k, "value": "" if v is None else str(v)} for k, v in overview_dict.items()]
        print_table(rows, ["metric", "value"], ["Metric", "Value"])
    else:
        print_json(overview_dict)


@app.command("top-pages")
@command
def site_explorer_top_pages(
    domain: str = typer.Argument(..., help="Target domain (e.g. example.com)"),
    refresh: bool = typer.Option(False, "--refresh", "-r", help="Force fresh fetch, bypass cache"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of pages to return"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter: field:op:value (e.g., url:contains:blog, traffic:gt:100)"
    ),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated list of properties to display"
    ),
):
    """
    Get top pages by organic traffic for a domain.

    Returns the top-ranking pages with their URL and estimated organic traffic
    per page.

    Example:
        ahrefs site-explorer top-pages adamtheautomator.com
        ahrefs site-explorer top-pages adamtheautomator.com --limit 10
        ahrefs site-explorer top-pages adamtheautomator.com --table
        ahrefs site-explorer top-pages adamtheautomator.com --filter "url:contains:blog"
    """
    client = get_client()
    with cache_disabled(refresh):
        pages = client.get_top_pages(domain, limit=limit)
    client.close()

    page_dicts = [p.model_dump() for p in pages]

    if filter:
        page_dicts = apply_filters(page_dicts, filter)

    if limit and len(page_dicts) > limit:
        page_dicts = page_dicts[:limit]

    if properties:
        props = [p.strip() for p in properties.split(",")]
        page_dicts = [{k: v for k, v in p.items() if k in props} for p in page_dicts]

    if table:
        columns = properties.split(",") if properties else ["url", "traffic"]
        headers = [c.replace("_", " ").title() for c in columns]
        print_table(page_dicts, columns, headers)
    else:
        print_json(page_dicts)
