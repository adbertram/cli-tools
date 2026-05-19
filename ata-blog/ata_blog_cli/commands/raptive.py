"""Raptive ads management commands for ATA Blog CLI.

Manage Raptive (AdThrive) ad settings on WordPress posts via post meta fields.

Raptive plugin post meta keys:
- adthrive_ads_disable: Disable display/sidebar/footer ads
- adthrive_ads_disable_content_ads: Disable content/in-article ads
- adthrive_ads_disable_auto_insert_videos: Disable auto-insert video players
- adthrive_ads_re_enable_ads_on: Unix timestamp to auto re-enable ads
- adthrive_ads_disable_metadata: Disable video metadata

Value 'on' enables the setting (disables ads), empty/missing re-enables ads.

Note: The --all flag (default) sets ALL three disable flags to ensure complete ad removal.
"""
import subprocess
import typer
from typing import Optional
from datetime import datetime, timedelta

from cli_tools_shared.output import print_json, print_table, print_success, print_info, print_error

COMMAND_CREDENTIALS = {
    "disable": ["custom"],
    "enable": ["custom"],
    "status": ["custom"],
    "fields": ["custom"],
}

app = typer.Typer(help="Manage Raptive (AdThrive) ad settings on posts")


# Raptive post meta field names
RAPTIVE_META_FIELDS = {
    "all": "adthrive_ads_disable",
    "content": "adthrive_ads_disable_content_ads",
    "video": "adthrive_ads_disable_auto_insert_videos",
    "metadata": "adthrive_ads_disable_metadata",
    "re_enable": "adthrive_ads_re_enable_ads_on",
}


def _run_wordpress(args: list, capture: bool = True) -> subprocess.CompletedProcess:
    """Run wordpress CLI command."""
    cmd = ["wordpress"] + args
    if capture:
        return subprocess.run(cmd, capture_output=True, text=True)
    return subprocess.run(cmd)


def _update_post_meta(post_id: int, meta_updates: dict) -> bool:
    """Update post meta using wordpress CLI."""
    args = ["posts", "update", str(post_id)]
    for key, value in meta_updates.items():
        args.extend(["--meta", f"{key}={value}"])

    result = _run_wordpress(args)
    return result.returncode == 0


@app.command("disable")
def ads_disable(
    post_id: int = typer.Argument(..., help="WordPress post ID"),
    all_ads: bool = typer.Option(True, "--all/--no-all", help="Disable ALL ads (default)"),
    content_only: bool = typer.Option(False, "--content-only", "-c", help="Disable only content ads"),
    video_only: bool = typer.Option(False, "--video-only", "-v", help="Disable only video auto-insert"),
    re_enable_days: Optional[int] = typer.Option(None, "--re-enable-days", "-d", help="Auto re-enable after N days"),
    re_enable_date: Optional[str] = typer.Option(None, "--re-enable-date", help="Auto re-enable on date (YYYY-MM-DD)"),
):
    """
    Disable Raptive ads on a WordPress post.

    By default disables ALL ads. Use flags to disable specific ad types only.

    Examples:
        ata-blog raptive disable 12345                    # Disable all ads
        ata-blog raptive disable 12345 --content-only     # Disable content ads only
        ata-blog raptive disable 12345 --video-only       # Disable video players only
        ata-blog raptive disable 12345 --re-enable-days 30  # Re-enable after 30 days
        ata-blog raptive disable 12345 --re-enable-date 2026-02-01
    """
    meta_updates = {}

    # Determine which ad types to disable
    if content_only:
        meta_updates[RAPTIVE_META_FIELDS["content"]] = "on"
        ad_type = "content ads"
    elif video_only:
        meta_updates[RAPTIVE_META_FIELDS["video"]] = "on"
        ad_type = "video auto-insert"
    else:
        # Default: disable ALL ads (display, content, and video)
        meta_updates[RAPTIVE_META_FIELDS["all"]] = "on"
        meta_updates[RAPTIVE_META_FIELDS["content"]] = "on"
        meta_updates[RAPTIVE_META_FIELDS["video"]] = "on"
        ad_type = "all ads (display, content, and video)"

    # Handle re-enable scheduling
    re_enable_timestamp = None
    if re_enable_days:
        re_enable_dt = datetime.now() + timedelta(days=re_enable_days)
        re_enable_timestamp = int(re_enable_dt.timestamp())
    elif re_enable_date:
        try:
            re_enable_dt = datetime.strptime(re_enable_date, "%Y-%m-%d")
            re_enable_timestamp = int(re_enable_dt.timestamp())
        except ValueError:
            print_error(f"Invalid date format: {re_enable_date}. Use YYYY-MM-DD.")
            raise typer.Exit(1)

    if re_enable_timestamp:
        meta_updates[RAPTIVE_META_FIELDS["re_enable"]] = str(re_enable_timestamp)

    print_info(f"Disabling {ad_type} on post {post_id}...")

    if _update_post_meta(post_id, meta_updates):
        print_success(f"Disabled {ad_type} on post {post_id}")
        if re_enable_timestamp:
            re_enable_str = datetime.fromtimestamp(re_enable_timestamp).strftime("%Y-%m-%d")
            print_info(f"Ads will auto re-enable on: {re_enable_str}")
        print_json({
            "post_id": post_id,
            "action": "disable",
            "ad_type": ad_type,
            "meta_updated": meta_updates,
            "re_enable_date": datetime.fromtimestamp(re_enable_timestamp).isoformat() if re_enable_timestamp else None,
        })
    else:
        print_error(f"Failed to disable ads on post {post_id}")
        raise typer.Exit(1)


@app.command("enable")
def ads_enable(
    post_id: int = typer.Argument(..., help="WordPress post ID"),
    all_ads: bool = typer.Option(True, "--all/--no-all", help="Enable ALL ads (default)"),
    content_only: bool = typer.Option(False, "--content-only", "-c", help="Enable only content ads"),
    video_only: bool = typer.Option(False, "--video-only", "-v", help="Enable only video auto-insert"),
):
    """
    Re-enable Raptive ads on a WordPress post.

    Removes the disable flags from post meta to restore ads.

    Examples:
        ata-blog raptive enable 12345                  # Enable all ads
        ata-blog raptive enable 12345 --content-only  # Enable content ads only
        ata-blog raptive enable 12345 --video-only    # Enable video players only
    """
    # To "enable" ads, we set the meta fields to empty string (removes the 'on' value)
    meta_updates = {}

    if content_only:
        meta_updates[RAPTIVE_META_FIELDS["content"]] = ""
        ad_type = "content ads"
    elif video_only:
        meta_updates[RAPTIVE_META_FIELDS["video"]] = ""
        ad_type = "video auto-insert"
    else:
        # Default: enable all - clear all disable flags
        meta_updates[RAPTIVE_META_FIELDS["all"]] = ""
        meta_updates[RAPTIVE_META_FIELDS["content"]] = ""
        meta_updates[RAPTIVE_META_FIELDS["video"]] = ""
        meta_updates[RAPTIVE_META_FIELDS["re_enable"]] = ""
        ad_type = "all ads"

    print_info(f"Enabling {ad_type} on post {post_id}...")

    if _update_post_meta(post_id, meta_updates):
        print_success(f"Enabled {ad_type} on post {post_id}")
        print_json({
            "post_id": post_id,
            "action": "enable",
            "ad_type": ad_type,
            "meta_cleared": list(meta_updates.keys()),
        })
    else:
        print_error(f"Failed to enable ads on post {post_id}")
        raise typer.Exit(1)


@app.command("status")
def ads_status(
    post_id: int = typer.Argument(..., help="WordPress post ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Check Raptive ad status for a WordPress post.

    Shows which ad types are disabled and any scheduled re-enable date.

    Examples:
        ata-blog raptive status 12345
        ata-blog raptive status 12345 --table
    """
    import json

    # Get post details with meta
    result = _run_wordpress(["posts", "get", str(post_id)])

    if result.returncode != 0:
        print_error(f"Failed to get post {post_id}: {result.stderr}")
        raise typer.Exit(1)

    try:
        post = json.loads(result.stdout)
    except json.JSONDecodeError:
        print_error(f"Invalid response from wordpress CLI")
        raise typer.Exit(1)

    # Extract meta values (may be nested in 'meta' dict)
    meta = post.get("meta", {})

    status_info = {
        "post_id": post_id,
        "title": post.get("title", {}).get("rendered", post.get("title", "Unknown")) if isinstance(post.get("title"), dict) else post.get("title", "Unknown"),
        "all_ads_disabled": meta.get(RAPTIVE_META_FIELDS["all"]) == "on",
        "content_ads_disabled": meta.get(RAPTIVE_META_FIELDS["content"]) == "on",
        "video_disabled": meta.get(RAPTIVE_META_FIELDS["video"]) == "on",
        "metadata_disabled": meta.get(RAPTIVE_META_FIELDS["metadata"]) == "on",
        "re_enable_date": None,
    }

    # Parse re-enable timestamp
    re_enable_ts = meta.get(RAPTIVE_META_FIELDS["re_enable"])
    if re_enable_ts:
        try:
            ts = int(re_enable_ts)
            status_info["re_enable_date"] = datetime.fromtimestamp(ts).isoformat()
        except (ValueError, TypeError):
            pass

    # Determine overall status
    if status_info["all_ads_disabled"]:
        status_info["status"] = "ALL_ADS_DISABLED"
    elif status_info["content_ads_disabled"] or status_info["video_disabled"]:
        disabled_types = []
        if status_info["content_ads_disabled"]:
            disabled_types.append("content")
        if status_info["video_disabled"]:
            disabled_types.append("video")
        status_info["status"] = f"PARTIAL_DISABLED ({', '.join(disabled_types)})"
    else:
        status_info["status"] = "ADS_ENABLED"

    if table:
        rows = [
            {"setting": "Post ID", "value": str(status_info["post_id"])},
            {"setting": "Title", "value": status_info["title"][:50]},
            {"setting": "Status", "value": status_info["status"]},
            {"setting": "All Ads Disabled", "value": "Yes" if status_info["all_ads_disabled"] else "No"},
            {"setting": "Content Ads Disabled", "value": "Yes" if status_info["content_ads_disabled"] else "No"},
            {"setting": "Video Disabled", "value": "Yes" if status_info["video_disabled"] else "No"},
            {"setting": "Re-enable Date", "value": status_info["re_enable_date"] or "Not scheduled"},
        ]
        print_table(rows, ["setting", "value"], ["Setting", "Value"])
    else:
        print_json(status_info)


@app.command("fields")
def list_fields():
    """
    List all Raptive post meta field names.

    Useful for manual debugging or direct API calls.
    """
    fields = [
        {"field": key, "meta_key": value, "description": _get_field_description(key)}
        for key, value in RAPTIVE_META_FIELDS.items()
    ]
    print_table(fields, ["field", "meta_key", "description"], ["Field", "Meta Key", "Description"])


def _get_field_description(field: str) -> str:
    """Get human-readable description for a field."""
    descriptions = {
        "all": "Disable display/sidebar/footer ads",
        "content": "Disable in-content/article ads",
        "video": "Disable auto-insert video players",
        "metadata": "Disable video metadata",
        "re_enable": "Unix timestamp to auto re-enable ads",
    }
    return descriptions.get(field, "")
