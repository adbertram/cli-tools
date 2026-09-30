"""Analytics commands for the authenticated user's YouTube channel.

These commands use the YouTube Analytics API v2 with OAuth (the
``yt-analytics.readonly`` scope) to report views, watch time, and engagement
for videos on the user's own channel. The YouTube Analytics API must be
enabled in the same Google Cloud project as the OAuth client.
"""
COMMAND_CREDENTIALS = {
    "report": ["custom"],
}

import re
from datetime import date, timedelta
from typing import List, Optional

import typer
from cli_tools_shared.filters import apply_filters, apply_properties_filter
from cli_tools_shared.output import (
    command,
    handle_error,
    print_error,
    print_info,
    print_json,
    print_table,
)
from googleapiclient.errors import HttpError

from ..api_client import get_api_client
from .channel import _get_uploads_playlist_id

app = typer.Typer(help="YouTube Analytics reports for the authenticated user's channel")

DEFAULT_METRICS = (
    "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,"
    "subscribersGained,likes,comments,shares"
)
DEFAULT_DAYS = 28
# Keep each analytics query's video filter under the API's safe limits.
_MAX_FILTER_IDS = 100
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_VIDEO_URL_RES = [
    re.compile(r"[?&]v=([A-Za-z0-9_-]{11})"),
    re.compile(r"youtu\.be/([A-Za-z0-9_-]{11})"),
    re.compile(r"/(?:shorts|embed|live|v)/([A-Za-z0-9_-]{11})"),
]


def _extract_video_id(value: str) -> str:
    """Accept a bare video ID or a YouTube URL; return the video ID."""
    value = value.strip()
    if _VIDEO_ID_RE.match(value):
        return value
    for pattern in _VIDEO_URL_RES:
        match = pattern.search(value)
        if match:
            return match.group(1)
    raise ValueError(f"Not a YouTube video ID or URL: {value}")


def _parse_date(value: str, label: str) -> date:
    """Parse a YYYY-MM-DD date or fail with a helpful message."""
    try:
        parts = value.split("-")
        if len(parts) != 3:
            raise ValueError
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        raise ValueError(f"--{label} must be YYYY-MM-DD, got: {value}")


def _collect_upload_video_ids(service, limit: int) -> List[str]:
    """Page the authenticated channel's uploads playlist for video IDs."""
    uploads_id = _get_uploads_playlist_id(service)
    video_ids: List[str] = []
    next_token = None
    while True:
        page_size = 50
        if limit > 0:
            page_size = min(50, limit - len(video_ids))
        response = (
            service.playlistItems()
            .list(
                part="snippet",
                playlistId=uploads_id,
                maxResults=page_size,
                pageToken=next_token,
            )
            .execute()
        )
        for pl_item in response.get("items", []):
            video_id = pl_item.get("snippet", {}).get("resourceId", {}).get("videoId")
            if video_id:
                video_ids.append(video_id)
        next_token = response.get("nextPageToken")
        if not next_token or (limit > 0 and len(video_ids) >= limit):
            break
    return video_ids


def _video_titles(service, video_ids: List[str]) -> dict:
    """Map video IDs to titles via the Data API (batched)."""
    titles = {}
    for start in range(0, len(video_ids), 50):
        batch = video_ids[start : start + 50]
        response = service.videos().list(part="snippet", id=",".join(batch)).execute()
        for item in response.get("items", []):
            titles[item["id"]] = item.get("snippet", {}).get("title", "")
    return titles


def _rows_to_dicts(response: dict) -> List[dict]:
    """Convert an Analytics API response to a list of named dicts."""
    headers = response.get("columnHeaders", [])
    rows = []
    for row in response.get("rows", []):
        record = {}
        for header, value in zip(headers, row):
            name = header.get("name")
            if header.get("dataType") in ("INTEGER", "DOUBLE") and isinstance(
                value, (int, float)
            ):
                record[name] = value
            else:
                record[name] = value
        rows.append(record)
    return rows


def _numeric_fields(response: dict) -> set:
    """Header names whose dataType is numeric."""
    return {
        h["name"]
        for h in response.get("columnHeaders", [])
        if h.get("dataType") in ("INTEGER", "DOUBLE")
    }


def _apply_sort(rows: List[dict], sort: str, numeric_fields: set) -> List[dict]:
    """Sort rows by an Analytics-style sort spec (e.g. -views,day)."""
    for spec in reversed([s.strip() for s in sort.split(",") if s.strip()]):
        descending = spec.startswith("-")
        field = spec[1:] if descending else spec
        rows.sort(
            key=lambda r: (
                (r.get(field) is None),
                r.get(field) if field in numeric_fields else str(r.get(field)),
            ),
            reverse=descending,
        )
    return rows


def _is_access_not_configured(error: HttpError) -> bool:
    """True when the Analytics API is not enabled in the Cloud project."""
    content = getattr(error, "content", b"") or b""
    try:
        text = content.decode("utf-8", "ignore")
    except Exception:
        return False
    return getattr(error, "resp", None) is not None and getattr(
        error.resp, "status", None
    ) == 403 and "accessNotConfigured" in text


@app.command("report")
@command
def analytics_report(
    video: Optional[List[str]] = typer.Option(
        None,
        "--video",
        "-v",
        help="Restrict to video ID(s) or URL(s); repeat or comma-separate. "
        "Default: all uploads on the authenticated channel.",
    ),
    channel: bool = typer.Option(
        False,
        "--channel",
        help="Channel-level totals (by day) instead of per-video rows.",
    ),
    start_date: Optional[str] = typer.Option(
        None, "--start-date", help="Start date YYYY-MM-DD (default: 28 days ago)"
    ),
    end_date: Optional[str] = typer.Option(
        None, "--end-date", help="End date YYYY-MM-DD (default: today)"
    ),
    metrics: str = typer.Option(
        DEFAULT_METRICS,
        "--metrics",
        "-m",
        help="Comma-separated Analytics API metrics",
    ),
    dimensions: Optional[str] = typer.Option(
        None,
        "--dimensions",
        "-d",
        help="Comma-separated Analytics API dimensions "
        "(default: video, or day with --channel)",
    ),
    sort: Optional[str] = typer.Option(
        None,
        "--sort",
        help="Sort spec, e.g. -views (default: -views)",
    ),
    max_results: int = typer.Option(
        200, "--max-results", help="Max rows per API query (1-200)"
    ),
    limit: int = typer.Option(
        0,
        "--limit",
        "-l",
        help="Max uploaded videos to scan (0 = all; ignored with --video/--channel)",
    ),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter: field:op:value (e.g., views:gt:1000)"
    ),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include in output"
    ),
    table: bool = typer.Option(
        False, "--table", "-t", help="Display results as a table"
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Report YouTube Analytics for videos on the authenticated user's channel."""
    try:
        end = _parse_date(end_date, "end-date") if end_date else date.today()
        start = (
            _parse_date(start_date, "start-date")
            if start_date
            else end - timedelta(days=DEFAULT_DAYS)
        )
        if start > end:
            print_error("--start-date must be on or before --end-date")
            raise typer.Exit(1)
        if not 1 <= max_results <= 200:
            print_error("--max-results must be between 1 and 200")
            raise typer.Exit(1)

        dims = dimensions or ("day" if channel else "video")
        sort_spec = sort or "-views"

        client = get_api_client(profile=profile)
        data_service = client.get_youtube_service()
        analytics = client.get_analytics_service()

        video_ids: List[str] = []
        if not channel:
            if video:
                seen = set()
                for raw in video:
                    for piece in raw.split(","):
                        piece = piece.strip()
                        if not piece:
                            continue
                        try:
                            vid = _extract_video_id(piece)
                        except ValueError as e:
                            print_error(str(e))
                            raise typer.Exit(1)
                        if vid not in seen:
                            seen.add(vid)
                            video_ids.append(vid)
            else:
                print_info("Scanning uploads playlist for video IDs...")
                video_ids = _collect_upload_video_ids(data_service, limit)
            if not video_ids:
                print_error("No videos found to report on")
                raise typer.Exit(1)
            print_info(
                f"Querying analytics for {len(video_ids)} video(s), "
                f"{start} to {end}..."
            )

        query_kwargs = dict(
            ids="channel==MINE",
            startDate=start.isoformat(),
            endDate=end.isoformat(),
            metrics=metrics,
            dimensions=dims,
            sort=sort_spec,
            maxResults=max_results,
        )

        all_rows: List[dict] = []
        numeric: set = set()
        if channel:
            response = analytics.reports().query(**query_kwargs).execute()
            numeric = _numeric_fields(response)
            all_rows = _rows_to_dicts(response)
        else:
            # Filter by video in chunks; merge rows and re-sort afterwards.
            first = True
            for chunk_start in range(0, len(video_ids), _MAX_FILTER_IDS):
                chunk = video_ids[chunk_start : chunk_start + _MAX_FILTER_IDS]
                response = (
                    analytics.reports()
                    .query(
                        **query_kwargs,
                        filters="video==" + ",".join(chunk),
                    )
                    .execute()
                )
                if first:
                    numeric = _numeric_fields(response)
                    first = False
                all_rows.extend(_rows_to_dicts(response))
            all_rows = _apply_sort(all_rows, sort_spec, numeric)

            if "video" in [d.strip() for d in dims.split(",")]:
                titles = _video_titles(data_service, video_ids)
                for row in all_rows:
                    row["title"] = titles.get(row.get("video"), "")

        print_info(f"Got {len(all_rows)} row(s)")

        if filter:
            all_rows = apply_filters(all_rows, filter)

        output_rows = all_rows
        property_fields = None
        if properties:
            property_fields = [f.strip() for f in properties.split(",") if f.strip()]
            output_rows = apply_properties_filter(output_rows, properties)

        if table:
            if not output_rows:
                print_info("No rows returned")
            else:
                cols = property_fields if property_fields else list(output_rows[0].keys())
                headers = [c.replace("_", " ").title() for c in cols]
                display = []
                for row in output_rows:
                    entry = {}
                    for col in cols:
                        value = row.get(col, "")
                        if col == "title" and isinstance(value, str) and len(value) > 50:
                            value = value[:47] + "..."
                        entry[col] = value
                    display.append(entry)
                print_table(display, cols, headers)
        else:
            print_json(output_rows)

    except HttpError as e:
        if _is_access_not_configured(e):
            print_error(
                "The YouTube Analytics API is not enabled in your Google Cloud "
                "project. Enable it (same project as your OAuth client), then "
                "retry:\n"
                "  https://console.cloud.google.com/apis/library/"
                "youtubeanalytics.googleapis.com"
            )
            raise typer.Exit(1)
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))
