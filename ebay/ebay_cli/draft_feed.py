"""Seller Hub FX_LISTING draft feed helpers."""

import csv
import gzip
import io
import xml.etree.ElementTree as ET
from enum import Enum
from typing import Optional


class DraftListingFormat(str, Enum):
    """Seller Hub draft format values."""

    AUCTION = "Auction"
    FIXED_PRICE = "FixedPrice"


DRAFT_FEED_HEADER = (
    "Action(SiteID=US|Country=US|Currency=USD|Version=1193|CC=UTF-8)",
    "Custom label (SKU)",
    "Category ID",
    "Title",
    "UPC",
    "Start price",
    "Quantity",
    "Item photo URL",
    "Condition ID",
    "Description",
    "Format",
)

DRAFT_FEED_INFO_ROWS = (
    (
        "#INFO",
        "Version=0.0.2",
        "Template= eBay-draft-listings-template_US",
    ),
    (
        "#INFO Action and Category ID are required fields. 1) Set Action to Draft "
        "2) Please find the category ID for your listings here: "
        "https://pages.ebay.com/sellerinformation/news/categorychanges.html",
    ),
    (
        "#INFO After you've successfully uploaded your draft from the Seller Hub "
        "Reports tab, complete your drafts to active listings here: "
        "https://www.ebay.com/sh/lst/drafts",
    ),
    ("#INFO",),
)

XML_IDENTIFIER_FIELDS = {
    "DraftID": "draft_id",
    "ItemID": "item_id",
    "SKU": "custom_label",
    "CorrelationID": "correlation_id",
}

CSV_IDENTIFIER_FIELDS = {
    "draft id": "draft_id",
    "item id": "item_id",
    "sku": "custom_label",
    "custom label (sku)": "custom_label",
    "correlation id": "correlation_id",
}

CSV_ERROR_FIELDS = {
    "error code": "error_code",
    "errorcode": "error_code",
    "severity": "severity",
    "severity code": "severity",
    "severitycode": "severity",
    "short message": "short_message",
    "shortmessage": "short_message",
    "long message": "long_message",
    "longmessage": "long_message",
    "error message": "long_message",
    "errormessage": "long_message",
}

# eBay's Bulk API Framework (BAF) backend returns generic, code-only errors for
# some failure modes. eBay Developer Support has confirmed there is no dedicated
# API for creating draft listings (community.ebay.com/t5/Traditional-APIs-Selling/
# Can-I-generate-drafts-via-API-instead-of-live-listings/td-p/35010391): the Sell
# Feed API's FX_LISTING task processor has no registered Task Action Id for the
# "Draft" action, so every upload fails identically regardless of file content.
# Verified live against production on 2026-08-04: a byte-correct minimal CSV
# (matching eBay's published "Draft template field definitions") still fails
# with this exact error. Only the browser-driven Seller Hub Reports > Uploads
# page can create a true Seller Hub draft; treat this as a platform limitation,
# not a fixable CSV/request defect.
KNOWN_ERROR_HINTS: tuple[tuple[str, str, str], ...] = (
    (
        "BAF.Error.5",
        "task action id for task draft",
        (
            "eBay's Sell Feed API does not support the Draft action end-to-end: "
            "eBay Developer Support has confirmed there is no dedicated API for "
            "creating draft listings (this is a platform limitation, not a file "
            "formatting problem — verified with a minimal, spec-correct CSV). "
            "Create the draft manually via Seller Hub > Reports > Uploads, or "
            "use a pseudo-draft workflow (publish then immediately end) instead."
        ),
    ),
)


def _hint_for_error(error: dict[str, str]) -> Optional[str]:
    """Return a known-cause hint for a recognized BAF error, if any."""
    code = (error.get("error_code") or "").strip()
    message = " ".join(
        (error.get("long_message") or "", error.get("short_message") or "")
    ).lower()
    for known_code, message_substring, hint in KNOWN_ERROR_HINTS:
        if code == known_code and message_substring in message:
            return hint
    return None


def _padded_row(values: tuple[object, ...]) -> list[object]:
    """Pad a feed row to the live Seller Hub column count."""
    return [*values, *([""] * (len(DRAFT_FEED_HEADER) - len(values)))]


def build_draft_feed_csv(
    *,
    category_id: str,
    sku: Optional[str] = None,
    title: Optional[str] = None,
    upc: Optional[str] = None,
    price: Optional[str] = None,
    quantity: Optional[int] = None,
    image_url: Optional[str] = None,
    condition_id: Optional[str] = None,
    description: Optional[str] = None,
    format_type: Optional[DraftListingFormat] = None,
) -> bytes:
    """Build one Draft action row with the live Seller Hub schema."""
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    for info_row in DRAFT_FEED_INFO_ROWS:
        writer.writerow(_padded_row(info_row))
    writer.writerow(DRAFT_FEED_HEADER)
    writer.writerow(
        (
            "Draft",
            sku or "",
            category_id,
            title or "",
            upc or "",
            price or "",
            quantity if quantity is not None else "",
            image_url or "",
            condition_id or "",
            description or "",
            format_type.value if format_type is not None else "",
        )
    )
    return output.getvalue().encode("utf-8")


def decode_feed_result(content: bytes) -> str:
    """Decode an uncompressed or GZIP result file."""
    if content.startswith(b"\x1f\x8b"):
        content = gzip.decompress(content)
    return content.decode("utf-8-sig")


def extract_feed_result(
    content: str,
    *,
    custom_label: Optional[str],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Extract available draft identifiers and result errors."""
    identifiers = {"custom_label": custom_label} if custom_label else {}
    errors: list[dict[str, str]] = []
    stripped = content.lstrip()

    if stripped.startswith("<"):
        root = ET.fromstring(content)
        for element in root.iter():
            field = element.tag.rsplit("}", 1)[-1]
            output_field = XML_IDENTIFIER_FIELDS.get(field)
            value = (element.text or "").strip()
            if output_field and value and output_field not in identifiers:
                identifiers[output_field] = value

            if field != "Errors":
                continue
            error_values = {
                child.tag.rsplit("}", 1)[-1]: (child.text or "").strip()
                for child in element
            }
            error = {
                "error_code": error_values.get("ErrorCode", ""),
                "severity": error_values.get("SeverityCode", ""),
                "short_message": error_values.get("ShortMessage", ""),
                "long_message": error_values.get("LongMessage", ""),
            }
            if any(error.values()):
                errors.append(error)
    else:
        for row in csv.DictReader(io.StringIO(content)):
            normalized_row = {
                field.strip().lower(): (value or "").strip()
                for field, value in row.items()
            }
            for normalized, clean_value in normalized_row.items():
                output_field = CSV_IDENTIFIER_FIELDS.get(normalized)
                if output_field and clean_value and output_field not in identifiers:
                    identifiers[output_field] = clean_value

            error = {
                output_field: normalized_row[field]
                for field, output_field in CSV_ERROR_FIELDS.items()
                if normalized_row.get(field)
            }
            if error:
                errors.append(error)

    for error in errors:
        hint = _hint_for_error(error)
        if hint:
            error["hint"] = hint

    return ([identifiers] if identifiers else []), errors
