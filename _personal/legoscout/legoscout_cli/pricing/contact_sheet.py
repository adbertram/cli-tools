"""Build labeled contact sheets for classifier image review."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def build_contact_sheet(
    image_paths: list[Path],
    output_path: Path,
    labels: list[str] | None = None,
    columns: int = 3,
    tile_size: tuple[int, int] = (480, 360),
) -> dict[str, object]:
    """Render every input into a fixed-size tile with a visible label."""
    if not image_paths:
        raise ValueError("at least one image is required")
    if columns < 1:
        raise ValueError("columns must be at least 1")
    if labels is not None and len(labels) != len(image_paths):
        raise ValueError("--label count must match image count")

    resolved_labels = labels or [path.name for path in image_paths]
    missing = [str(path) for path in image_paths if not path.is_file()]
    if missing:
        raise ValueError(f"image does not exist: {missing[0]}")

    width, image_height = tile_size
    label_height = 42
    tile_height = image_height + label_height
    rows = math.ceil(len(image_paths) / columns)
    sheet = Image.new("RGB", (columns * width, rows * tile_height), "white")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=20)

    for index, (path, label) in enumerate(zip(image_paths, resolved_labels)):
        x = (index % columns) * width
        y = (index // columns) * tile_height
        with Image.open(path) as source:
            image = source.convert("RGB")
            image.thumbnail((width, image_height), Image.Resampling.LANCZOS)
            image_x = x + (width - image.width) // 2
            image_y = y + (image_height - image.height) // 2
            sheet.paste(image, (image_x, image_y))
        draw.rectangle((x, y + image_height, x + width, y + tile_height), fill="white")
        draw.text((x + 8, y + image_height + 8), label, fill="black", font=font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(output_path)
    return {
        "output": str(output_path.resolve()),
        "image_count": len(image_paths),
        "columns": columns,
        "rows": rows,
        "width": sheet.width,
        "height": sheet.height,
        "labels": resolved_labels,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("images", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--label", action="append", dest="labels")
    parser.add_argument("--columns", type=int, default=3)
    args = parser.parse_args()
    try:
        result = build_contact_sheet(
            args.images, args.output, labels=args.labels, columns=args.columns)
    except (OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
