"""Banner image validation and normalization for YouTube channel uploads."""

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path

from cli_tools_shared.paths import resolve_cache_dir
from PIL import Image, ImageOps


MIN_BANNER_WIDTH = 2048
MIN_BANNER_HEIGHT = 1152
RECOMMENDED_BANNER_WIDTH = 2560
RECOMMENDED_BANNER_HEIGHT = 1440
MAX_BANNER_BYTES = 6 * 1024 * 1024
JPEG_QUALITIES = (90, 85, 80, 75, 70, 65, 60, 55, 50, 45, 40, 35, 30)
ALLOWED_IMAGE_FORMATS = {
    "JPEG": ("image/jpeg", ".jpg"),
    "PNG": ("image/png", ".png"),
}


@dataclass(frozen=True)
class PreparedBannerImage:
    """Upload-ready banner image metadata."""

    path: Path
    mime_type: str
    width: int
    height: int
    normalized: bool


def prepare_banner_image(image_path: Path) -> PreparedBannerImage:
    """Validate and normalize a banner image before upload."""
    with Image.open(image_path) as image:
        source_format = image.format
        if source_format not in ALLOWED_IMAGE_FORMATS:
            raise ValueError(
                "Banner image must be a PNG or JPEG file. "
                f"Received format: {source_format or 'unknown'}"
            )

        width, height = image.size
        if width < MIN_BANNER_WIDTH or height < MIN_BANNER_HEIGHT:
            raise ValueError(
                "Banner image is too small. "
                f"Received {width}x{height}; minimum is {MIN_BANNER_WIDTH}x{MIN_BANNER_HEIGHT}."
            )

        mime_type = ALLOWED_IMAGE_FORMATS[source_format][0]
        file_size = image_path.stat().st_size
        if (
            width == RECOMMENDED_BANNER_WIDTH
            and height == RECOMMENDED_BANNER_HEIGHT
            and file_size <= MAX_BANNER_BYTES
        ):
            return PreparedBannerImage(
                path=image_path,
                mime_type=mime_type,
                width=width,
                height=height,
                normalized=False,
            )

        prepared = _normalize_banner_image(image)

    prepared_path = _prepared_banner_path(image_path)
    _write_prepared_banner(prepared, prepared_path)
    return PreparedBannerImage(
        path=prepared_path,
        mime_type="image/jpeg",
        width=RECOMMENDED_BANNER_WIDTH,
        height=RECOMMENDED_BANNER_HEIGHT,
        normalized=True,
    )


def _normalize_banner_image(image: Image.Image) -> Image.Image:
    oriented = ImageOps.exif_transpose(image)
    fitted = ImageOps.fit(
        oriented,
        (RECOMMENDED_BANNER_WIDTH, RECOMMENDED_BANNER_HEIGHT),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )
    if "A" in fitted.getbands():
        rgba_image = fitted.convert("RGBA")
        background = Image.new("RGB", rgba_image.size, "white")
        background.paste(rgba_image, mask=rgba_image.getchannel("A"))
        return background
    return fitted.convert("RGB")


def _prepared_banner_path(image_path: Path) -> Path:
    cache_dir = resolve_cache_dir("youtube-cli") / "channel-banners"
    cache_dir.mkdir(parents=True, exist_ok=True)
    content_hash = sha256(image_path.read_bytes()).hexdigest()[:16]
    return cache_dir / f"{image_path.stem}-{content_hash}-2560x1440.jpg"


def _write_prepared_banner(image: Image.Image, destination: Path) -> None:
    for quality in JPEG_QUALITIES:
        buffer = BytesIO()
        image.save(buffer, format="JPEG", optimize=True, quality=quality)
        if buffer.tell() <= MAX_BANNER_BYTES:
            destination.write_bytes(buffer.getvalue())
            return

    raise ValueError(
        "Banner image could not be reduced below YouTube's 6 MB upload limit "
        "after normalization to 2560x1440 JPEG."
    )
