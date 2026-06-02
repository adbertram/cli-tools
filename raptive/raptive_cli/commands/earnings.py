"""Earnings commands for Raptive CLI."""
from typing import List, Optional

import typer

from ..client import get_client, ClientError
from ..dates import get_date_range
from ..output import print_json, print_table, handle_error, apply_limit, apply_properties
from cli_tools_shared.filters import apply_filters

COMMAND_CREDENTIALS = {
    "brand-safety": [
        "browser_session"
    ],
    "by-category": [
        "browser_session"
    ],
    "by-country": [
        "browser_session"
    ],
    "by-device": [
        "browser_session"
    ],
    "by-page": [
        "browser_session"
    ],
    "by-traffic-source": [
        "browser_session"
    ],
    "overview": [
        "browser_session"
    ],
    "sources": [
        "browser_session"
    ]
}

app = typer.Typer(help="View earnings and revenue data")


@app.command("overview")
def earnings_overview(
    period: str = typer.Option(
        "last30d",
        "--period",
        help="Time period: yesterday, last7d, last30d, mtd, lastmonth",
    ),
    start: str = typer.Option(
        None,
        "--start", "-s",
        help="Start date (YYYY-MM-DD). Overrides --period.",
    ),
    end: str = typer.Option(
        None,
        "--end", "-e",
        help="End date (YYYY-MM-DD). Overrides --period.",
    ),
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
    Get daily earnings breakdown for a date range.

    Shows earnings, sessions, RPM for each day.

    Examples:
        raptive earnings overview --period last7d
        raptive earnings overview --start 2025-12-01 --end 2025-12-31 --table
        raptive earnings overview --filter earnings:gt:100
        raptive earnings overview --limit 7 --properties date,earnings
    """
    try:
        start_date, end_date = get_date_range(period, start, end)

        client = get_client()
        earnings = client.get_earnings_overview(start_date, end_date)
        client.close()

        # Convert to dicts and apply client-side filtering/limiting/properties
        data = [e.to_dict() for e in earnings]
        data = apply_filters(data, filter_)
        data = apply_limit(data, limit)
        data = apply_properties(data, properties)

        if table:
            rows = []
            for e in data:
                rows.append({
                    "date": e.get("date", ""),
                    "earnings": f"${e['earnings']:.2f}" if e.get("earnings") is not None else "N/A",
                    "rpm": f"${e['rpm']:.2f}" if e.get("rpm") else "N/A",
                    "sessions": f"{e['sessions']:,}" if e.get("sessions") else "N/A",
                })
            print_table(rows, ["date", "earnings", "rpm", "sessions"], ["Date", "Earnings", "RPM", "Sessions"])
        else:
            print_json(data)

    except ValueError as e:
        raise typer.Exit(handle_error(e))
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("by-device")
def earnings_by_device(
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
    Get earnings breakdown by device type.

    Shows earnings for Desktop, Mobile, and Tablet.

    Examples:
        raptive earnings by-device --filter device:eq:Mobile
        raptive earnings by-device --filter earnings:gt:50 --table
        raptive earnings by-device --properties device,earnings
    """
    try:
        client = get_client()
        earnings = client.get_device_earnings()
        client.close()

        # Convert to dicts and apply client-side filtering/limiting/properties
        data = [e.to_dict() for e in earnings]
        data = apply_filters(data, filter_)
        data = apply_limit(data, limit)
        data = apply_properties(data, properties)

        if table:
            rows = []
            for e in data:
                device_val = e.get("device", "")
                if hasattr(device_val, "value"):
                    device_val = device_val.value
                rows.append({
                    "device": device_val,
                    "earnings": f"${e['earnings']:.2f}" if e.get("earnings") is not None else "N/A",
                    "rpm": f"${e['rpm']:.2f}" if e.get("rpm") else "N/A",
                    "sessions": f"{e['sessions']:,}" if e.get("sessions") else "N/A",
                })
            print_table(rows, ["device", "earnings", "rpm", "sessions"], ["Device", "Earnings", "RPM", "Sessions"])
        else:
            print_json(data)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("by-page")
def earnings_by_page(
    period: str = typer.Option(
        "last30d",
        "--period",
        help="Time period: yesterday, last7d, last30d, mtd, lastmonth",
    ),
    start: str = typer.Option(
        None,
        "--start", "-s",
        help="Start date (YYYY-MM-DD). Overrides --period.",
    ),
    end: str = typer.Option(
        None,
        "--end", "-e",
        help="End date (YYYY-MM-DD). Overrides --period.",
    ),
    limit: int = typer.Option(
        20,
        "--limit", "-l",
        help="Maximum number of pages to return",
    ),
    min_pageviews: Optional[int] = typer.Option(
        None,
        "--min-pageviews",
        help="Minimum pageviews filter (server-side)",
    ),
    max_pageviews: Optional[int] = typer.Option(
        None,
        "--max-pageviews",
        help="Maximum pageviews filter (server-side)",
    ),
    min_rpm: Optional[float] = typer.Option(
        None,
        "--min-rpm",
        help="Minimum page RPM filter (server-side)",
    ),
    max_rpm: Optional[float] = typer.Option(
        None,
        "--max-rpm",
        help="Maximum page RPM filter (server-side)",
    ),
    search: Optional[str] = typer.Option(
        None,
        "--search", "-q",
        help="Search term to filter page URLs (server-side, contains match)",
    ),
    filter_: Optional[List[str]] = typer.Option(
        None,
        "--filter", "-f",
        help="Filter results (field:op:value). Operators: eq, ne, gt, gte, lt, lte, in, like, contains",
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
    Get earnings breakdown by page.

    Shows page-level performance metrics sorted by pageviews.

    Examples:
        raptive earnings by-page --period last7d --table
        raptive earnings by-page --limit 50
        raptive earnings by-page --min-pageviews 50 --search spark
        raptive earnings by-page --min-rpm 10 --limit 100
        raptive earnings by-page --filter earnings:gt:10
        raptive earnings by-page --properties page_url,earnings
    """
    try:
        start_date, end_date = get_date_range(period, start, end)

        client = get_client()
        pages = client.get_page_performance(
            start_date,
            end_date,
            limit,
            min_pageviews=min_pageviews,
            max_pageviews=max_pageviews,
            min_rpm=min_rpm,
            max_rpm=max_rpm,
            search=search,
        )
        client.close()

        # Convert to dicts and apply client-side filtering/properties
        data = [p.to_dict() for p in pages]
        data = apply_filters(data, filter_)
        data = apply_properties(data, properties)

        if table:
            if data and "start_date" in data[0]:
                typer.echo(f"Period: {data[0]['start_date']} to {data[0]['end_date']}\n")
            rows = []
            for p in data:
                page_url = p.get("page_url") or ""
                rows.append({
                    "page_url": page_url[:50] + "..." if len(page_url) > 50 else page_url,
                    "pageviews": f"{p['pageviews']:,}" if p.get("pageviews") else "N/A",
                    "earnings": f"${p['earnings']:.2f}" if p.get("earnings") is not None else "N/A",
                    "rpm": f"${p['rpm']:.2f}" if p.get("rpm") is not None else "N/A",
                })
            print_table(rows, ["page_url", "pageviews", "earnings", "rpm"], ["Page URL", "Pageviews", "Earnings", "RPM"])
        else:
            print_json(data)

    except ValueError as e:
        raise typer.Exit(handle_error(e))
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("by-traffic-source")
def earnings_by_traffic_source(
    period: str = typer.Option(
        "last30d",
        "--period",
        help="Time period: yesterday, last7d, last30d, mtd, lastmonth",
    ),
    start: str = typer.Option(
        None,
        "--start", "-s",
        help="Start date (YYYY-MM-DD). Overrides --period.",
    ),
    end: str = typer.Option(
        None,
        "--end", "-e",
        help="End date (YYYY-MM-DD). Overrides --period.",
    ),
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
    Get earnings breakdown by traffic source.

    Shows performance metrics for each traffic source (direct, google, etc.).

    Examples:
        raptive earnings by-traffic-source --period last7d --table
        raptive earnings by-traffic-source --filter traffic_source:eq:google
        raptive earnings by-traffic-source --properties traffic_source,earnings
    """
    try:
        start_date, end_date = get_date_range(period, start, end)

        client = get_client()
        sources = client.get_traffic_source_performance(start_date, end_date)
        client.close()

        # Convert to dicts and apply client-side filtering/limiting/properties
        data = [s.to_dict() for s in sources]
        data = apply_filters(data, filter_)
        data = apply_limit(data, limit)
        data = apply_properties(data, properties)

        if table:
            if data and "start_date" in data[0]:
                typer.echo(f"Period: {data[0]['start_date']} to {data[0]['end_date']}\n")
            rows = []
            for s in data:
                rows.append({
                    "source": s.get("traffic_source", ""),
                    "sessions": f"{s['sessions']:,}" if s.get("sessions") else "N/A",
                    "pageviews": f"{s['pageviews']:,}" if s.get("pageviews") else "N/A",
                    "earnings": f"${s['earnings']:.2f}" if s.get("earnings") is not None else "N/A",
                    "rpm": f"${s['rpm']:.2f}" if s.get("rpm") is not None else "N/A",
                })
            print_table(rows, ["source", "sessions", "pageviews", "earnings", "rpm"], ["Source", "Sessions", "Pageviews", "Earnings", "RPM"])
        else:
            print_json(data)

    except ValueError as e:
        raise typer.Exit(handle_error(e))
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("by-country")
def earnings_by_country(
    period: str = typer.Option(
        "last30d",
        "--period",
        help="Time period: yesterday, last7d, last30d, mtd, lastmonth",
    ),
    start: str = typer.Option(
        None,
        "--start", "-s",
        help="Start date (YYYY-MM-DD). Overrides --period.",
    ),
    end: str = typer.Option(
        None,
        "--end", "-e",
        help="End date (YYYY-MM-DD). Overrides --period.",
    ),
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
    Get earnings breakdown by country.

    Shows performance metrics for each country.

    Examples:
        raptive earnings by-country --period last7d --table
        raptive earnings by-country --filter country:in:United States|Canada
        raptive earnings by-country --limit 10 --properties country,earnings
    """
    try:
        start_date, end_date = get_date_range(period, start, end)

        client = get_client()
        countries = client.get_country_performance(start_date, end_date)
        client.close()

        # Filter out countries with no earnings and sort by earnings
        countries = [c for c in countries if c.earnings > 0]
        countries.sort(key=lambda x: x.earnings, reverse=True)

        # Convert to dicts and apply client-side filtering/limiting/properties
        data = [c.to_dict() for c in countries]
        data = apply_filters(data, filter_)
        data = apply_limit(data, limit)
        data = apply_properties(data, properties)

        if table:
            if data and "start_date" in data[0]:
                typer.echo(f"Period: {data[0]['start_date']} to {data[0]['end_date']}\n")
            rows = []
            for c in data:
                rows.append({
                    "country": c.get("country", ""),
                    "sessions": f"{c['sessions']:,}" if c.get("sessions") else "N/A",
                    "pageviews": f"{c['pageviews']:,}" if c.get("pageviews") else "N/A",
                    "earnings": f"${c['earnings']:.2f}" if c.get("earnings") is not None else "N/A",
                    "rpm": f"${c['rpm']:.2f}" if c.get("rpm") is not None else "N/A",
                })
            print_table(rows, ["country", "sessions", "pageviews", "earnings", "rpm"], ["Country", "Sessions", "Pageviews", "Earnings", "RPM"])
        else:
            print_json(data)

    except ValueError as e:
        raise typer.Exit(handle_error(e))
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("by-category")
def earnings_by_category(
    period: str = typer.Option(
        "last30d",
        "--period",
        help="Time period: yesterday, last7d, last30d, mtd, lastmonth",
    ),
    start: str = typer.Option(
        None,
        "--start", "-s",
        help="Start date (YYYY-MM-DD). Overrides --period.",
    ),
    end: str = typer.Option(
        None,
        "--end", "-e",
        help="End date (YYYY-MM-DD). Overrides --period.",
    ),
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
    Get earnings breakdown by category.

    Shows performance metrics for each content category.

    Examples:
        raptive earnings by-category --period last7d --table
        raptive earnings by-category --filter earnings:gt:100
        raptive earnings by-category --properties category,earnings
    """
    try:
        start_date, end_date = get_date_range(period, start, end)

        client = get_client()
        categories = client.get_category_performance(start_date, end_date)
        client.close()

        # Sort by earnings
        categories.sort(key=lambda x: x.earnings, reverse=True)

        # Convert to dicts and apply client-side filtering/limiting/properties
        data = [c.to_dict() for c in categories]
        data = apply_filters(data, filter_)
        data = apply_limit(data, limit)
        data = apply_properties(data, properties)

        if table:
            if data and "start_date" in data[0]:
                typer.echo(f"Period: {data[0]['start_date']} to {data[0]['end_date']}\n")
            rows = []
            for c in data:
                rows.append({
                    "category": c.get("category", ""),
                    "posts": str(c.get("num_posts") or "N/A"),
                    "pageviews": f"{c['pageviews']:,}" if c.get("pageviews") else "N/A",
                    "earnings": f"${c['earnings']:.2f}" if c.get("earnings") is not None else "N/A",
                    "rpm": f"${c['rpm']:.2f}" if c.get("rpm") is not None else "N/A",
                })
            print_table(rows, ["category", "posts", "pageviews", "earnings", "rpm"], ["Category", "Posts", "Pageviews", "Earnings", "RPM"])
        else:
            print_json(data)

    except ValueError as e:
        raise typer.Exit(handle_error(e))
    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("brand-safety")
def earnings_brand_safety(
    limit: int = typer.Option(
        20,
        "--limit", "-l",
        help="Maximum number of pages to return",
    ),
    filter_: Optional[List[str]] = typer.Option(
        None,
        "--filter", "-f",
        help="Filter results (field:op:value). Operators: eq, ne, gt, gte, lt, lte, in, like, contains",
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
    Get brand safety assessments for pages.

    Shows pages with brand safety ratings sorted by pageviews.

    Examples:
        raptive earnings brand-safety --table
        raptive earnings brand-safety --limit 50
        raptive earnings brand-safety --filter alc:ne:normal
        raptive earnings brand-safety --properties pagepath,pageviews,alc
    """
    try:
        client = get_client()
        pages = client.get_brand_safety(limit)
        client.close()

        # Convert to dicts and apply client-side filtering/properties
        data = [p.to_dict() for p in pages]
        data = apply_filters(data, filter_)
        data = apply_properties(data, properties)

        if table:
            rows = []
            for p in data:
                # Show only non-normal ratings
                issues = []
                if p.get("alc") != "normal":
                    issues.append(f"alc:{p.get('alc')}")
                if p.get("adt") != "normal":
                    issues.append(f"adt:{p.get('adt')}")
                if p.get("vio") != "normal":
                    issues.append(f"vio:{p.get('vio')}")
                if p.get("hat") != "normal":
                    issues.append(f"hat:{p.get('hat')}")
                if p.get("drg") != "normal":
                    issues.append(f"drg:{p.get('drg')}")

                pagepath = p.get("pagepath", "")
                rows.append({
                    "page": pagepath[:40] + "..." if len(pagepath) > 40 else pagepath,
                    "pageviews": f"{p['pageviews']:,}" if p.get("pageviews") else "N/A",
                    "rpm": f"${p['rpm']:.2f}" if p.get("rpm") is not None else "N/A",
                    "issues": ", ".join(issues) if issues else "Clean",
                })
            print_table(rows, ["page", "pageviews", "rpm", "issues"], ["Page", "Pageviews", "RPM", "Issues"])
        else:
            print_json(data)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("sources")
def earnings_sources(
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
    Get earnings breakdown by ad network source.

    Shows monthly earnings from each ad network.

    Examples:
        raptive earnings sources --table
        raptive earnings sources --filter ad_network:eq:AdSense
        raptive earnings sources --filter earnings:gt:500
        raptive earnings sources --properties ad_network,earnings
    """
    try:
        client = get_client()
        sources = client.get_ad_network_earnings()
        client.close()

        # Convert to dicts and apply client-side filtering/limiting/properties
        data = [s.to_dict() for s in sources]
        data = apply_filters(data, filter_)
        data = apply_limit(data, limit)
        data = apply_properties(data, properties)

        if table:
            rows = []
            for s in data:
                rows.append({
                    "network": s.get("ad_network", ""),
                    "month": f"{s['year']}-{s['month']:02d}" if s.get("year") and s.get("month") else "N/A",
                    "earnings": f"${s['earnings']:.2f}" if s.get("earnings") is not None else "N/A",
                })
            print_table(rows, ["network", "month", "earnings"], ["Ad Network", "Month", "Earnings"])
        else:
            print_json(data)

    except ClientError as e:
        raise typer.Exit(handle_error(e))
    except Exception as e:
        raise typer.Exit(handle_error(e))
