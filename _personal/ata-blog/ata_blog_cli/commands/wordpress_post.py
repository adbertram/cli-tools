"""WordPress commands for ATA Blog CLI (passthrough to wordpress CLI)."""
import json
import subprocess
import typer
from cli_tools_shared.output import command
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional
from cli_tools_shared.output import print_json, print_table, handle_error, print_error

from ._ads_helpers import (
    SCANNER_DEFAULTS,
    inject_link_into_properties,
    reject_table_with_include_ads,
    run_wp_capture,
    scan_and_merge,
)

COMMAND_CREDENTIALS = {
    "list": ["custom"],
    "get": ["custom"],
    "create": ["custom"],
    "update": ["custom"],
    "schedule": ["custom"],
    "delete": ["custom"],
    "stats": ["custom"],
    "bounce": ["custom"],
}

app = typer.Typer(help="Manage WordPress posts")


def _passthrough(resource: str, args: List[str]):
    """Pass command through to wordpress CLI with full output."""
    cmd = ["wordpress", resource] + args
    result = subprocess.run(cmd)
    raise typer.Exit(result.returncode)


SPONSORED_TAG_ID = "7"


def _extra_args(ctx: typer.Context) -> List[str]:
    """Return passthrough args without Typer's separator marker."""
    return [arg for arg in ctx.args if arg != "--"]


@app.command("list", context_settings={"allow_extra_args": True, "allow_interspersed_args": False})
@command
def posts_list(
    ctx: typer.Context,
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(None, "--limit", "-l", help="Maximum results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
    sponsored: bool = typer.Option(False, "--sponsored", help="Only show sponsored posts"),
    exclude_sponsored: bool = typer.Option(False, "--exclude-sponsored", help="Exclude sponsored posts"),
    include_ads: bool = typer.Option(
        False, "--include-ads", "-A",
        help="Live-scan each post URL for advertisers via Google Publisher Tag (adds 'ads' key per item). JSON only -- incompatible with --table."
    ),
    ad_checks: int = typer.Option(SCANNER_DEFAULTS["checks"], "--ad-checks", help="Reloads per scan"),
    ad_interval: int = typer.Option(SCANNER_DEFAULTS["interval"], "--ad-interval", help="Seconds between reloads"),
    ad_timeout: int = typer.Option(SCANNER_DEFAULTS["per_check_timeout"], "--ad-timeout", help="Max seconds per check"),
):
    """List WordPress posts."""
    reject_table_with_include_ads(table, include_ads)
    if sponsored and exclude_sponsored:
        raise typer.BadParameter("--sponsored and --exclude-sponsored are mutually exclusive")

    base_args = ["list"]
    if limit:
        base_args.extend(["--limit", str(limit)])
    if filter:
        for f in filter:
            base_args.extend(["--filter", f])
    if sponsored:
        base_args.extend(["--filter", f"tags:eq:{SPONSORED_TAG_ID}"])
    if exclude_sponsored:
        base_args.extend(["--filter", f"tags:ne:{SPONSORED_TAG_ID}"])
    if properties:
        base_args.extend(["--properties", properties])
    extras = _extra_args(ctx)

    if not include_ads:
        # Pure passthrough -- unchanged from pre-ads-scanner behavior.
        args = list(base_args)
        if table:
            args.append("--table")
        args.extend(extras)
        _passthrough("posts", args)
        return

    # Capture + scan + merge path. Force 'link' into --properties if provided.
    capture_args = ["posts"] + base_args + inject_link_into_properties(extras)
    posts = run_wp_capture(capture_args)
    merged = scan_and_merge(
        posts, ad_checks, ad_interval, ad_timeout, sponsored_warning=sponsored
    )
    # Use typer.echo (not print_json) so the output is captured by CliRunner.
    typer.echo(json.dumps(merged, indent=2, default=str))


@app.command("get", context_settings={"allow_extra_args": True, "allow_interspersed_args": False})
@command
def posts_get(
    ctx: typer.Context,
    post_id: int = typer.Argument(..., help="Post ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields"),
    raw: bool = typer.Option(False, "--raw", "-r", help="Return raw Gutenberg blocks instead of rendered HTML"),
    include_ads: bool = typer.Option(
        False, "--include-ads", "-A",
        help="Live-scan the post URL for advertisers via Google Publisher Tag (adds 'ads' key). JSON only -- incompatible with --table."
    ),
    ad_checks: int = typer.Option(SCANNER_DEFAULTS["checks"], "--ad-checks", help="Reloads per scan"),
    ad_interval: int = typer.Option(SCANNER_DEFAULTS["interval"], "--ad-interval", help="Seconds between reloads"),
    ad_timeout: int = typer.Option(SCANNER_DEFAULTS["per_check_timeout"], "--ad-timeout", help="Max seconds per check"),
):
    """Get post details."""
    reject_table_with_include_ads(table, include_ads)

    extras = _extra_args(ctx)

    if not include_ads:
        # Pure passthrough.
        args = ["get"]
        if table:
            args.append("--table")
        if properties:
            args.extend(["--properties", properties])
        if raw:
            args.append("--raw")
        args.extend(extras)
        args.append(str(post_id))
        _passthrough("posts", args)
        return

    # Capture + scan + merge.
    wp_args = ["posts", "get"] + inject_link_into_properties(extras) + [str(post_id)]
    post = run_wp_capture(wp_args)
    merged = scan_and_merge(post, ad_checks, ad_interval, ad_timeout)
    typer.echo(json.dumps(merged, indent=2, default=str))


@app.command("create", context_settings={"allow_extra_args": True, "allow_interspersed_args": False})
@command
def posts_create(
    ctx: typer.Context,
    title: Optional[str] = typer.Option(None, "--title", help="Post title"),
    content: Optional[str] = typer.Option(None, "--content", help="Post content"),
    status: str = typer.Option("draft", "--status", help="Post status (publish, draft, pending, private, future)"),
    slug: Optional[str] = typer.Option(None, "--slug", help="URL slug"),
    from_docx: Optional[str] = typer.Option(None, "--from-docx", help="Path to DOCX file to convert"),
    from_markdown: Optional[str] = typer.Option(None, "--from-markdown", help="Path to Markdown file to convert"),
    sponsored: bool = typer.Option(False, "--sponsored", help="Sponsored post (nofollow links, Sponsored tag, disable ads)"),
    date: Optional[str] = typer.Option(None, "--date", help="Schedule date (ISO 8601)"),
    categories: Optional[str] = typer.Option(None, "--categories", help="Category IDs (comma-separated)"),
    tags: Optional[str] = typer.Option(None, "--tags", help="Tag IDs (comma-separated)"),
    excerpt: Optional[str] = typer.Option(None, "--excerpt", help="Post excerpt"),
):
    """Create a post."""
    args = ["create"]
    if title:
        args.extend(["--title", title])
    if content:
        args.extend(["--content", content])
    args.extend(["--status", status])
    if slug:
        args.extend(["--slug", slug])
    if from_docx:
        args.extend(["--from-docx", from_docx])
    if from_markdown:
        args.extend(["--from-markdown", from_markdown])
    if sponsored:
        args.append("--sponsored")
    if date:
        args.extend(["--date", date])
    if categories:
        args.extend(["--categories", categories])
    if tags:
        args.extend(["--tags", tags])
    if excerpt:
        args.extend(["--excerpt", excerpt])
    args.extend(_extra_args(ctx))
    _passthrough("posts", args)


@app.command("update", context_settings={"allow_extra_args": True})
@command
def posts_update(
    ctx: typer.Context,
    post_id: int = typer.Argument(..., help="Post ID"),
    title: Optional[str] = typer.Option(None, "--title", help="New post title"),
    content: Optional[str] = typer.Option(None, "--content", help="New post content"),
    content_file: Optional[Path] = typer.Option(None, "--content-file", help="Read new post content from file"),
    status: Optional[str] = typer.Option(None, "--status", help="New post status (publish, draft, pending, private, future)"),
    slug: Optional[str] = typer.Option(None, "--slug", help="New URL slug"),
    date: Optional[str] = typer.Option(None, "--date", help="Schedule date (ISO 8601)"),
    featured_media: Optional[int] = typer.Option(None, "--featured-media", help="Featured image media ID"),
    excerpt: Optional[str] = typer.Option(None, "--excerpt", help="Post excerpt"),
    meta: Optional[List[str]] = typer.Option(None, "--meta", help="Post meta (key=value, repeatable)"),
):
    """Update a post."""
    args = ["update"]
    if title:
        args.extend(["--title", title])
    if content:
        args.extend(["--content", content])
    if content_file is not None:
        args.extend(["--content-file", str(content_file)])
    if status:
        args.extend(["--status", status])
    if slug:
        args.extend(["--slug", slug])
    if date:
        args.extend(["--date", date])
    if featured_media is not None:
        args.extend(["--featured-media", str(featured_media)])
    if excerpt:
        args.extend(["--excerpt", excerpt])
    if meta:
        for item in meta:
            args.extend(["--meta", item])
    args.extend(_extra_args(ctx))
    args.append(str(post_id))
    _passthrough("posts", args)


@app.command("schedule")
@command
def posts_schedule(
    post_id: int = typer.Argument(..., help="WordPress post ID to schedule"),
    date: Optional[str] = typer.Option(None, "--date", "-d", help="Schedule date (ISO 8601)"),
    auto_schedule: bool = typer.Option(False, "--auto-schedule", help="Auto-find next available slot"),
):
    """Schedule an existing WordPress draft post for publication."""
    if not date and not auto_schedule:
        typer.echo("Error: Provide --date or --auto-schedule", err=True)
        raise typer.Exit(1)
    args = ["update", "--status", "future"]
    if auto_schedule:
        args.append("--auto-schedule")
    elif date:
        args.extend(["--date", date])
    args.append(str(post_id))
    _passthrough("posts", args)


@app.command("delete", context_settings={"allow_extra_args": True, "allow_interspersed_args": False})
@command
def posts_delete(ctx: typer.Context, post_id: int = typer.Argument(...)):
    """Delete a post."""
    _passthrough("posts", ["delete"] + _extra_args(ctx) + [str(post_id)])


def _resolve_slug(identifier: str) -> str:
    """Resolve a post identifier (ID or slug) to a slug."""
    if not identifier.isdigit():
        return identifier
    result = subprocess.run(
        ["wordpress", "posts", "get", identifier, "-p", "slug"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print_error(f"Failed to resolve post ID {identifier}: {result.stderr.strip()}")
        raise typer.Exit(1)
    data = json.loads(result.stdout)
    slug = data.get("slug")
    if not slug:
        print_error(f"No slug found for post ID {identifier}")
        raise typer.Exit(1)
    return slug


GA4_PROPERTY_ID = "322716704"

STATS_METRICS = "screenPageViews,totalUsers,averageSessionDuration,bounceRate"


@app.command("stats")
@command
def posts_stats(
    identifier: str = typer.Argument(..., help="Post ID or slug"),
    start: Optional[str] = typer.Option(None, "--start", "-s", help="Start date (YYYY-MM-DD)"),
    end: Optional[str] = typer.Option(None, "--end", "-e", help="End date (YYYY-MM-DD)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get traffic stats for a post (pageviews, unique users, time spent, bounce rate).

    Examples:
        ata-blog wordpress-post stats 26786
        ata-blog wordpress-post stats my-post-slug --table
        ata-blog wordpress-post stats 26786 -s 2026-01-01 -e 2026-03-30
    """
    try:
        slug = _resolve_slug(identifier)

        if not start:
            start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        if not end:
            end = datetime.now().strftime("%Y-%m-%d")

        result = subprocess.run(
            [
                "google", "analytics", "report",
                "-m", STATS_METRICS,
                "-d", "pagePath",
                "-f", f"pagePath:contains:{slug}",
                "-s", start,
                "-e", end,
                "--property", GA4_PROPERTY_ID,
            ],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print_error(f"Google Analytics query failed: {result.stderr.strip()}")
            raise typer.Exit(1)

        rows = json.loads(result.stdout)
        if not rows:
            print_error(f"No analytics data found for '{slug}' ({start} to {end})")
            raise typer.Exit(1)

        # Aggregate across path variants (with/without trailing slash)
        total_pageviews = sum(int(r["screenPageViews"]) for r in rows)
        total_users = sum(int(r["totalUsers"]) for r in rows)
        # Weighted average for duration and bounce rate
        total_sessions_weight = sum(int(r["screenPageViews"]) for r in rows)
        avg_duration = sum(
            float(r["averageSessionDuration"]) * int(r["screenPageViews"]) for r in rows
        ) / total_sessions_weight
        avg_bounce = sum(
            float(r["bounceRate"]) * int(r["screenPageViews"]) for r in rows
        ) / total_sessions_weight

        stats = {
            "slug": slug,
            "period": f"{start} to {end}",
            "pageviews": total_pageviews,
            "unique_users": total_users,
            "avg_time_on_page": f"{avg_duration:.1f}s",
            "bounce_rate": f"{avg_bounce * 100:.1f}%",
        }

        if table:
            print_table(
                [stats],
                ["slug", "period", "pageviews", "unique_users", "avg_time_on_page", "bounce_rate"],
                ["Slug", "Period", "Page Views", "Unique Users", "Avg Time on Page", "Bounce Rate"],
            )
        else:
            print_json(stats)

    except subprocess.CalledProcessError as e:
        print_error(f"Command failed: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))
