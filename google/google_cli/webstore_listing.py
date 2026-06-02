"""Chrome Web Store listing metadata parsing and validation."""
from pathlib import Path
import re
from urllib.parse import urlparse

from PIL import Image, ImageOps

from .client import ClientError
from .models.webstore import WebStoreListingData, WebStoreListingAsset


TEXT_FIELDS = {
    "title": "Title",
    "summary": "Summary",
    "description": "Detailed description",
    "category": "Suggested category",
    "language": "Language",
    "homepage_url": "Homepage URL",
    "support_url": "Support URL",
    "privacy_policy_url": "Privacy policy URL",
}

SCREENSHOT_DIRECTORY_PATTERN = re.compile(r"^- Screenshots: `(?P<path>[^`]+)`$", re.MULTILINE)
ASSET_PATTERNS = {
    "small_promo_tile": re.compile(r"^- Small promo tile: `(?P<path>[^`]+)`$", re.MULTILINE),
    "marquee_promo_image": re.compile(r"^- Marquee promo image: `(?P<path>[^`]+)`$", re.MULTILINE),
}

PNG_DIMENSIONS = {
    "screenshot": (1280, 800),
    "small_promo_tile": (440, 280),
    "marquee_promo_image": (1400, 560),
}
CONVERTED_SCREENSHOT_DIRECTORY = ".converted"


def parse_listing_file(listing_file: Path) -> WebStoreListingData:
    """Parse the repository Chrome Web Store listing markdown."""
    if not listing_file.is_file():
        raise ClientError(f"Listing file does not exist: {listing_file}")
    listing_file = listing_file.resolve()

    text = listing_file.read_text()
    values = {
        field_name: _extract_fenced_value(text, label)
        for field_name, label in TEXT_FIELDS.items()
    }
    for field_name in ("homepage_url", "support_url", "privacy_policy_url"):
        _validate_https_url(values[field_name], field_name)

    screenshot_assets = _extract_screenshots(text, listing_file.parent.parent)
    small_promo_tile = _extract_single_asset(text, "small_promo_tile", listing_file.parent.parent)
    marquee_promo_image = _extract_single_asset(text, "marquee_promo_image", listing_file.parent.parent)

    return WebStoreListingData(
        screenshots=screenshot_assets,
        small_promo_tile=small_promo_tile,
        marquee_promo_image=marquee_promo_image,
        **values,
    )


def _extract_fenced_value(text: str, label: str) -> str:
    pattern = re.compile(
        rf"^{re.escape(label)}:\s*\n\s*\n```text\n(?P<value>.*?)\n```",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if match is None:
        raise ClientError(f"Listing file missing field: {label}")
    value = match.group("value").strip()
    if not value:
        raise ClientError(f"Listing file field is empty: {label}")
    return value


def _validate_https_url(value: str, field_name: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ClientError(f"Listing field {field_name} must be an https URL: {value}")


def _extract_screenshots(text: str, repo_root: Path) -> list[WebStoreListingAsset]:
    match = SCREENSHOT_DIRECTORY_PATTERN.search(text)
    if match is None:
        raise ClientError("Listing file missing screenshot directory: Screenshots")

    directory_path = match.group("path")
    screenshot_directory = (repo_root / directory_path).resolve()
    if not screenshot_directory.is_dir():
        raise ClientError(f"Screenshot directory does not exist: {directory_path}")

    paths = sorted(
        (path for path in screenshot_directory.iterdir() if path.suffix.lower() == ".png"),
        key=_natural_path_key,
    )
    if len(paths) == 0:
        raise ClientError(f"Screenshot directory must contain at least one PNG file: {directory_path}")
    if len(paths) > 5:
        raise ClientError(f"Screenshot directory must contain no more than 5 PNG files: {directory_path}")

    return [
        _prepare_screenshot_asset(path, repo_root)
        for path in paths
    ]


def _prepare_screenshot_asset(path: Path, repo_root: Path) -> WebStoreListingAsset:
    target_dimensions = PNG_DIMENSIONS["screenshot"]
    width, height = _png_dimensions(path)
    if (width, height) != target_dimensions or _png_mode(path) != "RGB":
        path = _convert_screenshot(path, target_dimensions)
    return _asset_from_path(
        "screenshot",
        str(path.relative_to(repo_root)),
        repo_root,
        expected_dimensions=target_dimensions,
    )


def _convert_screenshot(path: Path, target_dimensions: tuple[int, int]) -> Path:
    output_directory = path.parent / CONVERTED_SCREENSHOT_DIRECTORY
    output_directory.mkdir(exist_ok=True)
    output_path = output_directory / f"{path.stem}-{target_dimensions[0]}x{target_dimensions[1]}.png"
    with Image.open(path) as image:
        converted = ImageOps.fit(
            image,
            target_dimensions,
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        ).convert("RGB")
        converted.save(output_path, format="PNG")
    return output_path


def _extract_single_asset(text: str, kind: str, repo_root: Path) -> WebStoreListingAsset | None:
    match = ASSET_PATTERNS[kind].search(text)
    if match is None:
        return None
    return _asset_from_path(kind, match.group("path"), repo_root, expected_dimensions=PNG_DIMENSIONS[kind])


def _asset_from_path(
    kind: str,
    relative_path: str,
    repo_root: Path,
    expected_dimensions: tuple[int, int],
) -> WebStoreListingAsset:
    path = (repo_root / relative_path).resolve()
    if not path.is_file():
        raise ClientError(f"Listing asset does not exist: {relative_path}")
    width, height = _png_dimensions(path)
    if (width, height) != expected_dimensions:
        raise ClientError(
            f"Listing asset {relative_path} must be {expected_dimensions[0]}x{expected_dimensions[1]}, "
            f"got {width}x{height}."
        )
    if _png_mode(path) != "RGB":
        raise ClientError(f"Listing asset {relative_path} must be a 24-bit RGB PNG.")
    return WebStoreListingAsset(kind=kind, path=str(path), width=width, height=height)


def _png_dimensions(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    signature = b"\x89PNG\r\n\x1a\n"
    if len(data) < 24 or data[:8] != signature:
        raise ClientError(f"Listing asset is not a valid PNG: {path}")
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def _png_mode(path: Path) -> str:
    with Image.open(path) as image:
        return image.mode


def _natural_path_key(path: Path) -> list[object]:
    return [
        int(part) if part.isdigit() else part.lower()
        for part in re.split(r"(\d+)", path.name)
    ]
