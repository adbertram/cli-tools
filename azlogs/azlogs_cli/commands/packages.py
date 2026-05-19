"""Package commands — manage downloaded log packages."""
import typer
from typing import Optional, List

from pydantic import BaseModel

from ..client import get_client, ClientError
from ..filters import apply_filters, apply_properties_filter  # client-side filtering on local data
from cli_tools_shared.output import print_json, print_table, print_success, print_error, print_info, handle_error


app = typer.Typer(help="Manage downloaded log packages", no_args_is_help=True)


def _model_to_dict(item):
    """Convert model or dict to dict."""
    if isinstance(item, BaseModel):
        return item.model_dump()
    return item


def _extract_fields(items: list, fields: list) -> list:
    """Extract specified fields from items."""
    result = []
    for item in items:
        data = _model_to_dict(item)
        extracted = {}
        for field in fields:
            parts = field.split(".")
            value = data
            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    value = None
                    break
            extracted[field] = value
        result.append(extracted)
    return result


@app.command("list")
def packages_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum packages to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
):
    """
    List downloaded log packages.

    Examples:
        azlogs packages list
        azlogs packages list --table
        azlogs packages list --limit 5
        azlogs packages list --filter "has_merged:true"
        azlogs packages list --properties "name,entry_count,created"
    """
    try:
        client = get_client()
        packages = client.list_packages(limit=limit, filters=filter)

        # Apply properties selection
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            packages = _extract_fields(packages, fields)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(packages, fields, fields)
            else:
                print_table(
                    packages,
                    ["name", "file_count", "entry_count", "has_merged", "created"],
                    ["Name", "Files", "Entries", "Merged", "Created"],
                )
        else:
            print_json(packages)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def packages_get(
    name: str = typer.Argument(..., help="Package name (directory name)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get details of a specific log package.

    Examples:
        azlogs packages get 2026-02-10_09-40-16
        azlogs packages get 2026-02-10_09-40-16 --table
    """
    try:
        client = get_client()
        detail = client.get_package(name)

        if table:
            item_dict = _model_to_dict(detail)
            # Exclude large nested fields from table view
            skip = {"files", "entity_counts", "level_counts"}
            rows = [{"field": k, "value": str(v)} for k, v in item_dict.items() if k not in skip and v is not None]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(detail)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("download")
def packages_download(
    table: bool = typer.Option(False, "--table", "-t", help="Display result as table"),
    include_kudu_trace: bool = typer.Option(
        False, "--include-kudu-trace",
        help="Download Kudu trace logs separately (already included in dump)",
    ),
    since: str = typer.Option(
        "24h", "--since", "-s",
        help="Only include entries from this time window (e.g. 24h, 3d, 1w, all)",
    ),
):
    """
    Download fresh logs from Azure Web App.

    Downloads via Kudu API, then auto-parses into JSONL and generates HTML report.
    Requires 'azlogs auth login' to be configured first.

    By default, only entries from the last 24 hours are included in the merged
    output. Use --since to change the window (e.g. --since 3d, --since all).

    The Kudu dump already includes trace logs. Use --include-kudu-trace to
    re-download them via a separate API call (overwrites with a fresh snapshot).

    Examples:
        azlogs packages download
        azlogs packages download --table
        azlogs packages download --since 3d
        azlogs packages download --since all
        azlogs packages download --include-kudu-trace
    """
    try:
        client = get_client()
        print_info("Starting download from Azure... (downloads can take up to 10 minutes)")
        package = client.download_package(include_kudu_trace=include_kudu_trace, since=since)
        print_success(f"Package created: {package.name}")

        if table:
            print_table(
                [package],
                ["name", "file_count", "entry_count", "has_merged", "has_report"],
                ["Name", "Files", "Entries", "Merged", "Report"],
            )
        else:
            print_json(package)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("parse")
def packages_parse(
    name: str = typer.Argument(..., help="Package name to re-parse"),
    format: str = typer.Option("jsonl", "--format", help="Output format: jsonl or csv"),
    table: bool = typer.Option(False, "--table", "-t", help="Display result as table"),
    since: str = typer.Option(
        "all", "--since", "-s",
        help="Only include entries from this time window (e.g. 12h, 3d, 1w, all)",
    ),
):
    """
    Re-parse an existing log package.

    Regenerates merged output and HTML report from raw log files.
    Use --since to filter to a time window (default: all entries).

    Examples:
        azlogs packages parse 2026-02-10_09-40-16
        azlogs packages parse 2026-02-10_09-40-16 --since 12h
        azlogs packages parse 2026-02-10_09-40-16 --format csv
    """
    try:
        from ..models import OutputFormat
        fmt = OutputFormat(format)

        client = get_client()
        print_info(f"Re-parsing package {name}...")
        package = client.parse_package(name, fmt=fmt, since=since)
        print_success(f"Package re-parsed: {package.entry_count} entries")

        if table:
            print_table(
                [package],
                ["name", "file_count", "entry_count", "has_merged", "has_report"],
                ["Name", "Files", "Entries", "Merged", "Report"],
            )
        else:
            print_json(package)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("validate")
def packages_validate(
    name: str = typer.Argument(..., help="Package name to validate"),
    table: bool = typer.Option(False, "--table", "-t", help="Display result as table"),
):
    """
    Validate that merged.jsonl covers every raw log line.

    Examples:
        azlogs packages validate 2026-02-10_09-40-16
        azlogs packages validate 2026-02-10_09-40-16 --table
    """
    try:
        client = get_client()
        result = client.validate_package(name)

        if result.is_valid:
            print_success(f"Validation PASSED: {result.total_raw_lines} lines, all covered")
        else:
            print_error(f"Validation FAILED: {result.missing_count} lines missing")

        if table:
            summary = _model_to_dict(result)
            # Don't show missing_lines array in table
            summary.pop("missing_lines", None)
            rows = [{"field": k, "value": str(v)} for k, v in summary.items()]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def packages_delete(
    name: str = typer.Argument(..., help="Package name to delete"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """
    Delete a downloaded log package.

    Examples:
        azlogs packages delete 2026-02-10_09-40-16
        azlogs packages delete 2026-02-10_09-40-16 --yes
    """
    try:
        if not yes:
            confirm = typer.confirm(f"Delete package '{name}'?")
            if not confirm:
                print_info("Cancelled")
                raise typer.Exit(0)

        client = get_client()
        client.delete_package(name)
        print_success(f"Package '{name}' deleted")

    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


COMMAND_CREDENTIALS = {
    "delete": [
        "custom"
    ],
    "download": [
        "custom"
    ],
    "get": [
        "custom"
    ],
    "list": [
        "custom"
    ],
    "parse": [
        "custom"
    ],
    "validate": [
        "custom"
    ]
}
