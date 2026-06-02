"""Channel management commands for the authenticated user's YouTube channel.

These commands use the YouTube Data API v3 with OAuth (NOT yt-dlp). They
operate on the user's own channel (videos owned by the authenticated user).
"""
COMMAND_CREDENTIALS = {
    "delete": ["custom"],
    "get": ["custom"],
    "list": ["custom"],
    "update": ["custom"],
    "upload": ["custom"],
    "videos": ["custom"],
}

from pathlib import Path
from typing import List, Optional

import typer
from cli_tools_shared.filters import apply_filters, apply_properties_filter
from cli_tools_shared.output import (
    handle_error,
    print_error,
    print_info,
    print_json,
    print_success,
    print_table,
)
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from ..api_client import get_api_client
from ..models import (
    DeleteResult,
    PrivacyStatus,
    UpdateResult,
    UploadResult,
    Video,
    VideoDetail,
    VideoStatistics,
    VideoStatus,
)


app = typer.Typer(help="Manage the authenticated user's YouTube channel")
videos_app = typer.Typer(help="Manage videos on the authenticated user's channel")
app.add_typer(videos_app, name="videos")


def _get_uploads_playlist_id(service) -> str:
    """Return the authenticated user's uploads playlist ID."""
    response = service.channels().list(part="contentDetails", mine=True).execute()
    items = response.get("items", [])
    if not items:
        raise RuntimeError("No channel found for authenticated user")
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"]


def _video_from_playlist_item(item: dict) -> dict:
    """Convert a playlistItem resource into a flat dict suitable for Video model."""
    snippet = item.get("snippet", {})
    return {
        "id": snippet.get("resourceId", {}).get("videoId", ""),
        "title": snippet.get("title", ""),
        "description": snippet.get("description"),
        "published_at": snippet.get("publishedAt"),
        "channel_id": snippet.get("channelId"),
    }


def _video_detail_from_api(item: dict) -> VideoDetail:
    """Convert a videos.list API response item into a VideoDetail model."""
    snippet = item.get("snippet", {})
    stats_raw = item.get("statistics", {})
    status_raw = item.get("status", {})
    content_details = item.get("contentDetails", {})

    stats = VideoStatistics(
        view_count=int(stats_raw["viewCount"]) if "viewCount" in stats_raw else None,
        like_count=int(stats_raw["likeCount"]) if "likeCount" in stats_raw else None,
        comment_count=int(stats_raw["commentCount"]) if "commentCount" in stats_raw else None,
        favorite_count=int(stats_raw["favoriteCount"]) if "favoriteCount" in stats_raw else None,
    )

    status = VideoStatus(
        upload_status=status_raw.get("uploadStatus"),
        privacy_status=status_raw.get("privacyStatus"),
        license=status_raw.get("license"),
        embeddable=status_raw.get("embeddable"),
        public_stats_viewable=status_raw.get("publicStatsViewable"),
        made_for_kids=status_raw.get("madeForKids"),
        publish_at=status_raw.get("publishAt"),
    )

    thumbnails = snippet.get("thumbnails", {})
    thumb_url = None
    for size in ("maxres", "high", "medium", "default"):
        if size in thumbnails:
            thumb_url = thumbnails[size].get("url")
            break

    return VideoDetail(
        id=item.get("id", ""),
        title=snippet.get("title", ""),
        description=snippet.get("description"),
        published_at=snippet.get("publishedAt"),
        channel_id=snippet.get("channelId"),
        channel_title=snippet.get("channelTitle"),
        tags=snippet.get("tags"),
        category_id=snippet.get("categoryId"),
        duration=content_details.get("duration"),
        thumbnail_url=thumb_url,
        statistics=stats,
        status=status,
    )


@videos_app.command("list")
def videos_list(
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum number of videos to list"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter: field:op:value (e.g., title:contains:foo)"
    ),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include in output"
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """List videos on the authenticated user's channel (uploads playlist)."""
    try:
        client = get_api_client(profile=profile)
        service = client.get_youtube_service()

        uploads_id = _get_uploads_playlist_id(service)

        # Page through the uploads playlist and collect video IDs.
        video_ids: List[str] = []
        next_token: Optional[str] = None
        while len(video_ids) < limit:
            page_size = min(50, limit - len(video_ids))
            response = service.playlistItems().list(
                part="snippet",
                playlistId=uploads_id,
                maxResults=page_size,
                pageToken=next_token,
            ).execute()
            for pl_item in response.get("items", []):
                snippet = pl_item.get("snippet", {})
                video_id = snippet.get("resourceId", {}).get("videoId")
                if video_id:
                    video_ids.append(video_id)
            next_token = response.get("nextPageToken")
            if not next_token:
                break

        # Fetch full status (privacy_status) + statistics in batches of 50.
        video_models: List[Video] = []
        for batch_start in range(0, len(video_ids), 50):
            batch_ids = video_ids[batch_start : batch_start + 50]
            details = service.videos().list(
                part="snippet,status,statistics",
                id=",".join(batch_ids),
            ).execute()
            for item in details.get("items", []):
                detail = _video_detail_from_api(item)
                video_models.append(
                    Video(
                        id=detail.id,
                        title=detail.title,
                        description=detail.description,
                        published_at=detail.published_at,
                        privacy_status=detail.status.privacy_status if detail.status else None,
                        channel_id=detail.channel_id,
                    )
                )

        # Apply filters using shared helper (filters are on model dict-equivalents).
        if filter:
            dicts = [v.model_dump(mode="json") for v in video_models]
            filtered = apply_filters(dicts, filter)
            ids = {row["id"] for row in filtered}
            video_models = [v for v in video_models if v.id in ids]

        # Apply property filtering for output only (after filtering on full model).
        output_rows = [m.model_dump(mode="json") for m in video_models]
        property_fields = None
        if properties:
            output_rows = apply_properties_filter(output_rows, properties)
            property_fields = [field.strip() for field in properties.split(",") if field.strip()]

        if table:
            cols = (
                property_fields[:5]
                if property_fields
                else ["id", "title", "privacy_status", "published_at"]
            )
            headers = [c.replace("_", " ").title() for c in cols]
            print_table(output_rows, cols, headers)
        else:
            print_json(output_rows)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@videos_app.command("get")
def videos_get(
    video_id: str = typer.Argument(..., help="YouTube video ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Get full metadata for a single video by ID."""
    try:
        client = get_api_client(profile=profile)
        service = client.get_youtube_service()
        response = service.videos().list(
            part="snippet,status,statistics,contentDetails",
            id=video_id,
        ).execute()
        items = response.get("items", [])
        if not items:
            print_error(f"Video not found: {video_id}")
            raise typer.Exit(1)

        detail = _video_detail_from_api(items[0])

        if table:
            print_table(
                [detail],
                ["id", "title", "channel_title", "category_id", "duration"],
                ["ID", "Title", "Channel", "Category", "Duration"],
            )
        else:
            print_json(detail)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@videos_app.command("upload")
def videos_upload(
    file: Path = typer.Argument(..., help="Path to video file to upload", exists=True, dir_okay=False),
    title: str = typer.Option(..., "--title", help="Video title"),
    description: str = typer.Option("", "--description", help="Video description"),
    tags: Optional[List[str]] = typer.Option(
        None, "--tag", help="Video tag (repeatable). Pass --tag multiple times."
    ),
    category_id: str = typer.Option(
        "22", "--category-id", help="YouTube category ID (default 22 = People & Blogs)"
    ),
    privacy: PrivacyStatus = typer.Option(
        PrivacyStatus.PRIVATE, "--privacy", help="Privacy status: private, unlisted, or public"
    ),
    publish_at: Optional[str] = typer.Option(
        None,
        "--publish-at",
        help=(
            "Scheduled publish time in RFC 3339 (e.g., 2026-06-01T15:00:00Z). "
            "Requires --privacy private."
        ),
    ),
    made_for_kids: bool = typer.Option(
        False, "--made-for-kids/--not-made-for-kids", help="Mark video as made for kids"
    ),
    thumbnail: Optional[Path] = typer.Option(
        None,
        "--thumbnail",
        help="Path to thumbnail image (jpg/png) to set after upload",
        exists=True,
        dir_okay=False,
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Upload a video file to the authenticated user's channel."""
    if publish_at and privacy != PrivacyStatus.PRIVATE:
        print_error("--publish-at requires --privacy private (YouTube schedules private uploads)")
        raise typer.Exit(1)

    try:
        client = get_api_client(profile=profile)
        service = client.get_youtube_service()

        body = {
            "snippet": {
                "title": title,
                "description": description,
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy.value,
                "selfDeclaredMadeForKids": made_for_kids,
            },
        }
        if tags:
            body["snippet"]["tags"] = tags
        if publish_at:
            body["status"]["publishAt"] = publish_at

        media = MediaFileUpload(str(file), chunksize=-1, resumable=True)
        request = service.videos().insert(
            part="snippet,status", body=body, media_body=media
        )

        print_info(f"Uploading {file}...")
        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print_info(f"  uploaded {int(status.progress() * 100)}%")

        video_id = response["id"]

        thumbnail_uploaded = False
        if thumbnail:
            print_info(f"Uploading thumbnail {thumbnail}...")
            service.thumbnails().set(
                videoId=video_id, media_body=MediaFileUpload(str(thumbnail))
            ).execute()
            thumbnail_uploaded = True

        result = UploadResult(
            id=video_id,
            title=title,
            privacy_status=privacy,
            publish_at=publish_at,
            url=f"https://www.youtube.com/watch?v={video_id}",
            thumbnail_uploaded=thumbnail_uploaded,
        )
        print_success(f"Uploaded: {result.url}")
        print_json(result)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@videos_app.command("update")
def videos_update(
    video_id: str = typer.Argument(..., help="YouTube video ID"),
    title: Optional[str] = typer.Option(None, "--title", help="New video title"),
    description: Optional[str] = typer.Option(None, "--description", help="New description"),
    tags: Optional[List[str]] = typer.Option(
        None, "--tag", help="Replace tags with these values (repeatable)"
    ),
    category_id: Optional[str] = typer.Option(None, "--category-id", help="New category ID"),
    privacy: Optional[PrivacyStatus] = typer.Option(
        None, "--privacy", help="New privacy status"
    ),
    thumbnail: Optional[Path] = typer.Option(
        None,
        "--thumbnail",
        help="Path to new thumbnail image",
        exists=True,
        dir_okay=False,
    ),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Update title, description, tags, privacy, or thumbnail of an existing video."""
    if not any([title, description, tags is not None, category_id, privacy, thumbnail]):
        print_error("Provide at least one field to update")
        raise typer.Exit(1)

    try:
        client = get_api_client(profile=profile)
        service = client.get_youtube_service()

        # Fetch current snippet (required by API to keep mandatory fields).
        current = service.videos().list(part="snippet,status", id=video_id).execute()
        items = current.get("items", [])
        if not items:
            print_error(f"Video not found: {video_id}")
            raise typer.Exit(1)

        snippet = items[0]["snippet"]
        status = items[0]["status"]

        if title is not None:
            snippet["title"] = title
        if description is not None:
            snippet["description"] = description
        if tags is not None:
            snippet["tags"] = tags
        if category_id is not None:
            snippet["categoryId"] = category_id
        if privacy is not None:
            status["privacyStatus"] = privacy.value

        update_body = {"id": video_id, "snippet": snippet, "status": status}
        updated = service.videos().update(part="snippet,status", body=update_body).execute()

        thumbnail_updated = False
        if thumbnail:
            service.thumbnails().set(
                videoId=video_id, media_body=MediaFileUpload(str(thumbnail))
            ).execute()
            thumbnail_updated = True

        result = UpdateResult(
            id=video_id,
            title=updated["snippet"]["title"],
            privacy_status=updated["status"].get("privacyStatus"),
            thumbnail_updated=thumbnail_updated,
        )
        print_success(f"Updated video: {video_id}")
        print_json(result)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))


@videos_app.command("delete")
def videos_delete(
    video_id: str = typer.Argument(..., help="YouTube video ID"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Delete a video by ID. Requires confirmation unless --yes is passed."""
    try:
        if not yes:
            confirm = typer.confirm(
                f"Permanently delete video {video_id}? This cannot be undone."
            )
            if not confirm:
                print_info("Aborted.")
                raise typer.Exit(0)

        client = get_api_client(profile=profile)
        service = client.get_youtube_service()
        service.videos().delete(id=video_id).execute()

        result = DeleteResult(id=video_id, deleted=True)
        print_success(f"Deleted video: {video_id}")
        print_json(result)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        raise typer.Exit(handle_error(e))
