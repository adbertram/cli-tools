"""`legoscout images` -- persistent, space-bounded deal-photo storage."""
from __future__ import annotations

import json
from pathlib import Path

import typer
from cli_tools_shared.output import command, print_json

from ..paths import DEAL_IMAGE_ROOT
from ..pricing import deal_images

COMMAND_CREDENTIALS = ["no_auth"]

app = typer.Typer(
    help="Download, downscale, and expire persistent deal photos",
    no_args_is_help=True,
)


@app.command("download-batch")
@command
def download_batch(
    records: Path = typer.Option(
        ..., "--records",
        help="JSON array of {listing_key, image_urls} objects"),
    out: Path = typer.Option(
        ..., "--out", help="Write the result array here (and to stdout)"),
    image_root: Path = typer.Option(
        Path(DEAL_IMAGE_ROOT), "--image-root",
        help="Content-addressed deal-image store root"),
    max_images: int = typer.Option(
        deal_images.DEAL_IMAGE_MAX_PER_LISTING, "--max-images",
        help="Fetch at most this many photos per listing"),
    workers: int = typer.Option(
        4, "--workers", help="Concurrent listings downloaded at once"),
):
    """Download, downscale to WebP, and persist one batch's listing photos."""
    payload = json.loads(records.read_text(encoding="utf-8"))
    results = deal_images.download_batch(
        payload, str(image_root),
        max_images_per_listing=max_images, workers=workers)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    print_json(results)


@app.command("gc")
@command
def gc(
    older_than_days: int = typer.Option(
        deal_images.DEAL_IMAGE_RETENTION_DAYS, "--older-than-days",
        help="Delete images whose file is older than this many days"),
    apply: bool = typer.Option(
        False, "--apply", help="Actually delete; dry run by default"),
    image_root: Path = typer.Option(
        Path(DEAL_IMAGE_ROOT), "--image-root",
        help="Content-addressed deal-image store root"),
):
    """Report (and, with --apply, delete) expired deal images."""
    print_json(deal_images.gc(
        str(image_root), older_than_days=older_than_days, apply=apply))
