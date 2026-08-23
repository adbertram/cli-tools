"""Owned-channel discovery commands for the authenticated YouTube profile."""
COMMAND_CREDENTIALS = {
    "create": ["no_auth"],
    "list": ["custom"],
    "get": ["custom"],
    "update": ["custom"],
}

from pathlib import Path
from typing import List, Optional

import typer
from cli_tools_shared.filters import (
    FilterValidationError,
    apply_filters,
    apply_properties_filter,
    validate_filters,
)
from cli_tools_shared.output import handle_error, print_error, print_info, print_json, print_table
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from ..api_client import get_api_client
from ..banner_images import prepare_banner_image
from ..config import get_config


CHANNEL_COLUMNS = [
    "profile",
    "id",
    "title",
    "custom_url",
    "subscriber_count",
    "video_count",
]

app = typer.Typer(help="List channels available to the authenticated account", no_args_is_help=True)

CHANNEL_CREATION_HELP_URL = "https://support.google.com/youtube/answer/1646861"
CHANNEL_CREATION_ERROR = (
    "Creating YouTube channels is not supported by the YouTube Data API v3. "
    "Google's current channels API only supports list and update. "
    f"Create the channel in the YouTube web UI instead: {CHANNEL_CREATION_HELP_URL}"
)


def _property_fields(properties: Optional[str]) -> Optional[List[str]]:
    if properties is None:
        return None
    fields = [field.strip() for field in properties.split(",") if field.strip()]
    return fields or None


def _optional_int(value) -> Optional[int]:
    if value is None:
        return None
    return int(value)


def _normalize_channel(item: dict, profile: Optional[str] = None) -> dict:
    snippet = item["snippet"]
    statistics = item.get("statistics", {})
    content_details = item.get("contentDetails", {})
    related_playlists = content_details.get("relatedPlaylists", {})
    branding_settings = item.get("brandingSettings", {})
    branding_image = branding_settings.get("image", {})

    return {
        "profile": profile,
        "id": item["id"],
        "title": snippet["title"],
        "custom_url": snippet.get("customUrl"),
        "description": snippet.get("description"),
        "published_at": snippet.get("publishedAt"),
        "country": snippet.get("country"),
        "subscriber_count": _optional_int(statistics.get("subscriberCount")),
        "video_count": _optional_int(statistics.get("videoCount")),
        "view_count": _optional_int(statistics.get("viewCount")),
        "uploads_playlist_id": related_playlists.get("uploads"),
        "banner_external_url": branding_image.get("bannerExternalUrl"),
    }


def _list_owned_channels(profile: Optional[str], limit: Optional[int] = None) -> List[dict]:
    """List owned channels for a single profile's token (channels.list?mine=true)."""
    client = get_api_client(profile=profile)
    service = client.get_youtube_service()
    channels = []
    next_token = None

    while True:
        page_size = 50
        if limit is not None and limit > 0:
            page_size = min(page_size, limit - len(channels))
            if page_size <= 0:
                break

        response = service.channels().list(
            part="id,snippet,statistics,contentDetails,brandingSettings",
            mine=True,
            maxResults=page_size,
            pageToken=next_token,
        ).execute()
        channels.extend(_normalize_channel(item, profile=profile) for item in response.get("items", []))

        next_token = response.get("nextPageToken")
        if not next_token:
            break

    return channels


def _all_profile_names() -> List[str]:
    """Return every authenticated profile name managed by the YouTube CLI config."""
    config = get_config()
    return [config.profile_name_for_path(path) for path in config.list_profile_paths()]


def _aggregate_owned_channels(
    profile: Optional[str], limit: Optional[int] = None
) -> tuple[List[dict], List[dict]]:
    """Aggregate owned channels across profiles.

    Each YouTube OAuth token is bound to exactly one channel, so a single
    profile only ever returns its own channel. When ``profile`` is None this
    iterates every authenticated profile, merges and dedupes the results by
    channel id, and annotates each row with the profile it came from. When
    ``profile`` is provided, only that profile is queried (single-profile
    behavior preserved).

    Returns a tuple of (channels, errors). ``errors`` holds one
    ``{"profile", "error"}`` record per profile whose token failed so callers
    can report failures loudly instead of silently swallowing them.
    """
    profile_names = [profile] if profile else _all_profile_names()

    channels: List[dict] = []
    seen_ids = set()
    errors: List[dict] = []

    for name in profile_names:
        try:
            profile_channels = _list_owned_channels(name, limit=limit)
        except Exception as exc:  # noqa: BLE001 - report per-profile, never swallow
            errors.append({"profile": name, "error": str(exc)})
            continue

        for channel in profile_channels:
            channel_id = channel["id"]
            if channel_id in seen_ids:
                continue
            seen_ids.add(channel_id)
            channels.append(channel)

    # ``limit`` is a per-profile page cap inside ``_list_owned_channels``; apply
    # it again to the merged, deduped result so it caps the aggregated total.
    if limit is not None and limit > 0:
        channels = channels[:limit]

    return channels, errors


def _report_profile_errors(errors: List[dict]) -> None:
    """Print one stderr line per profile whose token failed during aggregation."""
    for failure in errors:
        print_error(f"Profile '{failure['profile']}' failed: {failure['error']}")


def _get_owned_channel_resource(service, channel_id: str) -> Optional[dict]:
    next_token = None

    while True:
        response = service.channels().list(
            part="id,snippet,statistics,contentDetails,brandingSettings",
            mine=True,
            maxResults=50,
            pageToken=next_token,
        ).execute()

        for item in response.get("items", []):
            if item["id"] == channel_id:
                return item

        next_token = response.get("nextPageToken")
        if not next_token:
            return None


def _render_rows(rows: List[dict], table: bool, properties: Optional[str], empty: str) -> None:
    fields = _property_fields(properties)
    if fields:
        rows = apply_properties_filter(rows, properties)

    if not table:
        print_json(rows)
        return

    if not rows:
        print_info(empty)
        return

    visible_columns = fields or CHANNEL_COLUMNS
    headers = [column.replace("_", " ").title() for column in visible_columns]
    print_table(rows, visible_columns, headers)


@app.command("create")
def create_channel():
    """Explain how to create a YouTube channel when the API does not support it."""
    print_error(CHANNEL_CREATION_ERROR)
    raise typer.Exit(1)


@app.command("list")
def list_channels(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of channels"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter results (field:op:value)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
    profile: Optional[str] = typer.Option(
        None,
        "--profile",
        help="Limit to a single profile's channel. Omit to aggregate every authenticated profile.",
    ),
):
    """List owned YouTube channels across every authenticated profile.

    Each OAuth token is bound to one channel, so aggregating across profiles is
    the only way to see every channel you manage. Pass --profile to restrict to
    one profile's channel.
    """
    try:
        validate_filters(filter or [])
        rows, errors = _aggregate_owned_channels(profile, limit=limit)
    except FilterValidationError as exc:
        print_error(str(exc))
        raise typer.Exit(1)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))

    _report_profile_errors(errors)

    if filter:
        rows = apply_filters(rows, filter)
    _render_rows(rows, table, properties, "No channels found.")

    if errors:
        raise typer.Exit(1)


@app.command("get")
def get_channel(
    channel_id: str = typer.Argument(..., help="YouTube channel ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Get one owned YouTube channel by channel ID (searches every profile)."""
    try:
        rows, errors = _aggregate_owned_channels(profile)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))

    _report_profile_errors(errors)

    for row in rows:
        if row["id"] == channel_id:
            if table:
                _render_rows([row], table, properties, "No channel found.")
                return
            if properties:
                print_json(apply_properties_filter([row], properties)[0])
                return
            print_json(row)
            return

    print_error(f"Channel not found: {channel_id}")
    raise typer.Exit(1)


@app.command("update")
def update_channel(
    channel_id: str = typer.Argument(..., help="YouTube channel ID"),
    banner_image: Path = typer.Option(
        ...,
        "--banner-image",
        help="Path to banner image file (PNG/JPEG, minimum 2048x1152)",
        exists=True,
        dir_okay=False,
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to include"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Update one owned YouTube channel."""
    try:
        prepared_banner = prepare_banner_image(banner_image)
        client = get_api_client(profile=profile)
        service = client.get_youtube_service()

        current = _get_owned_channel_resource(service, channel_id)
        if current is None:
            print_error(f"Channel not found: {channel_id}")
            raise typer.Exit(1)

        if prepared_banner.normalized:
            print_info(
                "Normalized banner image to "
                f"{prepared_banner.width}x{prepared_banner.height} at {prepared_banner.path}"
            )

        print_info(f"Uploading banner image: {prepared_banner.path}")
        upload_response = service.channelBanners().insert(
            media_body=MediaFileUpload(str(prepared_banner.path), mimetype=prepared_banner.mime_type)
        ).execute()
        banner_url = upload_response.get("url")
        if not banner_url:
            raise RuntimeError("YouTube did not return a banner URL for the uploaded image")

        branding_settings = current.get("brandingSettings", {})
        branding_image = branding_settings.setdefault("image", {})
        branding_image["bannerExternalUrl"] = banner_url

        updated = service.channels().update(
            part="brandingSettings",
            body={"id": channel_id, "brandingSettings": branding_settings},
        ).execute()
        current["brandingSettings"] = updated["brandingSettings"]
        row = _normalize_channel(current)

        if table:
            _render_rows([row], table, properties, "No channel found.")
            return

        if properties:
            print_json(apply_properties_filter([row], properties)[0])
            return

        print_json(row)

    except HttpError as exc:
        print_error(f"HTTP error: {exc}")
        raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
