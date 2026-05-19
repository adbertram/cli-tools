"""Earnings commands for ATA Blog CLI.

Query Raptive ad revenue and performance data for posts.
Wraps the raptive CLI earnings by-page functionality with
post-friendly filtering options.
"""
import json
import subprocess
from datetime import datetime
from typing import Dict, List, Optional

import typer

from ..filters import apply_filters, validate_filters
from ..models import PostEarnings, create_post_earnings
from cli_tools_shared.output import print_error, print_info, print_json, print_table

COMMAND_CREDENTIALS = {
    "get": ["custom"],
    "list": ["custom"],
}

app = typer.Typer(help="Query ad earnings and revenue data", no_args_is_help=True)

SPONSORED_TAG_ID = 7


def _run_raptive(args: list) -> subprocess.CompletedProcess:
    """Run raptive CLI command."""
    cmd = ["raptive"] + args
    return subprocess.run(cmd, capture_output=True, text=True)


def _run_wordpress(args: list) -> subprocess.CompletedProcess:
    """Run wordpress CLI command."""
    cmd = ["wordpress"] + args
    return subprocess.run(cmd, capture_output=True, text=True)


def _is_post_sponsored(post_id: int) -> bool:
    """Check if a post has the Sponsored tag.

    Args:
        post_id: WordPress post ID

    Returns:
        True if post has the Sponsored tag
    """
    result = _run_wordpress(["posts", "get", str(post_id)])
    if result.returncode != 0:
        return False

    try:
        post = json.loads(result.stdout)
        tags = post.get("tags", [])
        return SPONSORED_TAG_ID in tags
    except json.JSONDecodeError:
        return False


def _get_non_sponsored_slugs(slugs: List[str]) -> List[str]:
    """Filter out slugs that belong to sponsored posts.

    Args:
        slugs: List of post slugs to check

    Returns:
        List of slugs that are NOT sponsored
    """
    if not slugs:
        return []

    # Fetch all posts, check which ones have the Sponsored tag
    result = _run_wordpress(["posts", "list", "--filter", f"tags:notcontains:{SPONSORED_TAG_ID}", "--limit", "1000"])
    if result.returncode != 0:
        return slugs  # On failure, return unfiltered

    try:
        posts = json.loads(result.stdout)
        non_sponsored_slugs = {p.get("slug") for p in posts if p.get("slug")}
        return [s for s in slugs if s in non_sponsored_slugs]
    except json.JSONDecodeError:
        return slugs


def _get_post_slug_by_id(post_id: int) -> Optional[str]:
    """Look up WordPress post slug by ID.

    Args:
        post_id: WordPress post ID

    Returns:
        Post slug or None if not found
    """
    result = _run_wordpress(["posts", "get", str(post_id)])
    if result.returncode != 0:
        return None

    try:
        post = json.loads(result.stdout)
        return post.get("slug")
    except json.JSONDecodeError:
        return None


def _get_post_slugs_by_title(title: str) -> List[str]:
    """Look up WordPress post slugs by title search.

    Args:
        title: Title search term (partial match)

    Returns:
        List of matching post slugs
    """
    result = _run_wordpress([
        "posts", "list",
        "--filter", f"title:ilike:%{title}%",
        "--limit", "100"
    ])
    if result.returncode != 0:
        return []

    try:
        posts = json.loads(result.stdout)
        return [p.get("slug") for p in posts if p.get("slug")]
    except json.JSONDecodeError:
        return []


def _get_posts_by_slugs(slugs: List[str]) -> Dict[str, dict]:
    """Fetch WordPress posts and return a dict keyed by slug.

    Args:
        slugs: List of post slugs to look up (without leading /)

    Returns:
        Dict mapping slug -> post data
    """
    if not slugs:
        return {}

    # Fetch posts with high limit (WordPress slug filter isn't server-side)
    # Then filter client-side to match the slugs we need
    result = _run_wordpress([
        "posts", "list",
        "--limit", "1000"  # Fetch enough posts to find matches
    ])

    if result.returncode != 0:
        return {}

    try:
        posts = json.loads(result.stdout)
        # Filter to only the slugs we care about
        slug_set = set(slugs)
        return {
            p.get("slug"): p
            for p in posts
            if p.get("slug") in slug_set
        }
    except json.JSONDecodeError:
        return {}


def _enrich_with_publish_dates(data: List[dict]) -> List[dict]:
    """Enrich earnings data with publish dates and earnings_per_day.

    Args:
        data: List of earnings data dicts

    Returns:
        Enriched data with publish_date and earnings_per_day fields
    """
    # Extract slugs from page_urls (remove leading /)
    slugs = [(item.get("page_url") or "").lstrip("/") for item in data]
    slugs = [s for s in slugs if s]  # Filter out empty slugs

    # Fetch posts from WordPress
    posts_by_slug = _get_posts_by_slugs(slugs)

    # Enrich each earnings record
    for item in data:
        slug = (item.get("page_url") or "").lstrip("/")
        post = posts_by_slug.get(slug, {})

        # Get publish date from WordPress post
        publish_date = post.get("date")  # WordPress returns ISO format
        if publish_date:
            # Parse and format as date only
            try:
                dt = datetime.fromisoformat(publish_date.replace("Z", "+00:00"))
                item["publish_date"] = dt.strftime("%Y-%m-%d")

                # Calculate earnings_per_day
                days_since_publish = (datetime.now(dt.tzinfo) - dt).days
                if days_since_publish > 0 and item.get("earnings"):
                    item["earnings_per_day"] = round(
                        item["earnings"] / days_since_publish, 4
                    )
            except (ValueError, TypeError):
                item["publish_date"] = None
                item["earnings_per_day"] = None
        else:
            item["publish_date"] = None
            item["earnings_per_day"] = None

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
    # Normalize slugs to URL path format
    url_patterns = [f"/{slug}" for slug in slugs]

    return [
        item for item in data
        if item.get("page_url") in url_patterns
    ]


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
def get_earnings(
    identifier: str = typer.Argument(..., help="Post ID or slug to get earnings for"),
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
    Get earnings for a specific post by ID or slug.

    Examples:
        ata-blog earnings get 26786
        ata-blog earnings get my-post-slug --table
        ata-blog earnings get 26786 --period last7d
        ata-blog earnings get 26786 --exclude-sponsored
    """
    # Check if post is sponsored (when using post ID)
    if exclude_sponsored and identifier.isdigit():
        if _is_post_sponsored(int(identifier)):
            print_info(f"Post {identifier} is sponsored, skipping")
            print_json({})
            return

    # Determine slug from identifier
    slug = None
    if identifier.isdigit():
        # It's a post ID
        slug = _get_post_slug_by_id(int(identifier))
        if not slug:
            print_error(f"Post ID {identifier} not found")
            raise typer.Exit(1)
    else:
        # Assume it's a slug
        slug = identifier

    # Fetch earnings data (fetch more to ensure we find the post)
    data = _fetch_earnings_data(period, start, end, limit=1000)

    # Filter to this specific post
    filtered = _filter_by_slugs(data, [slug])

    if not filtered:
        print_info(f"No earnings data found for post: {slug}")
        print_json({})
        return

    # Should be a single result - enrich with publish date
    enriched = _enrich_with_publish_dates(filtered)
    result = enriched[0]
    earnings = create_post_earnings(result)
    output_data = earnings.model_dump()

    if table:
        rows = [{"field": k, "value": str(v)} for k, v in output_data.items() if v is not None]
        print_table(rows, columns=["field", "value"], headers=["Field", "Value"])
    else:
        print_json(output_data)


@app.command("list")
def list_earnings(
    post_id: Optional[int] = typer.Option(
        None, "--post-id", help="Filter by WordPress post ID"
    ),
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
    Supports filtering by post ID, title, or numeric thresholds.

    Examples:
        ata-blog earnings list --table
        ata-blog earnings list --post-id 26786
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

    # Determine slugs to filter by
    slugs_to_match: Optional[List[str]] = None

    if post_id:
        slug = _get_post_slug_by_id(post_id)
        if not slug:
            print_error(f"Post ID {post_id} not found")
            raise typer.Exit(1)
        slugs_to_match = [slug]
        print_info(f"Filtering by post: {slug}")

    if post_title:
        slugs = _get_post_slugs_by_title(post_title)
        if not slugs:
            print_error(f"No posts found matching title: {post_title}")
            raise typer.Exit(1)
        # If post_id was also provided, intersect the results
        if slugs_to_match:
            slugs_to_match = [s for s in slugs_to_match if s in slugs]
        else:
            slugs_to_match = slugs
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
        slugs_in_data = [(item.get("page_url") or "").lstrip("/") for item in data]
        non_sponsored = _get_non_sponsored_slugs(slugs_in_data)
        non_sponsored_urls = {f"/{s}" for s in non_sponsored}
        before_count = len(data)
        data = [item for item in data if item.get("page_url") in non_sponsored_urls]
        excluded = before_count - len(data)
        if excluded:
            print_info(f"Excluded {excluded} sponsored post(s)")

    # Apply numeric/field filters
    if filter_strs:
        data = apply_filters(data, filter_strs)

    # Apply limit after filtering
    data = data[:limit]

    # Enrich with publish dates from WordPress
    data = _enrich_with_publish_dates(data)

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
