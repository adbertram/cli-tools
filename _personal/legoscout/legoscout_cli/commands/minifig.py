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
