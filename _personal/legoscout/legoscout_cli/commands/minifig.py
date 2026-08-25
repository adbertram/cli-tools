"""`legoscout minifig` -- durable minifigure detection and identification stages."""

from __future__ import annotations

from pathlib import Path

import typer
from cli_tools_shared.output import command, print_json

from ..paths import MINIFIG_CROP_ROOT
from ..pricing import minifig_identification

COMMAND_CREDENTIALS = ["no_auth"]

app = typer.Typer(
    help="Detect, identify, price, and evaluate listing minifigures",
    no_args_is_help=True,
)


@app.command("detect")
@command
def detect(
    input_path: Path = typer.Option(
        ..., "--input", help="Classifier minifigure hand-off JSON array"),
    output_path: Path = typer.Option(
        ..., "--output", help="Atomic minifig_detection artifact path"),
    detector: str = typer.Option(
        "grounding-dino-tiny", "--detector", help="Registered detector name"),
    crop_root: Path = typer.Option(
        Path(MINIFIG_CROP_ROOT), "--crop-root",
        help="Shared content-addressed crop root"),
):
    """Detect figures in already-saved listing photos; never fetch media."""
    summary = minifig_identification.detect_file(
        input_path,
        output_path,
        detector_name=detector,
        crop_root=crop_root,
    )
    print_json(summary)


@app.command("identify")
@command
def identify(
    input_path: Path = typer.Option(
        ..., "--input", help="minifig_detection artifact path"),
    output_path: Path = typer.Option(
        ..., "--output", help="Atomic minifig_identification artifact path"),
    workers: int = typer.Option(
        2, "--workers", help="Concurrent Brickognize requests; maximum 2"),
    top_k: int = typer.Option(
        10, "--top-k", help="Maximum Brickognize candidates; 1 through 50"),
    min_similarity: float = typer.Option(
        0.5, "--min-similarity",
        help="Candidates must score above this 0 through 1 threshold"),
):
    """Group cached Brickognize evidence; never claim verified identity."""
    result = minifig_identification.identify_file(
        input_path,
        output_path,
        crop_root=MINIFIG_CROP_ROOT,
        workers=workers,
        top_k=top_k,
        min_similarity=min_similarity,
    )
    print_json(result)


@app.command("price")
@command
def price(
    input_path: Path = typer.Option(
        ..., "--input", help="Agent-verified minifig_identification artifact"),
    output_path: Path = typer.Option(
        ..., "--output", help="Atomic plain per-listing identification results"),
    workers: int = typer.Option(
        4, "--workers", help="Concurrent BrickLink price lookups; 1 through 8"),
    refresh: bool = typer.Option(
        False, "--refresh",
        help="Bypass and do not write the shared BrickLink call cache"),
):
    """Validate agent evidence, finalize quantities, and price verified IDs."""
    summary = minifig_identification.price_file(
        input_path,
        output_path,
        workers=workers,
        refresh=refresh,
    )
    print_json(summary)
