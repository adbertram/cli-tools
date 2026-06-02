"""Traffic commands for Raptive CLI."""
from typing import List, Optional

import typer

from ..client import get_client, ClientError
from ..output import print_json, print_table, handle_error, apply_limit, apply_properties
from cli_tools_shared.filters import apply_filters

COMMAND_CREDENTIALS = {
    "by-device": [
        "browser_session"
    ],
    "sources": [
        "browser_session"
    ]
}

app = typer.Typer(help="View traffic and session data")


@app.command("sources")
def traffic_sources(
    filter_: Optional[List[str]] = typer.Option(
        None,
        "--filter", "-f",
        help="Filter results (field:op:value). Operators: eq, ne, gt, gte, lt, lte, in, like, contains",
    ),
    limit: Optional[int] = typer.Option(
        None,
        "--limit", "-l",
        help="Maximum number of results to return",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties", "-p",
        help="Comma-separated list of properties to include",
    ),
    table: bool = typer.Option(
        False,
        "--table", "-t",
        help="Display as table",
    ),
):
    """
    Get traffic breakdown by source.

    Shows sessions from different traffic sources (direct, google, bing, etc.).

    Note: The Raptive API does not support date filtering for this endpoint.
    Data reflects the default dashboard period.

    Examples:
        raptive traffic sources --filter source:eq:google
        raptive traffic sources --filter sessions:gt:1000 --table
        raptive traffic sources --limit 5
        raptive traffic sources --properties source,sessions
    """
    try:
        client = get_client()
        sources = client.get_traffic_sources()
        client.close()

        # Convert to dicts and apply client-side filtering/limiting/properties
        data = [s.to_dict() for s in sources]
        data = apply_filters(data, filter_)
        data = apply_limit(data, limit)
        data = apply_properties(data, properties)

        if table:
            # Show date range header
            if data and "start_date" in data[0]:
                typer.echo(f"Period: {data[0]['start_date']} to {data[0]['end_date']}\n")
            rows = []
            for s in data:
                rows.append({
                    "source": s.get("source", ""),
                    "sessions": f"{s['sessions']:,}" if s.get("sessions") else "N/A",
                })
            print_table(rows, ["source", "sessions"], ["Source", "Sessions"])
        else:
            print_json(data)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("by-device")
def traffic_by_device(
    filter_: Optional[List[str]] = typer.Option(
        None,
        "--filter", "-f",
        help="Filter results (field:op:value). Operators: eq, ne, gt, gte, lt, lte, in, like, contains",
    ),
    limit: Optional[int] = typer.Option(
        None,
        "--limit", "-l",
        help="Maximum number of results to return",
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties", "-p",
        help="Comma-separated list of properties to include",
    ),
    table: bool = typer.Option(
        False,
        "--table", "-t",
        help="Display as table",
    ),
):
    """
    Get traffic breakdown by device type.

    Shows sessions for Desktop, Mobile, and Tablet.

    Examples:
        raptive traffic by-device --filter device:eq:Mobile
        raptive traffic by-device --filter sessions:gt:5000 --table
        raptive traffic by-device --limit 2
        raptive traffic by-device --properties device,sessions
    """
    try:
        client = get_client()
        traffic = client.get_device_traffic()
        client.close()

        # Convert to dicts and apply client-side filtering/limiting/properties
        data = [t.to_dict() for t in traffic]
        data = apply_filters(data, filter_)
        data = apply_limit(data, limit)
        data = apply_properties(data, properties)

        if table:
            rows = []
            for t in data:
                device_val = t.get("device", "")
                if hasattr(device_val, "value"):
                    device_val = device_val.value
                rows.append({
                    "device": device_val,
                    "sessions": f"{t['sessions']:,}" if t.get("sessions") else "N/A",
                    "pageviews": f"{t['pageviews']:,}" if t.get("pageviews") else "N/A",
                    "pages_per_session": f"{t['pages_per_session']:.2f}" if t.get("pages_per_session") else "N/A",
                })
            print_table(rows, ["device", "sessions", "pageviews", "pages_per_session"], ["Device", "Sessions", "Pageviews", "Pages/Session"])
        else:
            print_json(data)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))
