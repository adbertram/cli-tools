"""Earnings commands for ATA Blog CLI.

Query Raptive ad revenue and performance data for posts.
Wraps the raptive CLI earnings by-page functionality with
post-friendly filtering options.
"""
import json
import subprocess
from datetime import datetime
from typing import List, Optional

import typer
from cli_tools_shared.output import command

from cli_tools_shared.filters import apply_filters, validate_filters
from ..corpus import SPONSORED_TAG_NAME, list_posts, list_terms
from ..models import create_post_earnings
from cli_tools_shared.output import print_error, print_info, print_json, print_table

COMMAND_CREDENTIALS = {
    "get": ["custom"],
    "list": ["custom"],
}

app = typer.Typer(help="Query ad earnings and revenue data", no_args_is_help=True)


def _run_raptive(args: list) -> subprocess.CompletedProcess:
    """Run raptive CLI command."""
    cmd = ["raptive"] + args
    return subprocess.run(cmd, capture_output=True, text=True)


def _page_slug(item: dict) -> str:
    """Return the post slug a Raptive page_url addresses."""
    return (item.get("page_url") or "").strip("/")


def _sponsored_slugs(posts: List[dict]) -> set:
    """Return the slug of every static site post carrying the Sponsored tag."""
    sponsored_ids = [
        term["id"] for term in list_terms("tags") if term["name"] == SPONSORED_TAG_NAME
    ]
    if len(sponsored_ids) != 1:
        raise ValueError(
            f"Static site terms must contain exactly one {SPONSORED_TAG_NAME!r} tag; "
            f"found {len(sponsored_ids)}"
        )
    return {post["slug"] for post in posts if sponsored_ids[0] in post["tag_ids"]}


def _enrich_with_publish_dates(data: List[dict], posts: List[dict]) -> List[dict]:
    """Add publish_date and earnings_per_day from the static site post corpus.

    A Raptive page that is not a post (the home page, an archive) has no corpus
    record and carries neither value.
    """
    published_by_slug = {post["slug"]: post["published"] for post in posts}
    for item in data:
        published = published_by_slug.get(_page_slug(item))
        item["publish_date"] = published.strftime("%Y-%m-%d") if published else None
        item["earnings_per_day"] = None
        if published:
            days_since_publish = (datetime.now(published.tzinfo) - published).days
            if days_since_publish > 0 and item.get("earnings"):
                item["earnings_per_day"] = round(item["earnings"] / days_since_publish, 4)
    return data


def _fetch_earnings_data(
    period: str,
    start: Optional[str],
    end: Optional[str],
    limit: int
) -> List[dict]:
    """Fetch earnings data from raptive CLI.

    Args:
        period: Time period (last7d, last30d, etc.)
        start: Custom start date (overrides period)
        end: Custom end date (overrides period)
        limit: Maximum results

    Returns:
        List of earnings data dicts
    """
    args = ["earnings", "by-page", "--limit", str(limit)]

    if start and end:
        args.extend(["--start", start, "--end", end])
    else:
        args.extend(["--period", period])

    result = _run_raptive(args)

    if result.returncode != 0:
        print_error(f"Failed to fetch earnings data: {result.stderr}")
        raise typer.Exit(1)

    try:
        parsed = json.loads(result.stdout)
        # raptive CLI may return {"cache_hit": ..., "results": [...]} or a plain list
        if isinstance(parsed, dict) and "results" in parsed:
            return parsed["results"]
        return parsed
    except json.JSONDecodeError:
        print_error("Invalid response from raptive CLI")
        raise typer.Exit(1)


def _filter_by_slugs(data: List[dict], slugs: List[str]) -> List[dict]:
    """Filter earnings data to only include matching slugs.

    Args:
        data: Earnings data list
        slugs: List of slugs to match (without leading /)

    Returns:
        Filtered list
    """
    wanted = set(slugs)
    return [item for item in data if _page_slug(item) in wanted]


def _select_properties(data: List[dict], properties: str) -> List[dict]:
    """Select specific properties from data.

    Args:
        data: List of dicts
        properties: Comma-separated list of property names

    Returns:
        List of dicts with only selected properties
    """
    prop_list = [p.strip() for p in properties.split(",")]
    return [
        {k: v for k, v in item.items() if k in prop_list}
        for item in data
    ]


@app.command("get")
@command
def get_earnings(
    slug: str = typer.Argument(..., help="Post slug to get earnings for"),
    period: str = typer.Option(
        "last30d", "--period",
        help="Time period: yesterday, last7d, last30d, mtd, lastmonth"
    ),
    start: Optional[str] = typer.Option(
        None, "--start", "-s", help="Start date (YYYY-MM-DD). Overrides --period."
    ),
    end: Optional[str] = typer.Option(
        None, "--end", "-e", help="End date (YYYY-MM-DD). Overrides --period."
    ),
    exclude_sponsored: bool = typer.Option(
        False, "--exclude-sponsored", help="Skip sponsored posts"
    ),
    table: bool = typer.Option(
        False, "--table", "-t", help="Display as table"
    ),
):
    """
    Get earnings for a specific post by slug.

    Examples:
        ata-blog earnings get my-post-slug
        ata-blog earnings get my-post-slug --table
        ata-blog earnings get my-post-slug --period last7d
        ata-blog earnings get my-post-slug --exclude-sponsored
    """
    posts = list_posts()
    if exclude_sponsored and slug in _sponsored_slugs(posts):
        print_info(f"Post {slug} is sponsored, skipping")
        print_json({})
        return

    # Fetch earnings data (fetch more to ensure we find the post)
    data = _fetch_earnings_data(period, start, end, limit=1000)

    # Filter to this specific post
    filtered = _filter_by_slugs(data, [slug])

    if not filtered:
        print_info(f"No earnings data found for post: {slug}")
        print_json({})
        return

    # Should be a single result - enrich with publish date
    enriched = _enrich_with_publish_dates(filtered, posts)
    result = enriched[0]
    earnings = create_post_earnings(result)
    output_data = earnings.model_dump()

    if table:
        rows = [{"field": k, "value": str(v)} for k, v in output_data.items() if v is not None]
        print_table(rows, columns=["field", "value"], headers=["Field", "Value"])
    else:
        print_json(output_data)


@app.command("list")
@command
def list_earnings(
    post_title: Optional[str] = typer.Option(
        None, "--post-title", help="Filter by post title (partial match)"
    ),
    period: str = typer.Option(
        "last30d", "--period",
        help="Time period: yesterday, last7d, last30d, mtd, lastmonth"
    ),
    start: Optional[str] = typer.Option(
        None, "--start", "-s", help="Start date (YYYY-MM-DD). Overrides --period."
    ),
    end: Optional[str] = typer.Option(
        None, "--end", "-e", help="End date (YYYY-MM-DD). Overrides --period."
    ),
    limit: int = typer.Option(
        100, "--limit", "-l", help="Maximum number of results"
    ),
    exclude_sponsored: bool = typer.Option(
        False, "--exclude-sponsored", help="Exclude posts tagged as Sponsored"
    ),
    filter_strs: Optional[List[str]] = typer.Option(
        None, "--filter", "-f",
        help="Filter results (field:op:value). E.g., earnings:gt:50, rpm:gt:20"
    ),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p",
        help="Comma-separated list of fields to include"
    ),
    table: bool = typer.Option(
        False, "--table", "-t", help="Display as table"
    ),
):
    """
    List post earnings from Raptive ad data.

    Query ad revenue, pageviews, RPM, and impressions for your posts.
    Supports filtering by post title or numeric thresholds.

    Examples:
        ata-blog earnings list --table
        ata-blog earnings list --post-title "PowerShell"
        ata-blog earnings list --filter "earnings:gt:50"
        ata-blog earnings list --filter "rpm:gt:20" --period last7d
        ata-blog earnings list --start 2025-01-01 --end 2025-12-31 --limit 50
        ata-blog earnings list --exclude-sponsored
    """
    # Validate filters
    if filter_strs:
        try:
            validate_filters(filter_strs)
        except Exception as e:
            print_error(f"Invalid filter: {e}")
            raise typer.Exit(1)

    posts = list_posts()

    # Determine slugs to filter by
    slugs_to_match: Optional[List[str]] = None

    if post_title:
        slugs_to_match = [
            post["slug"] for post in posts if post_title.casefold() in post["title"].casefold()
        ]
        if not slugs_to_match:
            print_error(f"No posts found matching title: {post_title}")
            raise typer.Exit(1)
        print_info(f"Found {len(slugs_to_match)} matching post(s)")

    # Fetch earnings data
    # If filtering by specific posts, fetch more to ensure we find them
    fetch_limit = limit * 10 if slugs_to_match else limit
    data = _fetch_earnings_data(period, start, end, fetch_limit)

    # Show timeframe info
    if start and end:
        print_info(f"Period: {start} to {end}")
    else:
        period_labels = {
            "yesterday": "Yesterday",
            "last7d": "Last 7 days",
            "last30d": "Last 30 days",
            "mtd": "Month to date",
            "lastmonth": "Last month",
        }
        print_info(f"Period: {period_labels.get(period, period)}")

    if not data:
        print_info("No earnings data found")
        print_json([])
        return

    # Filter by post slugs if specified
    if slugs_to_match:
        data = _filter_by_slugs(data, slugs_to_match)
        if not data:
            print_info("No earnings data found for specified post(s)")
            print_json([])
            return

    # Exclude sponsored posts
    if exclude_sponsored:
        sponsored = _sponsored_slugs(posts)
        before_count = len(data)
        data = [item for item in data if _page_slug(item) not in sponsored]
        excluded = before_count - len(data)
        if excluded:
            print_info(f"Excluded {excluded} sponsored post(s)")

    # Apply numeric/field filters
    if filter_strs:
        data = apply_filters(data, filter_strs)

    # Apply limit after filtering
    data = data[:limit]

    # Enrich with publish dates from the static site corpus
    data = _enrich_with_publish_dates(data, posts)

    # Convert to models
    earnings = [create_post_earnings(item) for item in data]

    # Convert back to dicts for output
    output_data = [e.model_dump() for e in earnings]

    # Select properties if specified
    if properties:
        output_data = _select_properties(output_data, properties)

    # Output
    if table:
        columns = ["page_url", "pageviews", "earnings", "rpm", "publish_date", "earnings_per_day"]
        headers = ["Page", "Views", "Earnings", "RPM", "Published", "$/Day"]
        if properties:
            columns = [p.strip() for p in properties.split(",")]
            headers = columns
        print_table(output_data, columns=columns, headers=headers)
    else:
        print_json(output_data)
