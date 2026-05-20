"""Site Audit commands for Ahrefs CLI."""
from typing import List, Optional

import typer
from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import handle_error, print_info, print_json, print_success, print_table

from ..client import get_client, ClientError
from ..cache import list_cached_projects, clear_cache

COMMAND_CREDENTIALS = {
    "cache": [
        "browser_session"
    ],
    "get": [
        "browser_session"
    ],
    "list": [
        "browser_session"
    ]
}

app = typer.Typer(help="Site audit operations", no_args_is_help=True)


@app.command("list")
def site_audit_list(
    project_id: int = typer.Argument(..., help="Ahrefs project ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of crawls to return"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"
    ),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated list of properties to display"
    ),
):
    """
    List all site audit crawls for a project.

    Shows all available crawls/audits with their dates and status.

    Example:
        ahrefs site-audit list 2185593
        ahrefs site-audit list 2185593 --table
        ahrefs site-audit list 2185593 --limit 5
    """
    try:
        client = get_client()
        crawls = client.list_crawls(project_id)
        client.close()

        # Convert to dicts first for filtering
        crawl_dicts = [c.model_dump() for c in crawls]

        # Apply filters using standard filter module
        if filter:
            crawl_dicts = apply_filters(crawl_dicts, filter)

        # Apply limit
        if limit and len(crawl_dicts) > limit:
            crawl_dicts = crawl_dicts[:limit]

        # Apply property filter
        if properties:
            props = [p.strip() for p in properties.split(",")]
            crawl_dicts = [{k: v for k, v in c.items() if k in props} for c in crawl_dicts]

        if table:
            columns = properties.split(",") if properties else ["id", "crawl_date", "status", "pages_crawled", "health_score"]
            headers = [c.replace("_", " ").title() for c in columns]
            print_table(crawl_dicts, columns, headers)
        else:
            print_json(crawl_dicts)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def site_audit_get(
    project_id: int = typer.Argument(..., help="Ahrefs project ID"),
    refresh: bool = typer.Option(False, "--refresh", "-r", help="Force fresh fetch, bypass cache"),
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum issues per category"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"
    ),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated list of top-level properties to include"
    ),
):
    """
    Get complete site audit report for a project.

    Returns comprehensive audit data including overview metrics, issues by category,
    orphan pages, redirect chains, and duplicate content.

    Data is cached locally. Use --refresh to force a fresh fetch.

    Example:
        ahrefs site-audit get 2185593
        ahrefs site-audit get 2185593 --refresh
        ahrefs site-audit get 2185593 --table
    """
    try:
        client = get_client()
        report = client.get_site_audit(project_id, refresh=refresh)
        client.close()

        # Convert to dict
        report_dict = report.model_dump()

        # Apply property filter
        if properties:
            props = [p.strip() for p in properties.split(",")]
            report_dict = {k: v for k, v in report_dict.items() if k in props}

        if table:
            # Show summary table
            overview = report.overview
            rows = [
                {"metric": "Project ID", "value": str(report.project_id)},
                {"metric": "Domain", "value": report.domain or "N/A"},
                {"metric": "Crawl Date", "value": report.crawl_date or "N/A"},
                {"metric": "Health Score", "value": f"{overview.health_score}%" if overview.health_score else "N/A"},
                {"metric": "Pages Crawled", "value": str(overview.pages_crawled)},
                {"metric": "Total Issues", "value": str(overview.total_issues)},
                {"metric": "Errors", "value": str(overview.errors_count)},
                {"metric": "Warnings", "value": str(overview.warnings_count)},
                {"metric": "Broken Links", "value": str(overview.broken_links)},
                {"metric": "Redirects", "value": str(overview.redirects)},
                {"metric": "Orphan Pages", "value": str(overview.orphan_pages)},
                {"metric": "Duplicate Content", "value": str(overview.duplicate_content)},
            ]

            # Add error info if any
            if report.errors:
                rows.append({"metric": "Fetch Errors", "value": str(len(report.errors))})

            print_table(rows, ["metric", "value"], ["Metric", "Value"])
        else:
            print_json(report_dict)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("cache")
def site_audit_cache(
    action: str = typer.Argument("list", help="Action: list, clear"),
    project_id: Optional[int] = typer.Option(None, "--project", "-p", help="Specific project ID (for clear)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Manage cached site audit reports.

    Actions:
        list  - Show all cached project IDs
        clear - Clear cached reports

    Example:
        ahrefs site-audit cache list
        ahrefs site-audit cache clear
        ahrefs site-audit cache clear --project 2185593
    """
    if action == "list":
        projects = list_cached_projects()
        if table:
            rows = [{"project_id": p} for p in projects]
            print_table(rows, ["project_id"], ["Project ID"])
        else:
            print_json({"cached_projects": projects, "count": len(projects)})

    elif action == "clear":
        removed = clear_cache(project_id)
        if project_id:
            print_success(f"Cleared cache for project {project_id}")
        else:
            print_success(f"Cleared {removed} cached report(s)")

    else:
        print_info(f"Unknown action: {action}. Use 'list' or 'clear'.")
        raise typer.Exit(1)
