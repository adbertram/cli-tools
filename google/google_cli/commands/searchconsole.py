"""Google Search Console commands."""
COMMAND_CREDENTIALS = {
    "index": ["custom"],
    "sites": ["custom"],
    "urls": ["custom"],
}

import re
from datetime import datetime, timedelta
import typer
from typing import Optional, List
from googleapiclient.errors import HttpError
from ..client import get_client
from cli_tools_shared.output import print_json, print_table, print_success, print_error, handle_error
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
    """Request Google to crawl and index a URL via URL Inspection API."""
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
