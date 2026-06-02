"""Google Analytics commands."""
COMMAND_CREDENTIALS = {
    "accounts": ["custom"],
    "properties": ["custom"],
    "report": ["custom"],
    "top-pages": ["custom"],
    "traffic": ["custom"],
    "realtime": ["custom"],
}

import typer
from datetime import datetime, timedelta
from typing import Optional, List
from googleapiclient.errors import HttpError
from ..client import get_client
from ..config import get_config
from cli_tools_shared.output import print_json, print_table, handle_error, print_error

app = typer.Typer(help="Access Google Analytics data")


def _get_property_id(property_opt: Optional[str], profile=None) -> str:
    """Resolve GA4 property ID from option or env var."""
    if property_opt:
        return property_opt
    config = get_config(profile=profile)
    prop_id = config.analytics_property_id
    if not prop_id:
        print_error("No property ID provided. Use --property or set GOOGLE_ANALYTICS_PROPERTY_ID")
        raise typer.Exit(1)
    return prop_id


def _build_dimension_filter(filter_str: str) -> dict:
    """Convert filter string to GA4 API dimension filter expression.

    Supports formats:
    - field:op:value (e.g., 'pagePath:contains:/blog/')
    - field:value (defaults to 'contains' operator)

    Operators: eq (exact), contains, beginsWith, endsWith, regex
    """
    parts = filter_str.split(":", 2)

    if len(parts) == 2:
        field_name, value = parts
        match_type = "CONTAINS"
    elif len(parts) >= 3:
        field_name, op, value = parts[0], parts[1], parts[2]
        op_map = {
            "eq": "EXACT",
            "exact": "EXACT",
            "contains": "CONTAINS",
            "beginsWith": "BEGINS_WITH",
            "begins_with": "BEGINS_WITH",
            "endsWith": "ENDS_WITH",
            "ends_with": "ENDS_WITH",
            "regex": "FULL_REGEXP",
            "partial_regex": "PARTIAL_REGEXP",
        }
        match_type = op_map.get(op)
        if not match_type:
            raise ValueError(f"Unknown filter operator '{op}'. Valid: {', '.join(op_map.keys())}")
    else:
        raise ValueError(f"Invalid filter format: {filter_str}. Use field:op:value or field:value")

    return {
        "filter": {
            "fieldName": field_name,
            "stringFilter": {
                "matchType": match_type,
                "value": value,
            },
        }
    }


def _build_dimension_filter_clause(filter_strings: list[str]) -> dict:
    """Build a GA4 dimensionFilter clause from multiple filter strings.

    Multiple filters are combined with AND logic.
    """
    expressions = [_build_dimension_filter(f) for f in filter_strings]

    if len(expressions) == 1:
        return expressions[0]

    return {"andGroup": {"expressions": expressions}}


def _format_report_rows(response: dict) -> list[dict]:
    """Transform GA4 report response into flat dicts."""
    dimension_headers = [h["name"] for h in response.get("dimensionHeaders", [])]
    metric_headers = [h["name"] for h in response.get("metricHeaders", [])]
    rows = response.get("rows", [])

    results = []
    for row in rows:
        record = {}
        for i, val in enumerate(row.get("dimensionValues", [])):
            record[dimension_headers[i]] = val["value"]
        for i, val in enumerate(row.get("metricValues", [])):
            record[metric_headers[i]] = val["value"]
        results.append(record)
    return results


def _format_account_properties(account_summaries: list[dict], properties: Optional[List[str]] = None) -> list[dict]:
    """Flatten GA4 account summaries into property records."""
    formatted = []
    for account in account_summaries:
        account_name = account.get("displayName", "")
        account_id = account.get("account", "").replace("accounts/", "")
        for prop in account.get("propertySummaries", []):
            record = {
                "account_name": account_name,
                "account_id": account_id,
                "property_name": prop.get("displayName", ""),
                "property_id": prop.get("property", "").replace("properties/", ""),
            }
            if properties:
                record = {k: v for k, v in record.items() if k in properties}
            formatted.append(record)
    return formatted


@app.command("accounts")
def analytics_accounts(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of accounts to list"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Properties to include in output"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """List GA4 accounts and properties."""
    try:
        client = get_client(profile=profile)
        service = client.get_analytics_admin_service()

        result = service.accountSummaries().list(pageSize=limit).execute()
        account_summaries = result.get("accountSummaries", [])

        if not account_summaries:
            print_error("No GA4 accounts found")
            raise typer.Exit(1)

        formatted = _format_account_properties(account_summaries, properties)

        if table:
            default_cols = ["account_name", "account_id", "property_name", "property_id"]
            cols = [c for c in default_cols if c in (properties or default_cols)]
            headers = {
                "account_name": "Account",
                "account_id": "Account ID",
                "property_name": "Property",
                "property_id": "Property ID",
            }
            print_table(formatted[:limit], cols, [headers.get(c, c) for c in cols])
        else:
            print_json(formatted[:limit])

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("properties")
def analytics_properties(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of properties to list"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Properties to include in output"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """List GA4 properties."""
    try:
        client = get_client(profile=profile)
        service = client.get_analytics_admin_service()

        result = service.accountSummaries().list(pageSize=limit).execute()
        formatted = _format_account_properties(result.get("accountSummaries", []), properties)

        if not formatted:
            print_error("No GA4 properties found")
            raise typer.Exit(1)

        if table:
            default_cols = ["account_name", "account_id", "property_name", "property_id"]
            cols = [c for c in default_cols if c in (properties or default_cols)]
            headers = {
                "account_name": "Account",
                "account_id": "Account ID",
                "property_name": "Property",
                "property_id": "Property ID",
            }
            print_table(formatted[:limit], cols, [headers.get(c, c) for c in cols])
        else:
            print_json(formatted[:limit])

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("report")
def analytics_report(
    metrics: str = typer.Option(..., "--metrics", "-m", help="Comma-separated metrics (e.g., sessions,activeUsers)"),
    dimensions: Optional[str] = typer.Option(None, "--dimensions", "-d", help="Comma-separated dimensions (e.g., date,pagePath)"),
    start: str = typer.Option(None, "--start", "-s", help="Start date (YYYY-MM-DD, default: 7 days ago)"),
    end: str = typer.Option(None, "--end", "-e", help="End date (YYYY-MM-DD, default: today)"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of rows"),
    order_by: Optional[str] = typer.Option(None, "--order-by", help="Metric or dimension to order by"),
    desc: bool = typer.Option(True, "--desc/--asc", help="Sort descending (default) or ascending"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    property: Optional[str] = typer.Option(None, "--property", help="GA4 property ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Run a custom GA4 report with dimensions and metrics."""
    try:
        prop_id = _get_property_id(property, profile=profile)
        client = get_client(profile=profile)
        service = client.get_analytics_data_service()

        # Default date range: last 7 days
        if not start:
            start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        if not end:
            end = datetime.now().strftime("%Y-%m-%d")

        body = {
            "dateRanges": [{"startDate": start, "endDate": end}],
            "metrics": [{"name": m.strip()} for m in metrics.split(",")],
            "limit": limit,
        }

        if dimensions:
            body["dimensions"] = [{"name": d.strip()} for d in dimensions.split(",")]

        if filter:
            body["dimensionFilter"] = _build_dimension_filter_clause(filter)

        if order_by:
            order_type = "DESC" if desc else "ASC"
            # Determine if order_by is a metric or dimension
            metric_names = [m.strip() for m in metrics.split(",")]
            if order_by in metric_names:
                body["orderBys"] = [{"metric": {"metricName": order_by}, "desc": desc}]
            else:
                body["orderBys"] = [{"dimension": {"dimensionName": order_by}, "desc": desc}]

        response = service.properties().runReport(
            property=f"properties/{prop_id}",
            body=body,
        ).execute()

        results = _format_report_rows(response)

        if not results:
            print_error("No data returned for this report")
            raise typer.Exit(1)

        if table:
            cols = list(results[0].keys())
            print_table(results, cols, [c for c in cols])
        else:
            print_json(results)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("top-pages")
def analytics_top_pages(
    days: int = typer.Option(7, "--days", "-d", help="Number of days to look back"),
    limit: int = typer.Option(10, "--limit", "-l", help="Maximum number of pages"),
    property: Optional[str] = typer.Option(None, "--property", help="GA4 property ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Show top pages by pageviews."""
    try:
        prop_id = _get_property_id(property, profile=profile)
        client = get_client(profile=profile)
        service = client.get_analytics_data_service()

        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        end_date = datetime.now().strftime("%Y-%m-%d")

        response = service.properties().runReport(
            property=f"properties/{prop_id}",
            body={
                "dateRanges": [{"startDate": start_date, "endDate": end_date}],
                "dimensions": [{"name": "pagePath"}],
                "metrics": [{"name": "screenPageViews"}],
                "orderBys": [{"metric": {"metricName": "screenPageViews"}, "desc": True}],
                "limit": limit,
            },
        ).execute()

        results = _format_report_rows(response)

        if not results:
            print_error("No page data found")
            raise typer.Exit(1)

        if table:
            print_table(results, ["pagePath", "screenPageViews"], ["Page", "Views"])
        else:
            print_json(results)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("traffic")
def analytics_traffic(
    days: int = typer.Option(7, "--days", "-d", help="Number of days to look back"),
    limit: int = typer.Option(10, "--limit", "-l", help="Maximum number of sources"),
    property: Optional[str] = typer.Option(None, "--property", help="GA4 property ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Show traffic sources breakdown."""
    try:
        prop_id = _get_property_id(property, profile=profile)
        client = get_client(profile=profile)
        service = client.get_analytics_data_service()

        start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        end_date = datetime.now().strftime("%Y-%m-%d")

        response = service.properties().runReport(
            property=f"properties/{prop_id}",
            body={
                "dateRanges": [{"startDate": start_date, "endDate": end_date}],
                "dimensions": [{"name": "sessionSource"}, {"name": "sessionMedium"}],
                "metrics": [{"name": "sessions"}, {"name": "activeUsers"}],
                "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
                "limit": limit,
            },
        ).execute()

        results = _format_report_rows(response)

        if not results:
            print_error("No traffic data found")
            raise typer.Exit(1)

        if table:
            print_table(
                results,
                ["sessionSource", "sessionMedium", "sessions", "activeUsers"],
                ["Source", "Medium", "Sessions", "Active Users"],
            )
        else:
            print_json(results)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("realtime")
def analytics_realtime(
    property: Optional[str] = typer.Option(None, "--property", help="GA4 property ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Show real-time active users and pages."""
    try:
        prop_id = _get_property_id(property, profile=profile)
        client = get_client(profile=profile)
        service = client.get_analytics_data_service()

        response = service.properties().runRealtimeReport(
            property=f"properties/{prop_id}",
            body={
                "dimensions": [{"name": "unifiedScreenName"}],
                "metrics": [{"name": "activeUsers"}],
            },
        ).execute()

        results = _format_report_rows(response)

        if not results:
            print_error("No real-time data available")
            raise typer.Exit(1)

        if table:
            print_table(results, ["unifiedScreenName", "activeUsers"], ["Page/Screen", "Active Users"])
        else:
            print_json(results)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))
