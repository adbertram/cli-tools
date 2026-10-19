"""Google Search Console commands."""
COMMAND_CREDENTIALS = {
    "coverage": ["no_auth"],
    "index": ["custom"],
    "sites": ["custom"],
    "sitemaps": ["custom"],
    "urls": ["custom"],
}

import csv
import io
import re
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
import typer
from typing import Optional, List
from googleapiclient.errors import HttpError
from ..client import get_client
from cli_tools_shared.output import command, print_json, print_table, print_success, print_error, handle_error
from ..config import get_config

app = typer.Typer(help="Access Google Search Console")


def _handle_api_not_enabled(error: HttpError) -> bool:
    """Check if error is due to API not being enabled and show helpful message.

    Returns True if the error was handled, False otherwise.
    """
    if error.resp.status == 403:
        error_content = str(error)
        if "accessNotConfigured" in error_content or "has not been used in project" in error_content:
            # Extract the enable URL from the error message
            url_match = re.search(r'https://console\.developers\.google\.com/apis/api/[^\s]+', error_content)
            enable_url = url_match.group(0).rstrip('".') if url_match else (
                "https://console.developers.google.com/apis/api/searchconsole.googleapis.com/overview"
            )

            print_error("Google Search Console API is not enabled for your project.")
            print_error("")
            print_error("To enable it:")
            print_error(f"  1. Visit: {enable_url}")
            print_error("  2. Click 'Enable' to activate the Search Console API")
            print_error("  3. Wait 1-2 minutes for the change to propagate")
            print_error("  4. Run this command again")
            return True
    return False


sites_app = typer.Typer(help="Manage Search Console sites")
app.add_typer(sites_app, name="sites")


@app.command("index")
@command
def searchconsole_index(
    url: str = typer.Argument(..., help="URL to request indexing for"),
    site_url: Optional[str] = typer.Option(
        None,
        "--site-url",
        "-s",
        help="Search Console site URL (overrides GOOGLE_SEARCHCONSOLE_SITE env var)"
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Inspect a URL's Google index status via the URL Inspection API."""
    try:
        client = get_client(profile=profile)
        service = client.get_webmasters_service()
        config = get_config(profile=profile)

        # Get site URL from option or config
        site = site_url or config.searchconsole_site
        if not site:
            raise ValueError(
                "Search Console site URL not configured. "
                "Set GOOGLE_SEARCHCONSOLE_SITE environment variable or use --site-url."
            )

        # Request URL inspection
        response = service.urlInspection().index().inspect(
            body={
                "inspectionUrl": url,
                "siteUrl": site
            }
        ).execute()

        # Output result
        result = response.get("inspectionResult", {})
        print_json(result)

        # Show indexing status
        index_result = result.get("indexStatusResult", {})
        verdict = index_result.get("verdict", "UNKNOWN")
        coverage_state = index_result.get("coverageState", "UNKNOWN")
        print_success(f"URL inspection complete. Verdict: {verdict}, Coverage: {coverage_state}")

    except HttpError as e:
        if _handle_api_not_enabled(e):
            raise typer.Exit(1)
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@sites_app.command("list")
@command
def searchconsole_sites_list(
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Output as table instead of JSON"
    ),
    limit: int = typer.Option(
        100,
        "--limit",
        "-l",
        help="Maximum number of sites to return"
    ),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter sites (field:op:value format, e.g., 'permissionLevel:eq:siteOwner')"
    ),
    properties: Optional[List[str]] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Properties to include in output (e.g., 'siteUrl,permissionLevel')"
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """List verified Search Console sites."""
    try:
        client = get_client(profile=profile)
        service = client.get_webmasters_service()

        # List sites
        response = service.sites().list().execute()
        sites = response.get("siteEntry", [])

        # Add type property based on siteUrl format
        for site in sites:
            site["type"] = "domain" if site.get("siteUrl", "").startswith("sc-domain:") else "url"

        # Apply limit
        sites = sites[:limit]

        # Apply client-side filtering if specified
        if filter:
            filtered_sites = []
            for site in sites:
                include = True
                for f in filter:
                    parts = f.split(":", 2)
                    if len(parts) >= 3:
                        field, op, value = parts[0], parts[1], parts[2]
                        site_value = str(site.get(field, ""))
                        if op == "eq" and site_value != value:
                            include = False
                        elif op == "ne" and site_value == value:
                            include = False
                        elif op == "like" and value.strip("%") not in site_value:
                            include = False
                if include:
                    filtered_sites.append(site)
            sites = filtered_sites

        # Filter properties if specified
        if properties:
            sites = [{k: v for k, v in site.items() if k in properties} for site in sites]

        # Output
        if table:
            cols = properties[:3] if properties else ["siteUrl", "type", "permissionLevel"]
            headers = [c.title() for c in cols]
            print_table(sites, cols, headers)
        else:
            print_json(sites)

    except HttpError as e:
        if _handle_api_not_enabled(e):
            raise typer.Exit(1)
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@sites_app.command("get")
@command
def searchconsole_sites_get(
    site_url: str = typer.Argument(..., help="Site URL to get details for"),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Output as table instead of JSON"
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Get details for a specific Search Console site."""
    try:
        client = get_client(profile=profile)
        service = client.get_webmasters_service()

        # Get site details
        response = service.sites().get(siteUrl=site_url).execute()

        # Add type property based on siteUrl format
        response["type"] = "domain" if response.get("siteUrl", "").startswith("sc-domain:") else "url"

        # Output
        if table:
            print_table([response], ["siteUrl", "type", "permissionLevel"], ["Site URL", "Type", "Permission Level"])
        else:
            print_json(response)

    except HttpError as e:
        if _handle_api_not_enabled(e):
            raise typer.Exit(1)
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


# URLs subcommand group
urls_app = typer.Typer(help="Query indexed URLs and search analytics")
app.add_typer(urls_app, name="urls")


def _build_dimension_filter(filter_str: str) -> dict:
    """Convert filter string to API dimension filter format.

    Supports formats:
    - field:op:value (e.g., 'page:contains:/blog/')
    - field:value (defaults to 'contains' operator)

    Operators: eq (equals), ne (notEquals), contains, notContains, regex, notRegex
    """
    parts = filter_str.split(":", 2)

    if len(parts) == 2:
        # field:value format - default to contains
        dimension, expression = parts
        operator = "contains"
    elif len(parts) >= 3:
        dimension, op, expression = parts[0], parts[1], parts[2]
        # Map short operators to API operators
        op_map = {
            "eq": "equals",
            "ne": "notEquals",
            "contains": "contains",
            "notContains": "notContains",
            "like": "contains",
            "regex": "includingRegex",
            "notRegex": "excludingRegex",
        }
        operator = op_map.get(op, op)
    else:
        raise ValueError(f"Invalid filter format: {filter_str}")

    return {
        "dimension": dimension,
        "operator": operator,
        "expression": expression
    }


@urls_app.command("list")
@command
def searchconsole_urls_list(
    site_url: Optional[str] = typer.Option(
        None,
        "--site-url",
        "-s",
        help="Search Console site URL (overrides GOOGLE_SEARCHCONSOLE_SITE env var)"
    ),
    start_date: Optional[str] = typer.Option(
        None,
        "--start-date",
        help="Start date in YYYY-MM-DD format (default: 30 days ago)"
    ),
    end_date: Optional[str] = typer.Option(
        None,
        "--end-date",
        help="End date in YYYY-MM-DD format (default: today)"
    ),
    search_type: str = typer.Option(
        "web",
        "--type",
        help="Search type: web, image, video, discover, googleNews, news"
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Output as table instead of JSON"
    ),
    limit: int = typer.Option(
        1000,
        "--limit",
        "-l",
        help="Maximum number of URLs to return (max 25000)"
    ),
    offset: int = typer.Option(
        0,
        "--offset",
        "-o",
        help="Starting row offset for pagination"
    ),
    filter: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter results (e.g., 'page:contains:/blog/', 'query:eq:python')"
    ),
    properties: Optional[List[str]] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Properties to include in output (e.g., 'page,clicks,impressions')"
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """List indexed URLs with search performance data.

    Returns URLs that have appeared in search results within the date range,
    along with clicks, impressions, CTR, and average position.

    Examples:
        google searchconsole urls list
        google searchconsole urls list --filter "page:contains:/blog/"
        google searchconsole urls list --start-date 2024-01-01 --limit 100
        google searchconsole urls list -t -p page,clicks,impressions
    """
    try:
        client = get_client(profile=profile)
        # Use webmasters v3 API for search analytics
        service = client.get_webmasters_v3_service()
        config = get_config(profile=profile)

        # Get site URL from option or config
        site = site_url or config.searchconsole_site
        if not site:
            raise ValueError(
                "Search Console site URL not configured. "
                "Set GOOGLE_SEARCHCONSOLE_SITE environment variable or use --site-url."
            )

        # Set default date range (last 30 days)
        if not end_date:
            end_date = datetime.now().strftime("%Y-%m-%d")
        if not start_date:
            start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        # Clamp limit to API maximum
        limit = min(limit, 25000)

        # Build request body
        body = {
            "startDate": start_date,
            "endDate": end_date,
            "dimensions": ["page"],
            "type": search_type,
            "rowLimit": limit,
            "startRow": offset,
        }

        # Add filters if specified
        if filter:
            filters = [_build_dimension_filter(f) for f in filter]
            body["dimensionFilterGroups"] = [{
                "groupType": "and",
                "filters": filters
            }]

        # Query search analytics
        response = service.searchanalytics().query(siteUrl=site, body=body).execute()
        rows = response.get("rows", [])

        # Transform rows to include page URL as a field
        urls = []
        for row in rows:
            url_data = {
                "page": row["keys"][0],
                "clicks": int(row.get("clicks", 0)),
                "impressions": int(row.get("impressions", 0)),
                "ctr": round(row.get("ctr", 0) * 100, 2),  # Convert to percentage
                "position": round(row.get("position", 0), 1),
            }
            urls.append(url_data)

        # Filter properties if specified
        if properties:
            urls = [{k: v for k, v in url.items() if k in properties} for url in urls]

        # Output
        if table:
            cols = properties[:5] if properties else ["page", "clicks", "impressions", "ctr", "position"]
            headers = [c.upper() if c in ["ctr"] else c.title() for c in cols]
            print_table(urls, cols, headers)
        else:
            print_json(urls)

    except HttpError as e:
        if _handle_api_not_enabled(e):
            raise typer.Exit(1)
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@urls_app.command("get")
@command
def searchconsole_urls_get(
    url: str = typer.Argument(..., help="URL to inspect"),
    site_url: Optional[str] = typer.Option(
        None,
        "--site-url",
        "-s",
        help="Search Console site URL (overrides GOOGLE_SEARCHCONSOLE_SITE env var)"
    ),
    table: bool = typer.Option(
        False,
        "--table",
        "-t",
        help="Output as table instead of JSON"
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Get indexing status and details for a specific URL.

    Uses the URL Inspection API to retrieve indexing information including:
    - Index status and verdict
    - Crawl information
    - Mobile usability
    - Rich results status

    Examples:
        google searchconsole urls get https://example.com/page
        google searchconsole urls get https://example.com/page --table
    """
    try:
        client = get_client(profile=profile)
        service = client.get_webmasters_service()
        config = get_config(profile=profile)

        # Get site URL from option or config
        site = site_url or config.searchconsole_site
        if not site:
            raise ValueError(
                "Search Console site URL not configured. "
                "Set GOOGLE_SEARCHCONSOLE_SITE environment variable or use --site-url."
            )

        # Request URL inspection
        response = service.urlInspection().index().inspect(
            body={
                "inspectionUrl": url,
                "siteUrl": site
            }
        ).execute()

        result = response.get("inspectionResult", {})

        if table:
            # Extract key fields for table display
            index_result = result.get("indexStatusResult", {})
            mobile_result = result.get("mobileUsabilityResult", {})

            table_data = [{
                "url": url,
                "verdict": index_result.get("verdict", "UNKNOWN"),
                "coverage": index_result.get("coverageState", "UNKNOWN"),
                "indexing": index_result.get("indexingState", "UNKNOWN"),
                "mobile": mobile_result.get("verdict", "UNKNOWN"),
            }]
            print_table(
                table_data,
                ["url", "verdict", "coverage", "indexing", "mobile"],
                ["URL", "Verdict", "Coverage", "Indexing", "Mobile"]
            )
        else:
            print_json(result)

    except HttpError as e:
        if _handle_api_not_enabled(e):
            raise typer.Exit(1)
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


sitemaps_app = typer.Typer(help="Manage submitted Search Console sitemaps")
app.add_typer(sitemaps_app, name="sitemaps")
SITEMAP_FIELDS = ["path", "lastSubmitted", "isPending", "isSitemapsIndex", "type", "lastDownloaded", "warnings", "errors", "contents"]


@sitemaps_app.command("list")
@command
def searchconsole_sitemaps_list(
    site_url: str = typer.Argument(..., help="Exact Search Console property URL or sc-domain property"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as table"),
    limit: int = typer.Option(100, "--limit", "-l", min=1, help="Maximum number of sitemaps"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Comma-separated output fields"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """List sitemaps submitted for a Search Console property."""
    from cli_tools_shared.filters import apply_filters

    fields = [field.strip() for item in properties for field in item.split(",")] if properties else SITEMAP_FIELDS
    unknown = set(fields) - set(SITEMAP_FIELDS)
    if unknown:
        raise ValueError(f"Unknown sitemap properties: {', '.join(sorted(unknown))}")
    service = get_client(profile=profile).get_webmasters_v3_service()
    rows = service.sitemaps().list(siteUrl=site_url).execute().get("sitemap", [])
    rows = apply_filters(rows, filter, allowed_fields=SITEMAP_FIELDS)[:limit]
    rows = [{key: value for key, value in row.items() if key in fields} for row in rows]
    if table:
        columns = fields if properties else ["path", "lastSubmitted", "isPending", "errors"]
        print_table(rows, columns, columns)
    else:
        print_json(rows)


@sitemaps_app.command("get")
@command
def searchconsole_sitemaps_get(
    site_url: str = typer.Argument(..., help="Exact Search Console property URL or sc-domain property"),
    sitemap_url: str = typer.Argument(..., help="Submitted sitemap URL"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Get Google's processing status for a submitted sitemap."""
    service = get_client(profile=profile).get_webmasters_v3_service()
    result = service.sitemaps().get(siteUrl=site_url, feedpath=sitemap_url).execute()
    if table:
        columns = ["path", "lastSubmitted", "isPending", "errors"]
        print_table([result], columns, columns)
    else:
        print_json(result)


@sitemaps_app.command("submit")
@command
def searchconsole_sitemaps_submit(
    site_url: str = typer.Argument(..., help="Exact Search Console property URL or sc-domain property"),
    sitemap_url: str = typer.Argument(..., help="Public sitemap URL to submit"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Submit a sitemap URL to Google; acceptance does not guarantee indexing."""
    service = get_client(profile=profile).get_webmasters_v3_service()
    service.sitemaps().submit(siteUrl=site_url, feedpath=sitemap_url).execute()
    print_json({"siteUrl": site_url, "path": sitemap_url, "submitted": True})


COVERAGE_FILE_NAMES = {
    "chart": "Chart.csv",
    "critical_issues": "Critical issues.csv",
    "non_critical_issues": "Non-critical issues.csv",
    "metadata": "Metadata.csv",
}
COVERAGE_REQUIRED_COLUMNS = {
    "chart": ("Date", "Not indexed", "Indexed", "Impressions"),
    "critical_issues": ("Reason", "Source", "Validation", "Pages"),
    "non_critical_issues": ("Reason", "Source", "Validation", "Pages"),
    "metadata": ("Property", "Value"),
}


def _coverage_member_name(filename: str) -> str:
    """Return the basename of a ZIP member for case-insensitive matching."""
    return filename.replace("\\", "/").rsplit("/", 1)[-1].strip().lower()


def _read_coverage_source(path: Path) -> dict[str, str]:
    """Read the four CSV files from a coverage ZIP or an extracted directory."""
    expected = {name.lower(): key for key, name in COVERAGE_FILE_NAMES.items()}
    found: dict[str, str] = {}

    def add(key: str, content: str, origin: str) -> None:
        if key in found:
            raise ValueError(
                f"Coverage export contains more than one {COVERAGE_FILE_NAMES[key]} ({origin})"
            )
        found[key] = content

    if path.is_dir():
        for child in path.iterdir():
            if not child.is_file():
                continue
            key = expected.get(child.name.strip().lower())
            if key is not None:
                add(key, child.read_text(encoding="utf-8-sig"), str(child))
    elif path.is_file() and zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for info in archive.infolist():
                if info.is_dir():
                    continue
                key = expected.get(_coverage_member_name(info.filename))
                if key is not None:
                    add(key, archive.read(info).decode("utf-8-sig"), info.filename)
    else:
        raise ValueError(f"Coverage export not found or not a ZIP/directory: {path}")

    missing = [COVERAGE_FILE_NAMES[key] for key in COVERAGE_FILE_NAMES if key not in found]
    if missing:
        raise ValueError(f"Coverage export is missing required file(s): {', '.join(missing)}")
    return found


def _coverage_rows(text: str, key: str) -> list[tuple[int, dict[str, str]]]:
    """Parse one CSV and verify its required columns."""
    filename = COVERAGE_FILE_NAMES[key]
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if reader.fieldnames is None:
        raise ValueError(f"{filename} is empty")
    missing = [
        column for column in COVERAGE_REQUIRED_COLUMNS[key]
        if column not in reader.fieldnames
    ]
    if missing:
        raise ValueError(
            f"{filename} is missing required column(s): {', '.join(missing)}"
        )
    rows = []
    for row_number, row in enumerate(reader, start=2):
        if None in row:
            raise ValueError(
                f"{filename} row {row_number} has more values than the header"
            )
        rows.append((row_number, row))
    return rows


def _coverage_optional_int(
    value: str | None,
    filename: str,
    row_number: int,
    column: str,
) -> int | None:
    """Parse an integer cell, preserving empty cells as null."""
    if value is None or not value.strip():
        return None
    try:
        return int(value.strip())
    except ValueError:
        raise ValueError(
            f"{filename} row {row_number}: {column} must be an integer, got {value!r}"
        ) from None


def _coverage_required_int(
    value: str | None,
    filename: str,
    row_number: int,
    column: str,
) -> int:
    """Parse a required integer cell."""
    result = _coverage_optional_int(value, filename, row_number, column)
    if result is None:
        raise ValueError(f"{filename} row {row_number}: {column} is empty")
    return result


def _coverage_issue_rows(text: str, key: str) -> list[dict[str, object]]:
    """Parse a critical or non-critical issues CSV."""
    filename = COVERAGE_FILE_NAMES[key]
    issues = []
    for row_number, row in _coverage_rows(text, key):
        reason = (row.get("Reason") or "").strip()
        if not reason:
            raise ValueError(f"{filename} row {row_number}: Reason is empty")
        issues.append({
            "reason": reason,
            "source": (row.get("Source") or "").strip(),
            "validation": (row.get("Validation") or "").strip(),
            "pages": _coverage_required_int(
                row.get("Pages"), filename, row_number, "Pages"
            ),
        })
    return issues


def _parse_coverage_export(path: Path) -> dict:
    """Parse a Page indexing CSV export into a structured payload."""
    files = _read_coverage_source(path)

    chart = []
    for row_number, row in _coverage_rows(files["chart"], "chart"):
        date_value = (row.get("Date") or "").strip()
        try:
            date.fromisoformat(date_value)
        except ValueError:
            raise ValueError(
                f"Chart.csv row {row_number}: Date must be YYYY-MM-DD, "
                f"got {date_value!r}"
            ) from None
        chart.append({
            "date": date_value,
            "not_indexed": _coverage_optional_int(
                row.get("Not indexed"), "Chart.csv", row_number, "Not indexed"
            ),
            "indexed": _coverage_optional_int(
                row.get("Indexed"), "Chart.csv", row_number, "Indexed"
            ),
            "impressions": _coverage_optional_int(
                row.get("Impressions"), "Chart.csv", row_number, "Impressions"
            ),
        })

    metadata = []
    for row_number, row in _coverage_rows(files["metadata"], "metadata"):
        prop = (row.get("Property") or "").strip()
        if not prop:
            raise ValueError(f"Metadata.csv row {row_number}: Property is empty")
        metadata.append({
            "property": prop,
            "value": (row.get("Value") or "").strip(),
        })

    critical_issues = _coverage_issue_rows(files["critical_issues"], "critical_issues")
    non_critical_issues = _coverage_issue_rows(
        files["non_critical_issues"], "non_critical_issues"
    )
    latest = next(
        (
            row for row in reversed(chart)
            if row["not_indexed"] is not None or row["indexed"] is not None
        ),
        None,
    )
    return {
        "source": str(path),
        "metadata": metadata,
        "latest": latest,
        "chart": chart,
        "critical_issues": critical_issues,
        "non_critical_issues": non_critical_issues,
        "totals": {
            "critical_pages": sum(
                issue["pages"] for issue in critical_issues
            ),
            "non_critical_pages": sum(
                issue["pages"] for issue in non_critical_issues
            ),
        },
    }


def _print_coverage_tables(payload: dict) -> None:
    """Print the parsed coverage export as readable tables."""
    tables = []
    if payload["metadata"]:
        tables.append((
            payload["metadata"],
            ["property", "value"],
            ["Property", "Value"],
        ))
    if payload["latest"] is not None:
        tables.append((
            [payload["latest"]],
            ["date", "not_indexed", "indexed", "impressions"],
            ["Date", "Not Indexed", "Indexed", "Impressions"],
        ))
    if payload["critical_issues"]:
        tables.append((
            payload["critical_issues"],
            ["reason", "source", "validation", "pages"],
            ["Reason", "Source", "Validation", "Pages"],
        ))
    if payload["non_critical_issues"]:
        tables.append((
            payload["non_critical_issues"],
            ["reason", "source", "validation", "pages"],
            ["Reason", "Source", "Validation", "Pages"],
        ))
    for index, (rows, columns, headers) in enumerate(tables):
        if index:
            typer.echo()
        print_table(rows, columns, headers)


coverage_app = typer.Typer(
    help="Parse Page indexing (coverage) exports",
    no_args_is_help=True,
)
app.add_typer(coverage_app, name="coverage")


@coverage_app.command("parse")
@command
def searchconsole_coverage_parse(
    export_path: str = typer.Argument(
        ...,
        help="Path to a Coverage export .zip or extracted directory",
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Parse a Google Search Console Page indexing export."""
    payload = _parse_coverage_export(Path(export_path).expanduser())
    if table:
        _print_coverage_tables(payload)
    else:
        print_json(payload)
