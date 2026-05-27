"""Unified Listings commands for eBay CLI.

Abstracts eBay's Inventory API, Offer API, and Trading API into a single
consistent interface for managing listings.

Commands:
- list: List all listings (active + drafts)
- get: Get single listing by SKU
- create: Create draft listing (with optional --publish)
- update: Update existing listing
- delete: Withdraw and delete listing
- publish: Publish draft to make it live
- unpublish: Withdraw active listing back to draft
- preview: Preview draft before publishing
"""
COMMAND_CREDENTIALS = {
    "create": ["oauth_authorization_code"],
    "delete": ["oauth_authorization_code"],
    "get": ["oauth_authorization_code"],
    "list": ["oauth_authorization_code"],
    "preview": ["oauth_authorization_code"],
    "publish": ["oauth_authorization_code"],
    # Top-level `ebay listings search` is registered from search.py under the
    # shared `listings` group name, so metadata consumers still expect this key.
    "search": ["no_auth"],
    "unpublish": ["oauth_authorization_code"],
    "update": ["oauth_authorization_code"],
}

import json
import shutil
import subprocess
import sys
import tempfile
import webbrowser
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Any, List

import typer

from ..client import get_client, ClientError
from ..models import (
    Listing,
    ListingStatus,
    Image,
    is_valid_sku,
    listing_from_offer,
    listing_from_trading_api,
    merge_listing_data,
    PSEUDO_DRAFT_PRICE,
    CONDITION_ID_TO_ENUM,
    CONDITION_ENUM_TO_ID,
)
from cli_tools_shared.output import (
    print_json,
    print_table,
    handle_error,
    print_success,
    print_info,
    print_warning,
    print_error,
)
from cli_tools_shared.filters import validate_filters, apply_filters, FilterValidationError
from ..properties import validate_and_filter_properties, PropertyValidationError
from ..storage import TemplateStorage, DraftStorage
from ..template_validation import validate_template_data

app = typer.Typer(help="Manage eBay listings (drafts and active)")

# Maximum images per listing (eBay limit)
MAX_IMAGES = 12

# Supported image extensions for --image-folder scanning
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

# eBay XML namespace for Trading API parsing
NS = {"ebay": "urn:ebay:apis:eBLBaseComponents"}


# =============================================================================
# Helper Functions: Condition Validation
# =============================================================================


def _validate_condition_for_category(client, condition: str, category_id: str) -> None:
    """
    Validate that a condition enum is valid for the given eBay category.

    Queries the eBay Metadata API to get valid conditions for the category,
    then checks if the requested condition is in the list. Raises typer.Exit
    on validation failure.

    Args:
        client: Authenticated EbayClient instance
        condition: Condition enum string (e.g., "NEW_OTHER")
        category_id: eBay category ID (e.g., "261329")
    """
    condition_upper = condition.upper()
    condition_id = CONDITION_ENUM_TO_ID.get(condition_upper)
    if not condition_id:
        print_warning(f"Unknown condition enum '{condition_upper}', skipping validation")
        return

    try:
        result = client.get_item_condition_policies(category_ids=[category_id])
        policies = result.get("itemConditionPolicies", [])
        if not policies:
            print_warning(f"Could not retrieve condition policies for category {category_id}, skipping validation")
            return

        policy = policies[0]
        valid_conditions = policy.get("itemConditions", [])
        valid_ids = {c.get("conditionId") for c in valid_conditions}

        if condition_id not in valid_ids:
            valid_enums = []
            for vc in valid_conditions:
                vc_id = vc.get("conditionId", "")
                vc_enum = CONDITION_ID_TO_ENUM.get(vc_id, vc_id)
                vc_desc = vc.get("conditionDescription", "")
                valid_enums.append(f"{vc_enum} ({vc_desc})")

            print_error(
                f"Condition '{condition_upper}' (ID {condition_id}) is not valid "
                f"for category {category_id}."
            )
            print_info(f"Valid conditions for this category: {', '.join(valid_enums)}")
            raise typer.Exit(1)

    except ClientError as e:
        print_warning(f"Could not validate condition against category: {e}")
        # Non-fatal: allow the request to proceed and let eBay API reject it if invalid


# =============================================================================
# Helper Functions: Trading API XML Parsing
# =============================================================================


def _find_element(parent: Optional[ET.Element], path: str) -> Optional[ET.Element]:
    """Find child element, trying with namespace first then without."""
    if parent is None:
        return None
    el = parent.find(f"ebay:{path}", NS)
    if el is not None:
        return el
    return parent.find(path)


def _get_text(element: Optional[ET.Element], path: str, default: str = "") -> str:
    """Get text from an element, handling namespace and None."""
    if element is None:
        return default
    el = _find_element(element, path)
    return el.text if el is not None and el.text else default


def _parse_seller_list_xml(xml_content: str) -> tuple[list[dict], int, int]:
    """Parse GetSellerList XML response into list of items."""
    try:
        root = ET.fromstring(xml_content)

        ack = _get_text(root, "Ack")
        if ack == "Failure":
            errors = _find_element(root, "Errors")
            if errors is not None:
                error_msg = _get_text(errors, "LongMessage") or _get_text(errors, "ShortMessage")
                raise ClientError(f"eBay API error: {error_msg}")
            raise ClientError("eBay API returned failure status")

        pagination_result = _find_element(root, "PaginationResult")
        total_entries = int(_get_text(pagination_result, "TotalNumberOfEntries", "0"))
        total_pages = int(_get_text(pagination_result, "TotalNumberOfPages", "0"))

        items = []
        item_array = _find_element(root, "ItemArray")
        if item_array is None:
            return items, total_entries, total_pages

        item_elements = item_array.findall("ebay:Item", NS)
        if not item_elements:
            item_elements = item_array.findall("Item")

        for item_el in item_elements:
            item: dict[str, Any] = {}
            item["item_id"] = _get_text(item_el, "ItemID")
            item["title"] = _get_text(item_el, "Title")
            item["sku"] = _get_text(item_el, "SKU")
            item["listing_type"] = _get_text(item_el, "ListingType")

            listing_details = _find_element(item_el, "ListingDetails")
            if listing_details is not None:
                item["url"] = _get_text(listing_details, "ViewItemURL")

            qty_available = _get_text(item_el, "QuantityAvailable")
            qty = _get_text(item_el, "Quantity")
            item["quantity"] = qty_available if qty_available else qty

            selling_status = _find_element(item_el, "SellingStatus")
            if selling_status is not None:
                current_price = _find_element(selling_status, "CurrentPrice")
                if current_price is not None and current_price.text:
                    item["price"] = current_price.text
                    item["currency"] = current_price.get("currencyID", "USD")
                qty_sold = _get_text(selling_status, "QuantitySold")
                if qty_sold:
                    item["quantity_sold"] = qty_sold

            picture_details = _find_element(item_el, "PictureDetails")
            if picture_details is not None:
                gallery_url = _get_text(picture_details, "GalleryURL")
                if gallery_url:
                    item["image_url"] = gallery_url

                picture_urls = []
                pic_elements = picture_details.findall("ebay:PictureURL", NS)
                if not pic_elements:
                    pic_elements = picture_details.findall("PictureURL")
                for pic_url in pic_elements:
                    if pic_url.text:
                        picture_urls.append(pic_url.text)
                if picture_urls:
                    item["image_urls"] = picture_urls
                    if "image_url" not in item:
                        item["image_url"] = picture_urls[0]

            items.append(item)

        return items, total_entries, total_pages

    except ET.ParseError as e:
        raise ClientError(f"Failed to parse XML response: {e}")


# =============================================================================
# Helper Functions: Image Upload
# =============================================================================


def _scan_folder_for_images(folder_path: str) -> list[str]:
    """Scan a folder for image files."""
    folder = Path(folder_path)
    if not folder.exists():
        raise FileNotFoundError(f"Folder not found: {folder_path}")
    if not folder.is_dir():
        raise NotADirectoryError(f"Not a directory: {folder_path}")

    image_files = []
    for file in folder.iterdir():
        if file.is_file() and file.suffix.lower() in IMAGE_EXTENSIONS:
            image_files.append(str(file.absolute()))

    image_files.sort()
    return image_files


def _export_photos_from_album(album_name: str, limit: int = MAX_IMAGES) -> tuple[list[str], str]:
    """Export photos from macOS Photos app album to temp directory."""
    temp_dir = tempfile.mkdtemp(prefix="ebay_photos_")

    try:
        result = subprocess.run(
            ["photos-app", "photos", "download", temp_dir, "--album", album_name, "--limit", str(limit)],
            capture_output=True,
            text=True,
            timeout=300,
        )
    except FileNotFoundError:
        raise RuntimeError("photos-app CLI not found. Install it with `_repo/_scripts/install-cli-tool.sh photos-app` from the cli-tools repo root.")
    except subprocess.TimeoutExpired:
        raise RuntimeError("Photo export timed out - photos may still be downloading from iCloud")

    if result.returncode != 0:
        error_msg = result.stderr.strip() if result.stderr else result.stdout.strip()
        raise RuntimeError(f"Failed to export photos from album '{album_name}': {error_msg}")

    exported_paths = []
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if line and line.startswith("/") and Path(line).exists():
            exported_paths.append(line)

    if not exported_paths:
        raise RuntimeError(f"No photos were exported from album '{album_name}'")

    return exported_paths, temp_dir


def _upload_images_for_listing(
    client,
    sku: str,
    image_paths: Optional[str],
    image_urls: Optional[str],
) -> tuple[list[str], list[dict]]:
    """Upload images and update inventory item's imageUrls."""
    from ..storage import ImageStorage

    uploaded_urls: list[str] = []
    errors: list[dict] = []
    storage = ImageStorage()

    sources: list[tuple[str, str]] = []

    if image_paths:
        for path in image_paths.split(","):
            sources.append((path.strip(), "file"))

    if image_urls:
        for url in image_urls.split(","):
            sources.append((url.strip(), "url"))

    if not sources:
        return uploaded_urls, errors

    if len(sources) > MAX_IMAGES:
        print_warning(f"Only first {MAX_IMAGES} images will be used (eBay limit). {len(sources)} provided.")
        sources = sources[:MAX_IMAGES]

    for source_value, source_type in sources:
        try:
            if source_type == "file":
                if not Path(source_value).exists():
                    errors.append({"source": source_value, "error": "File not found"})
                    print_warning(f"Image file not found: {source_value}")
                    continue
                result = client.upload_image_from_file(source_value)
            else:
                result = client.upload_image_from_url(source_value)

            storage.add_image(
                image_id=result["image_id"],
                image_url=result["imageUrl"],
                expiration_date=result["expirationDate"],
                source=source_type,
                original=source_value
            )
            uploaded_urls.append(result["imageUrl"])
            print_info(f"Uploaded image: {source_value}")

        except Exception as e:
            errors.append({"source": source_value, "error": str(e)})
            print_warning(f"Failed to upload {source_value}: {e}")

    if uploaded_urls:
        try:
            current_item = client.get_inventory_item(sku)
            product = current_item.get("product", {})
            existing_urls = product.get("imageUrls", [])

            combined_urls = uploaded_urls + [u for u in existing_urls if u not in uploaded_urls]
            combined_urls = combined_urls[:MAX_IMAGES]

            update_payload = current_item.copy()
            for field in ["sku", "locale", "groupIds", "inventoryItemGroupKeys"]:
                update_payload.pop(field, None)

            if "product" not in update_payload:
                update_payload["product"] = {}
            update_payload["product"]["imageUrls"] = combined_urls

            client.create_or_update_inventory_item(sku, update_payload)
            print_info(f"Updated inventory item with {len(uploaded_urls)} new image(s).")

        except Exception as e:
            print_warning(f"Failed to update inventory item images: {e}")

    return uploaded_urls, errors


# =============================================================================
# Helper Functions: Template Support
# =============================================================================


def _template_to_offer_payload(template_data: dict) -> dict:
    """Transform template structure to eBay Offer API format."""
    payload = {}

    if "marketplaceId" in template_data:
        payload["marketplaceId"] = template_data["marketplaceId"]

    if "category" in template_data:
        cat = template_data["category"]
        if "categoryId" in cat:
            payload["categoryId"] = cat["categoryId"]
        # Store category support - convert storeCategoryName to storeCategoryNames array
        if "storeCategoryName" in cat:
            store_cat = cat["storeCategoryName"]
            # Try without leading slash - API format unclear
            payload["storeCategoryNames"] = [store_cat]

    if "pricing" in template_data:
        pricing = template_data["pricing"]
        if "format" in pricing:
            payload["format"] = pricing["format"]
        if "price" in pricing:
            if pricing.get("format") == "AUCTION":
                payload["pricingSummary"] = {"auctionStartPrice": pricing["price"]}
            else:
                payload["pricingSummary"] = {"price": pricing["price"]}
        if pricing.get("format") == "AUCTION" and "buyItNowPrice" in pricing:
            if "pricingSummary" not in payload:
                payload["pricingSummary"] = {}
            payload["pricingSummary"]["price"] = pricing["buyItNowPrice"]
        if "quantity" in pricing:
            payload["availableQuantity"] = pricing["quantity"]

    listing_policies = {}
    if "shipping" in template_data:
        ship = template_data["shipping"]
        if "fulfillmentPolicyId" in ship:
            listing_policies["fulfillmentPolicyId"] = ship["fulfillmentPolicyId"]
    if "policies" in template_data:
        pol = template_data["policies"]
        if "paymentPolicyId" in pol:
            listing_policies["paymentPolicyId"] = pol["paymentPolicyId"]
        if "returnPolicyId" in pol:
            listing_policies["returnPolicyId"] = pol["returnPolicyId"]
    if listing_policies:
        payload["listingPolicies"] = listing_policies

    if "location" in template_data:
        loc = template_data["location"]
        if "merchantLocationKey" in loc:
            payload["merchantLocationKey"] = loc["merchantLocationKey"]

    for key in ["categoryId", "format", "pricingSummary", "listingPolicies",
                "merchantLocationKey", "availableQuantity", "listingDescription"]:
        if key in template_data and key not in payload:
            payload[key] = template_data[key]

    return payload


# =============================================================================
# Helper Functions: Data Fetching & Merging
# =============================================================================


def _fetch_all_offers(client, limit: int = 200) -> list[dict]:
    """Fetch all offers from Inventory API.

    Attempts bulk query. If that fails (e.g., due to orphaned offers with
    invalid SKUs in eBay's system), returns empty list.
    """
    all_offers = []
    offset = 0

    try:
        while True:
            result = client.get_offers(sku=None, limit=min(limit - len(all_offers), 200), offset=offset)
            offers = result.get("offers", [])
            if not offers:
                break
            all_offers.extend(offers)
            if len(all_offers) >= limit:
                break
            offset += len(offers)
            if len(offers) < 200:
                break
        return all_offers[:limit]
    except ClientError:
        return []


def _fetch_draft_offers(client, limit: int = 100) -> list[dict]:
    """Fetch draft offers using locally tracked draft IDs.

    This is instant because we only query offer IDs we already know about.
    Falls back to per-SKU queries if local tracking is empty.
    """
    storage = DraftStorage()
    tracked_drafts = storage.get_all_drafts()

    if not tracked_drafts:
        return []

    draft_offers = []
    stale_skus = []  # Track drafts that no longer exist

    for draft in tracked_drafts[:limit]:
        sku = draft.get("sku")
        if not sku:
            continue
        try:
            offer_result = client.get_offers(sku=sku, limit=1, offset=0)
            offers = offer_result.get("offers", [])
            if offers:
                offer = offers[0]
                if offer.get("status") != "PUBLISHED":
                    draft_offers.append(offer)
                else:
                    # Offer was published, remove from tracking
                    stale_skus.append(sku)
            else:
                # No offer found, remove from tracking
                stale_skus.append(sku)
        except ClientError:
            # Offer may have been deleted
            stale_skus.append(sku)

    # Clean up stale entries
    for sku in stale_skus:
        storage.remove_draft(sku)

    return draft_offers[:limit]


def _fetch_all_active_listings(client, limit: int = 200) -> list[dict]:
    """Fetch all active listings from Trading API."""
    all_items = []
    page = 1
    entries_per_page = min(limit, 200)

    while len(all_items) < limit:
        xml_response = client.get_seller_list(
            entries_per_page=entries_per_page,
            page_number=page,
        )
        items, total, total_pages = _parse_seller_list_xml(xml_response)
        if not items:
            break
        all_items.extend(items)
        page += 1
        if page > total_pages:
            break

    return all_items[:limit]


def _fetch_my_ebay_selling_list(client, list_type: str, status_label: str, limit: int = 200) -> list[dict]:
    """Fetch listings from Trading API via GetMyeBaySelling.

    Args:
        client: Authenticated EbayClient instance
        list_type: XML element name - 'SoldList' or 'UnsoldList'
        status_label: Status string to assign - 'sold' or 'unsold'
        limit: Maximum items to fetch
    """
    import requests
    import re

    all_items = []
    page = 1

    while len(all_items) < limit:
        xml_request = f'''<?xml version="1.0" encoding="utf-8"?>
<GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials>
    <eBayAuthToken>{client.config.access_token}</eBayAuthToken>
  </RequesterCredentials>
  <{list_type}>
    <Include>true</Include>
    <Pagination>
      <EntriesPerPage>200</EntriesPerPage>
      <PageNumber>{page}</PageNumber>
    </Pagination>
  </{list_type}>
  <OutputSelector>ItemID</OutputSelector>
  <OutputSelector>SKU</OutputSelector>
  <OutputSelector>Title</OutputSelector>
  <OutputSelector>SellingStatus</OutputSelector>
  <OutputSelector>PictureDetails</OutputSelector>
  <OutputSelector>Quantity</OutputSelector>
  <OutputSelector>QuantitySold</OutputSelector>
  <OutputSelector>PaginationResult</OutputSelector>
</GetMyeBaySellingRequest>'''

        headers = {
            'X-EBAY-API-COMPATIBILITY-LEVEL': '967',
            'X-EBAY-API-CALL-NAME': 'GetMyeBaySelling',
            'X-EBAY-API-SITEID': '0',
            'Content-Type': 'text/xml',
        }

        try:
            response = requests.post(
                'https://api.ebay.com/ws/api.dll',
                headers=headers,
                data=xml_request,
                timeout=30,
            )
        except Exception:
            break

        # Parse response with regex for simplicity
        item_ids = re.findall(r'<ItemID>(\d+)</ItemID>', response.text)
        skus = re.findall(r'<SKU>([^<]+)</SKU>', response.text)
        titles = re.findall(r'<Title>([^<]+)</Title>', response.text)
        quantities_sold = re.findall(r'<QuantitySold>(\d+)</QuantitySold>', response.text)

        # Get pagination info
        total_pages_match = re.search(r'<TotalNumberOfPages>(\d+)</TotalNumberOfPages>', response.text)
        total_pages = int(total_pages_match.group(1)) if total_pages_match else 1

        # Build items list (SKU and title lists may be shorter if some items lack them)
        for i, item_id in enumerate(item_ids):
            item = {
                'item_id': item_id,
                'sku': skus[i] if i < len(skus) else '',
                'title': titles[i] if i < len(titles) else '',
                'status': status_label,
                'quantity_sold': int(quantities_sold[i]) if i < len(quantities_sold) else 0,
            }
            all_items.append(item)

        if not item_ids or page >= total_pages:
            break
        page += 1

    return all_items[:limit]


def _fetch_unsold_listings(client, limit: int = 200) -> list[dict]:
    """Fetch unsold listings from Trading API via GetMyeBaySelling."""
    return _fetch_my_ebay_selling_list(client, 'UnsoldList', 'unsold', limit)


def _fetch_sold_listings(client, limit: int = 200) -> list[dict]:
    """Fetch sold listings from Trading API via GetMyeBaySelling."""
    return _fetch_my_ebay_selling_list(client, 'SoldList', 'sold', limit)


def _get_merged_listings(client, limit: int = 100, status_filter: Optional[str] = None) -> list[Listing]:
    """
    Fetch and merge listings from both APIs.

    Returns unified Listing objects combining offer and trading API data.
    Status filter can be: "active", "draft", "unsold", or "sold".
    """
    # Skip active/draft fetching when only sold or unsold is requested
    skip_active = status_filter in ("sold", "unsold")

    # Fetch active listings first (needed for all filters to avoid duplicates)
    active_items = [] if skip_active else _fetch_all_active_listings(client, limit * 2)

    # Build lookup by SKU for active items (only valid SKUs)
    active_by_sku: dict[str, dict] = {}
    for item in active_items:
        sku = item.get("sku")
        if sku and is_valid_sku(sku):
            active_by_sku[sku] = item

    # Fetch offers - use fast local tracking for drafts
    if skip_active:
        offers = []
    elif status_filter == "draft":
        # Fast path: query only locally tracked draft offer IDs
        offers = _fetch_draft_offers(client, limit * 2)
    else:
        offers = _fetch_all_offers(client, limit * 2)

    # Fetch unsold items if needed
    unsold_items = []
    if status_filter is None or status_filter == "unsold":
        unsold_items = _fetch_unsold_listings(client, limit * 2)

    # Fetch sold items if needed
    sold_items = []
    if status_filter is None or status_filter == "sold":
        sold_items = _fetch_sold_listings(client, limit * 2)

    # Track which SKUs we've processed
    processed_skus: set[str] = set()
    listings: list[Listing] = []

    # Process offers first (has more metadata)
    for offer in offers:
        sku = offer.get("sku", "")
        if not sku or sku in processed_skus:
            continue

        # Skip offers with invalid SKUs (can't query inventory API for them)
        if not is_valid_sku(sku):
            continue

        # Fetch inventory item for additional data
        try:
            inventory_item = client.get_inventory_item(sku)
        except Exception:
            inventory_item = None

        offer_listing = listing_from_offer(offer, inventory_item)

        # listing_from_offer returns None for invalid SKUs
        if offer_listing is None:
            continue

        # Check if there's matching active listing
        if sku in active_by_sku:
            trading_listing = listing_from_trading_api(active_by_sku[sku])
            if trading_listing:
                merged = merge_listing_data(offer_listing, trading_listing)
                listings.append(merged)
            else:
                listings.append(offer_listing)
        else:
            listings.append(offer_listing)

        processed_skus.add(sku)

    # Add active listings without offers (legacy listings)
    for sku, item in active_by_sku.items():
        if sku and sku not in processed_skus and is_valid_sku(sku):
            listing = listing_from_trading_api(item)
            if listing:
                listings.append(listing)
                processed_skus.add(sku)

    # Add unsold listings
    for item in unsold_items:
        sku = item.get("sku", "")
        item_id = item.get("item_id", "")

        # Skip if already processed (by valid SKU)
        if sku and is_valid_sku(sku) and sku in processed_skus:
            continue

        # Use item_id as fallback SKU for items with invalid/missing SKUs
        effective_sku = sku if sku and is_valid_sku(sku) else f"unsold{item_id}"

        # Create unsold listing
        listing = Listing(
            sku=effective_sku,
            item_id=item_id,
            title=item.get("title", ""),
            status=ListingStatus.UNSOLD,
            url=f"https://www.ebay.com/itm/{item_id}" if item_id else None,
        )
        listings.append(listing)
        if sku and is_valid_sku(sku):
            processed_skus.add(sku)

    # Add sold listings
    for item in sold_items:
        sku = item.get("sku", "")
        item_id = item.get("item_id", "")

        if sku and is_valid_sku(sku) and sku in processed_skus:
            continue

        effective_sku = sku if sku and is_valid_sku(sku) else f"sold{item_id}"

        listing = Listing(
            sku=effective_sku,
            item_id=item_id,
            title=item.get("title", ""),
            status=ListingStatus.SOLD,
            quantity_sold=item.get("quantity_sold", 0),
            url=f"https://www.ebay.com/itm/{item_id}" if item_id else None,
        )
        listings.append(listing)
        if sku and is_valid_sku(sku):
            processed_skus.add(sku)

    # Apply status filter
    if status_filter:
        if status_filter == "active":
            # Exclude pseudo-drafts from active listings (they're really drafts)
            listings = [l for l in listings if l.is_active and not l.is_pseudo_draft]
        elif status_filter == "draft":
            # Include both real drafts AND pseudo-drafts (active at $99,999)
            listings = [l for l in listings if l.is_draft or l.is_pseudo_draft]
        elif status_filter == "unsold":
            listings = [l for l in listings if l.is_unsold]
        elif status_filter == "sold":
            listings = [l for l in listings if l.is_sold]

    return listings[:limit]


def _get_listing_by_sku(client, sku: str) -> Optional[Listing]:
    """Get a single listing by SKU, merging data from all APIs."""
    # Try to get offer for this SKU
    offer = None
    inventory_item = None

    try:
        result = client.get_offers(sku=sku, limit=1, offset=0)
        offers = result.get("offers", [])
        if offers:
            offer = offers[0]
    except Exception:
        pass

    try:
        inventory_item = client.get_inventory_item(sku)
    except Exception:
        pass

    # If we have an offer, build listing from it
    if offer:
        listing = listing_from_offer(offer, inventory_item)

        # If published, try to get additional data from Trading API
        if listing.is_active and listing.item_id:
            try:
                active_items = _fetch_all_active_listings(client, 500)
                for item in active_items:
                    if item.get("sku") == sku:
                        trading_listing = listing_from_trading_api(item)
                        listing = merge_listing_data(listing, trading_listing)
                        break
            except Exception:
                pass

        return listing

    # No offer - try to find in active listings (legacy)
    try:
        active_items = _fetch_all_active_listings(client, 500)
        for item in active_items:
            if item.get("sku") == sku:
                return listing_from_trading_api(item)
    except Exception:
        pass

    # Check if inventory item exists but no offer
    if inventory_item:
        # Return minimal listing from inventory item only
        product = inventory_item.get("product", {})
        images = []
        for i, url in enumerate(product.get("imageUrls", [])):
            images.append(Image(url=url, position=i))

        return Listing(
            sku=sku,
            title=product.get("title", ""),
            description=product.get("description"),
            condition=inventory_item.get("condition"),
            quantity=inventory_item.get("availability", {}).get("shipToLocationAvailability", {}).get("quantity", 0),
            images=images,
            status="draft",  # No offer means it's not listed
        )

    return None


# =============================================================================
# Helper Functions: Preview Generation
# =============================================================================


def _generate_preview_html(listing: Listing) -> str:
    """Generate HTML preview for a listing."""
    # Build image gallery HTML
    if listing.images:
        main_image = listing.images[0].url
        thumbnail_html = "".join([
            f'<img src="{img.url}" class="thumbnail" onclick="document.getElementById(\'mainImage\').src=\'{img.url}\'" alt="Thumbnail {i+1}">'
            for i, img in enumerate(listing.images[:12])
        ])
        gallery_html = f'''
        <div class="image-gallery">
            <div class="main-image">
                <img id="mainImage" src="{main_image}" alt="{listing.title}">
            </div>
            <div class="thumbnails">
                {thumbnail_html}
            </div>
            <div class="image-count">{len(listing.images)} image{"s" if len(listing.images) != 1 else ""}</div>
        </div>
        '''
    else:
        gallery_html = '''
        <div class="image-gallery">
            <div class="no-image">No images uploaded</div>
        </div>
        '''

    # Pricing HTML based on format
    format_display = "Auction" if listing.format == "auction" else "Buy It Now"
    if listing.format == "auction":
        pricing_html = f'''
        <div class="price-section auction">
            <div class="format-badge">Auction</div>
            <div class="current-bid">
                <span class="label">Starting bid:</span>
                <span class="price">${listing.price}</span>
            </div>
        </div>
        '''
    else:
        pricing_html = f'''
        <div class="price-section fixed">
            <div class="format-badge">Buy It Now</div>
            <div class="buy-now-price">
                <span class="price">${listing.price}</span>
            </div>
        </div>
        '''

    status_class = "unpublished" if listing.is_draft else ""

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Listing Preview - {listing.title}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; background: #f7f7f7; color: #333; line-height: 1.5; }}
        .preview-banner {{ background: linear-gradient(135deg, #3665f3 0%, #0654ba 100%); color: white; padding: 15px 20px; text-align: center; font-size: 14px; }}
        .preview-banner .status {{ display: inline-block; background: rgba(255,255,255,0.2); padding: 4px 12px; border-radius: 4px; margin-left: 10px; font-weight: bold; }}
        .preview-banner .status.unpublished {{ background: #ff9800; }}
        .container {{ max-width: 1200px; margin: 0 auto; padding: 20px; display: grid; grid-template-columns: 1fr 400px; gap: 30px; }}
        @media (max-width: 900px) {{ .container {{ grid-template-columns: 1fr; }} }}
        .left-column {{ background: white; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); padding: 20px; }}
        .right-column {{ display: flex; flex-direction: column; gap: 20px; }}
        .card {{ background: white; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); padding: 20px; }}
        .image-gallery {{ margin-bottom: 20px; }}
        .main-image {{ width: 100%; aspect-ratio: 1; background: #f0f0f0; border-radius: 8px; overflow: hidden; display: flex; align-items: center; justify-content: center; }}
        .main-image img {{ max-width: 100%; max-height: 100%; object-fit: contain; }}
        .thumbnails {{ display: flex; gap: 8px; margin-top: 10px; overflow-x: auto; padding: 5px 0; }}
        .thumbnail {{ width: 60px; height: 60px; object-fit: cover; border-radius: 4px; cursor: pointer; border: 2px solid transparent; }}
        .thumbnail:hover {{ border-color: #3665f3; }}
        .image-count {{ font-size: 12px; color: #666; margin-top: 8px; text-align: center; }}
        .no-image {{ padding: 60px; text-align: center; color: #999; font-size: 18px; }}
        .title {{ font-size: 22px; font-weight: 600; color: #191919; margin-bottom: 15px; }}
        .condition {{ display: inline-block; background: #e7e7e7; padding: 4px 10px; border-radius: 4px; font-size: 13px; margin-bottom: 15px; }}
        .price-section {{ padding: 20px; border-radius: 8px; margin-bottom: 15px; }}
        .price-section.auction {{ background: linear-gradient(135deg, #fff3e0 0%, #ffe0b2 100%); }}
        .price-section.fixed {{ background: linear-gradient(135deg, #e8f5e9 0%, #c8e6c9 100%); }}
        .format-badge {{ font-size: 12px; font-weight: bold; text-transform: uppercase; color: #666; margin-bottom: 10px; }}
        .price {{ font-size: 28px; font-weight: bold; color: #191919; }}
        .quantity {{ font-size: 14px; color: #555; margin-bottom: 15px; }}
        .description {{ margin-top: 20px; padding-top: 20px; border-top: 1px solid #e7e7e7; }}
        .description h3 {{ font-size: 16px; font-weight: 600; margin-bottom: 10px; }}
        .description-content {{ font-size: 14px; color: #333; white-space: pre-wrap; }}
        .metadata {{ font-size: 13px; color: #666; }}
        .metadata-row {{ display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #eee; }}
        .metadata-row:last-child {{ border-bottom: none; }}
        .metadata-label {{ color: #888; }}
        .command-box {{ background: #1e1e1e; color: #4ec9b0; padding: 15px; border-radius: 8px; font-family: monospace; font-size: 13px; margin-top: 10px; }}
        .warning {{ background: #fff3cd; border: 1px solid #ffc107; border-radius: 8px; padding: 15px; font-size: 13px; color: #856404; }}
        .warning-title {{ font-weight: 600; margin-bottom: 5px; }}
    </style>
</head>
<body>
    <div class="preview-banner">
        LISTING PREVIEW - This is how your listing will appear on eBay
        <span class="status {status_class}">{listing.status.upper()}</span>
    </div>
    <div class="container">
        <div class="left-column">
            {gallery_html}
            <h1 class="title">{listing.title}</h1>
            <span class="condition">{(listing.condition or "Not specified").replace('_', ' ').title()}</span>
            <div class="description">
                <h3>Description</h3>
                <div class="description-content">{listing.description or "No description provided."}</div>
            </div>
        </div>
        <div class="right-column">
            <div class="card">
                {pricing_html}
                <div class="quantity"><strong>Quantity:</strong> {listing.quantity} available</div>
                <div class="command-box">ebay listings publish {listing.sku}</div>
            </div>
            <div class="card metadata">
                <div class="metadata-row"><span class="metadata-label">SKU</span><span>{listing.sku}</span></div>
                <div class="metadata-row"><span class="metadata-label">Offer ID</span><span>{listing.offer_id or "N/A"}</span></div>
                <div class="metadata-row"><span class="metadata-label">Category</span><span>{listing.category_id or "Not set"}</span></div>
                <div class="metadata-row"><span class="metadata-label">Format</span><span>{format_display}</span></div>
            </div>
            {"<div class='warning'><div class='warning-title'>Preview Only</div>This listing is NOT live on eBay. To publish, copy the command above.</div>" if listing.is_draft else ""}
        </div>
    </div>
</body>
</html>
'''
    return html


# =============================================================================
# Commands
# =============================================================================


@app.command("list")
def listings_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum number of listings (default: all)"),
    offset: int = typer.Option(0, "--offset", "-o", help="Offset for pagination"),
    status: Optional[str] = typer.Option(
        None,
        "--status",
        "-s",
        help="Filter by status: active, draft, sold, unsold, or all (default: all)"
    ),
    filters: Optional[List[str]] = typer.Option(
        None,
        "--filter",
        "-f",
        help="Filter (field:op:value). Operators: eq, ne, gt, gte, lt, lte, in, nin, like, ilike, null, notnull"
    ),
    properties: Optional[str] = typer.Option(
        None,
        "--properties",
        "-p",
        help="Comma-separated list of fields to include"
    ),
):
    """
    List all eBay listings (active and drafts).

    Combines data from eBay's Inventory API (offers) and Trading API (active listings)
    into a unified view.

    Examples:
        ebay listings list --table
        ebay listings list --status draft
        ebay listings list --status sold --limit 50
        ebay listings list --status active --limit 50
        ebay listings list --properties sku,title,price,status
        ebay listings list --filter "price:gt:50"
    """
    try:
        client = get_client()

        print_info("Fetching listings...")
        # When limit is None, fetch all listings (use a large number for internal pagination)
        fetch_limit = (limit + offset) if limit is not None else 100000
        listings = _get_merged_listings(client, fetch_limit, status)

        # Apply offset
        if offset:
            listings = listings[offset:]
        if limit is not None:
            listings = listings[:limit]

        if not listings:
            print_warning("No listings found.")
            return

        # Convert to dicts for output
        listing_dicts = [l.to_dict() for l in listings]

        # Validate and apply client-side filters if provided
        if filters:
            try:
                validated_filters = validate_filters(filters)
                listing_dicts = apply_filters(listing_dicts, validated_filters)
            except FilterValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        # Apply properties filter
        if properties:
            try:
                listing_dicts = validate_and_filter_properties(listing_dicts, properties)
            except PropertyValidationError as e:
                print_error(str(e))
                raise typer.Exit(1)

        if table:
            columns = ["sku", "title", "price", "quantity", "status", "format"]
            headers = ["SKU", "Title", "Price", "Qty", "Status", "Format"]

            display_items = []
            for item in listing_dicts:
                display = item.copy()
                if "title" in display and len(str(display["title"])) > 40:
                    display["title"] = str(display["title"])[:37] + "..."
                display_items.append(display)

            print_table(display_items, columns, headers)
        else:
            output = {
                "listings": listing_dicts,
                "count": len(listing_dicts),
                "offset": offset,
            }
            if limit is not None:
                output["limit"] = limit
            print_json(output)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def listings_get(
    sku: str = typer.Argument(..., help="The SKU of the listing"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """
    Get details for a specific listing by SKU.

    Examples:
        ebay listings get MY-SKU-123
        ebay listings get MY-SKU-123 --table
    """
    try:
        client = get_client()

        listing = _get_listing_by_sku(client, sku)

        if not listing:
            print_error(f"Listing not found: {sku}")
            raise typer.Exit(1)

        if table:
            summary = [{
                "sku": listing.sku,
                "title": listing.title[:40] + "..." if len(listing.title) > 40 else listing.title,
                "price": f"{listing.price} {listing.currency}",
                "quantity": listing.quantity,
                "status": listing.status,
                "format": listing.format,
                "item_id": listing.item_id or "-",
                "offer_id": listing.offer_id or "-",
            }]
            print_table(
                summary,
                ["sku", "title", "price", "quantity", "status", "format", "item_id", "offer_id"],
                ["SKU", "Title", "Price", "Qty", "Status", "Format", "Item ID", "Offer ID"],
            )

            if listing.images:
                print(f"\nImages: {len(listing.images)}")
            if listing.url:
                print(f"URL: {listing.url}")
        else:
            print_json(listing.to_dict())

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def listings_create(
    sku: str = typer.Option(..., "--sku", "-s", help="SKU for the listing (required)"),
    template: Optional[str] = typer.Option(None, "--template", help="Template name for default values"),
    title: Optional[str] = typer.Option(None, "--title", help="Listing title"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Listing description (overrides template)"),
    description_file: Optional[str] = typer.Option(None, "--description-file", help="Read description from file (use '-' for stdin)"),
    price: Optional[str] = typer.Option(None, "--price", "-p", help="Listing price"),
    buy_it_now_price: Optional[str] = typer.Option(None, "--buy-it-now-price", help="Buy It Now price (AUCTION only)"),
    currency: Optional[str] = typer.Option(None, "--currency", help="Currency code (default: USD)"),
    quantity: Optional[int] = typer.Option(None, "--quantity", "-q", help="Available quantity"),
    category_id: Optional[str] = typer.Option(None, "--category", "-c", help="eBay category ID"),
    condition: Optional[str] = typer.Option(None, "--condition", help="Item condition (NEW, USED_GOOD, etc.)"),
    condition_descriptors: Optional[str] = typer.Option(None, "--condition-descriptors", help="Condition descriptors JSON for trading cards (e.g., '[{\"name\":\"40001\",\"values\":[\"400010\"]}]')"),
    format_type: Optional[str] = typer.Option(None, "--format", "-f", help="FIXED_PRICE or AUCTION"),
    weight: Optional[float] = typer.Option(None, "--weight", "-w", help="Package weight in pounds"),
    dimensions: Optional[str] = typer.Option(None, "--dimensions", help="Package dimensions as LxWxH in inches (e.g., 12x10x8)"),
    image: Optional[str] = typer.Option(None, "--image", "-i", help="Local image file path(s), comma-separated"),
    image_folder: Optional[str] = typer.Option(None, "--image-folder", help="Folder to scan for images"),
    image_url: Optional[str] = typer.Option(None, "--image-url", help="Remote image URL(s), comma-separated"),
    photos_album: Optional[str] = typer.Option(None, "--photos-album", help="macOS Photos app album name"),
    aspects: Optional[str] = typer.Option(None, "--aspects", help="Item specifics as JSON (e.g., '{\"Sport\": [\"Football\"]}'"),
    fulfillment_policy_id: str = typer.Option(..., "--fulfillment-policy", help="Fulfillment policy ID (required)"),
    payment_policy_id: Optional[str] = typer.Option(None, "--payment-policy", help="Payment policy ID"),
    return_policy_id: Optional[str] = typer.Option(None, "--return-policy", help="Return policy ID"),
    location_key: Optional[str] = typer.Option(None, "--location", help="Merchant location key"),
    store_category_id: Optional[str] = typer.Option(None, "--store-category-id", help="eBay store category ID (use 'ebay store categories list' to find IDs)"),
    from_json: Optional[str] = typer.Option(None, "--from-json", help="Full payload from JSON file"),
    publish: bool = typer.Option(False, "--publish", help="Publish immediately after creation"),
    table: bool = typer.Option(False, "--table", "-t", help="Display result as table"),
):
    """
    Create a new listing.

    Without --publish: Creates a pseudo-draft using a template. The listing is published
    briefly at $99,999 then immediately ended, making it visible in eBay Seller Hub for
    editing. Only --template is required.

    With --publish: Creates an active listing that stays live. Requires all API parameters
    (price, category, etc.) either from CLI options or template.

    Examples:
        ebay listings create --sku SKU123 --template lego-bulk
        ebay listings create --sku SKU123 --template vintage-camera --publish --price 149.99
        ebay listings create --sku SKU123 --title "Item" --price 99 --category 175673 --publish
    """
    photos_temp_dir = None

    try:
        client = get_client()

        # Load template if provided
        template_data = {}
        raw_template = {}
        if template:
            storage = TemplateStorage()
            template_record = storage.get_template(template)
            if not template_record:
                print_error(f"Template '{template}' not found.")
                raise typer.Exit(1)
            raw_template = template_record.get("template", {})
            template_data = _template_to_offer_payload(raw_template)
            print_info(f"Using template: {template}")

        # =================================================================
        # Pre-validation: Check ALL required eBay fields
        # =================================================================
        missing_params = []

        # Helper to check if a field is provided via CLI or template
        def has_field(cli_value, *template_paths):
            """Check if field is provided via CLI option or exists in template."""
            if cli_value:
                return True
            for path in template_paths:
                value = template_data
                for key in path.split("."):
                    if isinstance(value, dict):
                        value = value.get(key)
                    else:
                        value = None
                        break
                if value:
                    return True
                # Also check raw_template
                value = raw_template
                for key in path.split("."):
                    if isinstance(value, dict):
                        value = value.get(key)
                    else:
                        value = None
                        break
                if value:
                    return True
            return False

        # 1. Format - required
        effective_format = format_type
        if not effective_format:
            effective_format = template_data.get("format")
            if not effective_format and raw_template:
                effective_format = raw_template.get("pricing", {}).get("format") or raw_template.get("format")
        if not effective_format:
            missing_params.append("--format (AUCTION or FIXED_PRICE)")
        effective_format = effective_format or "FIXED_PRICE"

        # 2. Category - required
        if not has_field(category_id, "categoryId", "category.categoryId"):
            missing_params.append("--category")

        # 3. Fulfillment policy - always provided (required CLI arg)

        # 4. Payment policy - required
        has_payment = has_field(
            payment_policy_id,
            "listingPolicies.paymentPolicyId",
            "policies.paymentPolicyId"
        )
        if not has_payment:
            missing_params.append("--payment-policy")

        # 5. Return policy - required
        has_return = has_field(
            return_policy_id,
            "listingPolicies.returnPolicyId",
            "policies.returnPolicyId"
        )
        if not has_return:
            missing_params.append("--return-policy")

        # 6. Location - required
        if not has_field(location_key, "merchantLocationKey", "location.merchantLocationKey"):
            missing_params.append("--location")

        # 7. Title - required (can come from CLI, template, or will be built from template title config)
        # Title can be auto-generated from weight + suffix, so check for that pattern too
        has_title = bool(title)
        if not has_title and raw_template:
            title_config = raw_template.get("title", {})
            if isinstance(title_config, str) and title_config:
                has_title = True
            elif isinstance(title_config, dict):
                # Has explicit title parts
                has_title = bool(
                    title_config.get("default") or
                    title_config.get("template") or
                    title_config.get("prefix") or
                    title_config.get("base") or
                    # suffix alone is valid if weight is provided (auto-generates base)
                    (title_config.get("suffix") and weight is not None)
                )
        if not has_title:
            missing_params.append("--title")

        # 8. Description - required
        has_description = bool(description) or bool(description_file)
        if not has_description and raw_template:
            template_desc = raw_template.get("description", {})
            if isinstance(template_desc, str) and template_desc:
                has_description = True
            elif isinstance(template_desc, dict) and template_desc.get("template"):
                has_description = True
        if not has_description:
            missing_params.append("--description or --description-file")

        # 9. Price - required for --publish mode (pseudo-drafts use $99,999 placeholder)
        has_price = bool(price)
        if not has_price and template_data:
            pricing_summary = template_data.get("pricingSummary", {})
            if effective_format == "AUCTION":
                template_price = pricing_summary.get("auctionStartPrice", {})
            else:
                template_price = pricing_summary.get("price", {})
            has_price = bool(template_price.get("value"))

        if publish and not has_price:
            if effective_format == "AUCTION":
                missing_params.append("--price (auction starting price)")
            else:
                missing_params.append("--price")

        # 10. Weight - required for shipping calculation
        has_weight = weight is not None
        if not has_weight and raw_template:
            template_weight = raw_template.get("inventory", {}).get("packageWeightAndSize", {}).get("weight", {}).get("value")
            has_weight = template_weight is not None
        if not has_weight:
            missing_params.append("--weight")

        # 11. Dimensions - required for shipping calculation
        has_dimensions = dimensions is not None
        if not has_dimensions and raw_template:
            template_dims = raw_template.get("inventory", {}).get("packageWeightAndSize", {}).get("dimensions", {})
            has_dimensions = all(template_dims.get(k, {}).get("value") is not None for k in ["length", "width", "height"])
        if not has_dimensions:
            missing_params.append("--dimensions (LxWxH in inches, e.g., 12x10x8)")

        # Report all missing parameters
        if missing_params:
            print_error("Missing required parameters:")
            for param in missing_params:
                print_error(f"  - {param}")
            print_info("")
            if template:
                print_info(f"Template '{template}' does not provide these fields.")
                print_info("Either add them to the template or provide them via CLI options.")
            else:
                print_info("Provide a template with --template or specify all required options.")
            raise typer.Exit(1)

        # Without --publish: require template for pseudo-draft workflow
        if not publish and not template:
            print_error("Template required for pseudo-draft creation.")
            print_info("")
            print_info("Without --publish, a template is required to create a pseudo-draft.")
            print_info("The listing will be published at $99,999 then immediately ended,")
            print_info("making it visible in eBay Seller Hub for editing.")
            raise typer.Exit(1)

        # Collect all image paths
        all_image_paths = image or ""

        if image_folder:
            folder_images = _scan_folder_for_images(image_folder)
            if not folder_images:
                print_warning(f"No images found in folder: {image_folder}")
            else:
                print_info(f"Found {len(folder_images)} image(s) in {image_folder}")
                if all_image_paths:
                    all_image_paths += "," + ",".join(folder_images)
                else:
                    all_image_paths = ",".join(folder_images)

        if photos_album:
            print_info(f"Exporting photos from album: {photos_album}")
            try:
                album_images, photos_temp_dir = _export_photos_from_album(photos_album)
                print_info(f"Exported {len(album_images)} photo(s) from Photos app")
                if all_image_paths:
                    all_image_paths += "," + ",".join(album_images)
                else:
                    all_image_paths = ",".join(album_images)
            except RuntimeError as e:
                print_error(str(e))
                raise typer.Exit(1)

        # Build inventory item payload
        inventory_payload: dict[str, Any] = {}

        if from_json:
            with open(from_json, "r") as f:
                full_payload = json.load(f)
                inventory_payload = full_payload.get("inventory", {})

        # Apply template inventory settings (e.g., packageWeightAndSize)
        if raw_template and "inventory" in raw_template:
            template_inventory = raw_template["inventory"]
            for key, value in template_inventory.items():
                if key not in inventory_payload:
                    inventory_payload[key] = value

        # Apply --weight option to inventory packageWeightAndSize
        if weight is not None:
            if "packageWeightAndSize" not in inventory_payload:
                inventory_payload["packageWeightAndSize"] = {}
            if "weight" not in inventory_payload["packageWeightAndSize"]:
                inventory_payload["packageWeightAndSize"]["weight"] = {"unit": "POUND"}
            inventory_payload["packageWeightAndSize"]["weight"]["value"] = weight
            inventory_payload["packageWeightAndSize"]["weight"]["unit"] = "POUND"

        # Apply --dimensions option to inventory packageWeightAndSize
        if dimensions is not None:
            # Parse LxWxH format (e.g., "12x10x8")
            try:
                parts = dimensions.lower().split("x")
                if len(parts) != 3:
                    raise ValueError("Invalid format")
                length, width, height = [float(p.strip()) for p in parts]
            except (ValueError, AttributeError):
                print_error(f"Invalid dimensions format: {dimensions}")
                print_info("Use LxWxH format in inches (e.g., 12x10x8)")
                raise typer.Exit(1)

            if "packageWeightAndSize" not in inventory_payload:
                inventory_payload["packageWeightAndSize"] = {}
            inventory_payload["packageWeightAndSize"]["dimensions"] = {
                "length": length,
                "width": width,
                "height": height,
                "unit": "INCH",
            }

        # Build product section
        product: dict[str, Any] = inventory_payload.get("product", {})

        # Apply title from CLI, template, or construct from template parts
        if title:
            product["title"] = title
        elif raw_template and not product.get("title"):
            title_config = raw_template.get("title", {})
            if isinstance(title_config, dict):
                # Check for a default/template title with placeholder support
                template_title = title_config.get("default") or title_config.get("template")
                if template_title:
                    # Replace {weight} placeholder if weight is provided
                    if weight is not None and "{weight}" in template_title:
                        template_title = template_title.replace("{weight}", str(weight))
                    product["title"] = template_title
                else:
                    # Construct from prefix/suffix if present
                    prefix = title_config.get("prefix", "")
                    suffix = title_config.get("suffix", "")
                    base = title_config.get("base", "")
                    # If weight provided, include it in the base
                    if weight is not None:
                        weight_str = f"{weight}lb" if weight == int(weight) else f"{weight:.1f}lb"
                        base = f"LEGO {weight_str} Bulk Lot"
                    elif not base:
                        base = "LEGO Bulk Lot"
                    product["title"] = f"{prefix}{base} {suffix}".strip()
            elif isinstance(title_config, str):
                product["title"] = title_config

        # Resolve description: --description-file takes precedence over --description
        # Both override any template description
        resolved_description = description
        if description_file:
            if description_file == "-":
                # Read from stdin
                print_info("Reading description from stdin...")
                resolved_description = sys.stdin.read().strip()
            else:
                # Read from file
                desc_path = Path(description_file)
                if not desc_path.exists():
                    print_error(f"Description file not found: {description_file}")
                    raise typer.Exit(1)
                resolved_description = desc_path.read_text().strip()
                print_info(f"Read description from: {description_file} ({len(resolved_description)} chars)")

            # Convert plain text newlines to HTML line breaks for eBay display
            # Only apply if the description doesn't already contain HTML tags
            if resolved_description and "<br" not in resolved_description.lower() and "<p>" not in resolved_description.lower():
                resolved_description = resolved_description.replace("\n", "<br>\n")

        # Apply description from CLI option or template
        if resolved_description:
            product["description"] = resolved_description
        elif raw_template and not product.get("description"):
            # Check for description template
            template_desc = raw_template.get("description", {})
            if isinstance(template_desc, dict) and "template" in template_desc:
                product["description"] = template_desc["template"]

        # Apply item specifics from template as product aspects
        if raw_template and "itemSpecifics" in raw_template and "aspects" not in product:
            product["aspects"] = raw_template["itemSpecifics"].copy()

        # Apply CLI --aspects option (overrides/merges with template aspects)
        if aspects:
            try:
                cli_aspects = json.loads(aspects)
                if "aspects" not in product:
                    product["aspects"] = {}
                # Merge CLI aspects into product aspects (CLI takes precedence)
                product["aspects"].update(cli_aspects)
            except json.JSONDecodeError as e:
                print_error(f"Invalid JSON for --aspects: {e}")
                print_info('Example: --aspects \'{"Sport": ["Football"], "Card Condition": ["Ungraded"]}\'')
                raise typer.Exit(1)

        # Add weight to Unit Quantity item specific if provided
        if weight is not None and "aspects" in product:
            weight_str = str(int(weight)) if weight == int(weight) else str(weight)
            product["aspects"]["Unit Quantity"] = [weight_str]

        if product:
            inventory_payload["product"] = product

        # Condition: CLI option > template conditionEnum > template conditionId mapping
        if condition:
            inventory_payload["condition"] = condition.upper()
        elif raw_template:
            template_condition = raw_template.get("condition", {})
            if isinstance(template_condition, dict):
                # Prefer conditionEnum (direct API value) over conditionId
                if "conditionEnum" in template_condition:
                    inventory_payload["condition"] = template_condition["conditionEnum"]
                elif "conditionId" in template_condition:
                    cond_id = template_condition.get("conditionId")
                    inventory_payload["condition"] = CONDITION_ID_TO_ENUM.get(str(cond_id), "USED_GOOD")
                if "conditionDescription" in template_condition:
                    inventory_payload["conditionDescription"] = template_condition["conditionDescription"]

        # Condition Descriptors - required for trading cards categories (261328, 183050, 183454)
        # These are separate from item specifics and use numeric IDs
        if raw_template and "conditionDescriptors" in raw_template:
            inventory_payload["conditionDescriptors"] = raw_template["conditionDescriptors"]

        # CLI --condition-descriptors option (overrides template)
        if condition_descriptors:
            try:
                cli_cond_desc = json.loads(condition_descriptors)
                inventory_payload["conditionDescriptors"] = cli_cond_desc
            except json.JSONDecodeError as e:
                print_error(f"Invalid JSON for --condition-descriptors: {e}")
                print_info('Example: --condition-descriptors \'[{"name":"40001","values":["400010"]}]\'')
                print_info("Card Condition IDs: 400010=Near Mint, 400011=Excellent, 400012=Very Good, 400013=Poor")
                raise typer.Exit(1)

        # Availability - apply from CLI, template, or default for auctions
        effective_quantity = quantity
        if effective_quantity is None and raw_template:
            # Check template for quantity in pricing section
            template_qty = raw_template.get("pricing", {}).get("quantity")
            if template_qty is not None:
                effective_quantity = template_qty

        # For AUCTION format, default to quantity 1 if not specified
        if effective_quantity is None and effective_format == "AUCTION":
            effective_quantity = 1
            print_info("Auction format: defaulting quantity to 1")

        if effective_quantity is not None:
            inventory_payload["availability"] = {
                "shipToLocationAvailability": {"quantity": effective_quantity}
            }

        # Validate template payload against schema (catches missing required fields like weight)
        if template:
            # Build a template data structure for validation
            validation_data = raw_template.copy() if raw_template else {}
            validation_data["inventory"] = inventory_payload
            is_valid, errors = validate_template_data(validation_data)
            if not is_valid:
                print_error("Template validation failed:")
                shown_errors = set()
                for error in errors:
                    # Make error messages more user-friendly
                    if "packageWeightAndSize" in error and "weight" in error:
                        msg = "Missing required --weight option for this template"
                    else:
                        msg = error
                    if msg not in shown_errors:
                        print_error(f"  - {msg}")
                        shown_errors.add(msg)
                raise typer.Exit(1)

        # If we have images to upload, we MUST create inventory item first
        # (image upload requires an existing inventory item to attach to)
        has_images = all_image_paths or image_url

        # Ensure we have at least a condition set for inventory item creation
        if has_images and "condition" not in inventory_payload:
            inventory_payload["condition"] = "USED_GOOD"

        # Validate condition against category before creating inventory item
        effective_condition = inventory_payload.get("condition")
        effective_category = category_id or (template_data.get("categoryId") if template_data else None)
        if effective_condition and effective_category:
            _validate_condition_for_category(client, effective_condition, effective_category)

        # Create/update inventory item first (if we have data for it)
        if inventory_payload:
            print_info(f"Creating inventory item: {sku}")
            client.create_or_update_inventory_item(sku, inventory_payload)

        # Upload images if provided
        if has_images:
            print_info("Processing image uploads...")
            uploaded_urls, image_errors = _upload_images_for_listing(
                client, sku, all_image_paths if all_image_paths else None, image_url
            )
            if uploaded_urls:
                print_success(f"Uploaded {len(uploaded_urls)} image(s).")
            if image_errors:
                print_warning(f"{len(image_errors)} image(s) failed to upload.")

        # Build offer payload
        if from_json:
            with open(from_json, "r") as f:
                offer_payload = json.load(f).get("offer", {})
        else:
            offer_payload = template_data.copy()

        offer_payload["sku"] = sku
        offer_payload["marketplaceId"] = offer_payload.get("marketplaceId", "EBAY_US")
        offer_payload["format"] = format_type or offer_payload.get("format", "FIXED_PRICE")

        if offer_payload["format"] == "AUCTION":
            if "listingDuration" not in offer_payload:
                offer_payload["listingDuration"] = "DAYS_7"
            offer_payload.pop("availableQuantity", None)

        if category_id:
            offer_payload["categoryId"] = category_id

        if price:
            if "pricingSummary" not in offer_payload:
                offer_payload["pricingSummary"] = {}
            price_key = "auctionStartPrice" if offer_payload.get("format") == "AUCTION" else "price"
            offer_payload["pricingSummary"][price_key] = {
                "value": price,
                "currency": currency or "USD",
            }

        if buy_it_now_price:
            if offer_payload.get("format") != "AUCTION":
                print_warning("--buy-it-now-price is only valid for AUCTION format, ignoring")
            else:
                if "pricingSummary" not in offer_payload:
                    offer_payload["pricingSummary"] = {}
                offer_payload["pricingSummary"]["price"] = {
                    "value": buy_it_now_price,
                    "currency": currency or "USD",
                }

        # Pseudo-draft mode: no --publish flag means create at $99,999 and auto-end
        is_pseudo_draft = not publish

        if is_pseudo_draft:
            # Set pseudo-draft price ($99,999) - will be ended immediately after publish
            if "pricingSummary" not in offer_payload:
                offer_payload["pricingSummary"] = {}
            price_key = "auctionStartPrice" if offer_payload.get("format") == "AUCTION" else "price"
            offer_payload["pricingSummary"][price_key] = {
                "value": PSEUDO_DRAFT_PRICE,
                "currency": currency or "USD",
            }
            print_info(f"Creating pseudo-draft at ${PSEUDO_DRAFT_PRICE}")

        if quantity is not None and offer_payload.get("format") != "AUCTION":
            offer_payload["availableQuantity"] = quantity

        if fulfillment_policy_id or payment_policy_id or return_policy_id:
            if "listingPolicies" not in offer_payload:
                offer_payload["listingPolicies"] = {}
            if fulfillment_policy_id:
                offer_payload["listingPolicies"]["fulfillmentPolicyId"] = fulfillment_policy_id
            if payment_policy_id:
                offer_payload["listingPolicies"]["paymentPolicyId"] = payment_policy_id
            if return_policy_id:
                offer_payload["listingPolicies"]["returnPolicyId"] = return_policy_id

        if location_key:
            offer_payload["merchantLocationKey"] = location_key

        # Resolve store category ID to category name for storeCategoryNames
        if store_category_id:
            print_info(f"Resolving store category ID: {store_category_id}")
            try:
                store_result = client.get_store_categories()
                store_cats = store_result.get("storeCategories", [])

                def _find_category_name(cats, target_id, parent_path=""):
                    """Recursively find category name by ID."""
                    for cat in cats:
                        cat_name = cat.get("categoryName", "")
                        cat_id = cat.get("categoryId", "")
                        if str(cat_id) == str(target_id):
                            return cat_name
                        children = cat.get("childrenCategories", [])
                        if children:
                            found = _find_category_name(children, target_id)
                            if found:
                                return found
                    return None

                resolved_name = _find_category_name(store_cats, store_category_id)
                if resolved_name:
                    offer_payload["storeCategoryNames"] = [resolved_name]
                    print_info(f"Store category: {resolved_name}")
                else:
                    print_warning(f"Store category ID {store_category_id} not found. Skipping store category assignment.")
            except ClientError as e:
                print_warning(f"Could not resolve store category: {e}")

        # Create offer
        print_info("Creating offer...")
        result = client.create_offer(offer_payload)
        offer_id = result.get("offerId")

        print_success(f"Listing created: SKU={sku}, Offer ID={offer_id}")

        # Track draft locally for fast retrieval
        draft_storage = DraftStorage()
        draft_storage.add_draft(sku, offer_id)

        # Always publish to get an item ID (required for Seller Hub visibility)
        # Pre-validation for auction listings
        if effective_format == "AUCTION":
            try:
                inv_item = client.get_inventory_item(sku)
                avail = inv_item.get("availability", {})
                ship_avail = avail.get("shipToLocationAvailability", {})
                inv_qty = ship_avail.get("quantity", 0)
                if inv_qty < 1:
                    print_error("Auction listings require quantity >= 1 on the inventory item.")
                    print_info("The inventory item has shipToLocationAvailability.quantity = 0")
                    print_info("This is required by eBay for auction format listings.")
                    raise typer.Exit(1)
            except ClientError:
                pass  # If we can't fetch, let the publish call handle the error

        print_info("Publishing listing...")
        pub_result = client.publish_offer(offer_id)
        item_id = pub_result.get("listingId")
        url = f"https://www.ebay.com/itm/{item_id}"
        print_success(f"Published! Listing ID: {item_id}")

        # For pseudo-drafts, immediately end the listing so it appears in Seller Hub as ended
        if is_pseudo_draft:
            print_info("Ending pseudo-draft listing...")
            client.withdraw_offer(offer_id)
            final_status = "ended"
            print_success("Listing ended. Edit in eBay Seller Hub to set price and relist.")
            print_info(f"Edit listing: {url}")
        else:
            final_status = "active"
            print_info(f"View listing: {url}")
            # Remove from draft tracking since it's now active
            draft_storage.remove_draft(sku)

        if table:
            summary = [{
                "sku": sku,
                "offer_id": offer_id,
                "status": final_status,
                "item_id": item_id or "-",
                "template": template or "-",
            }]
            print_table(
                summary,
                ["sku", "offer_id", "status", "item_id", "template"],
                ["SKU", "Offer ID", "Status", "Item ID", "Template"],
            )
        else:
            output = {
                "sku": sku,
                "offer_id": offer_id,
                "status": final_status,
                "item_id": item_id,
                "url": url,
            }
            if template:
                output["template_used"] = template
            print_json(output)

    except Exception as e:
        raise typer.Exit(handle_error(e))

    finally:
        if photos_temp_dir and Path(photos_temp_dir).exists():
            shutil.rmtree(photos_temp_dir, ignore_errors=True)


@app.command("update")
def listings_update(
    sku: str = typer.Argument(..., help="SKU of the listing to update"),
    title: Optional[str] = typer.Option(None, "--title", help="Update title"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="Update description"),
    price: Optional[str] = typer.Option(None, "--price", "-p", help="Update price"),
    currency: Optional[str] = typer.Option(None, "--currency", help="Update currency"),
    quantity: Optional[int] = typer.Option(None, "--quantity", "-q", help="Update quantity"),
    category_id: Optional[str] = typer.Option(None, "--category", "-c", help="Update category ID"),
    condition: Optional[str] = typer.Option(None, "--condition", help="Update condition"),
    fulfillment_policy_id: Optional[str] = typer.Option(None, "--fulfillment-policy", help="Update fulfillment policy"),
    payment_policy_id: Optional[str] = typer.Option(None, "--payment-policy", help="Update payment policy"),
    return_policy_id: Optional[str] = typer.Option(None, "--return-policy", help="Update return policy"),
    location_key: Optional[str] = typer.Option(None, "--location", help="Update location"),
    from_json: Optional[str] = typer.Option(None, "--from-json", help="Updates from JSON file"),
    table: bool = typer.Option(False, "--table", "-t", help="Display result as table"),
):
    """
    Update an existing listing.

    Updates both the inventory item and offer as needed.

    Examples:
        ebay listings update SKU123 --price 39.99
        ebay listings update SKU123 --quantity 5
        ebay listings update SKU123 --title "New Title" --price 29.99
    """
    try:
        client = get_client()

        # Get current listing
        listing = _get_listing_by_sku(client, sku)
        if not listing:
            print_error(f"Listing not found: {sku}")
            raise typer.Exit(1)

        if not listing.offer_id:
            print_error(f"Cannot update legacy listing (no offer ID): {sku}")
            raise typer.Exit(1)

        # Track if we need to update inventory item or offer
        update_inventory = False
        update_offer = False

        # Update inventory item
        try:
            current_inventory = client.get_inventory_item(sku)
        except Exception:
            current_inventory = {}

        inventory_payload = current_inventory.copy()
        for field in ["sku", "locale", "groupIds", "inventoryItemGroupKeys"]:
            inventory_payload.pop(field, None)

        if title or description:
            if "product" not in inventory_payload:
                inventory_payload["product"] = {}
            if title:
                inventory_payload["product"]["title"] = title
                update_inventory = True
            if description:
                inventory_payload["product"]["description"] = description
                update_inventory = True

        if condition:
            # Validate condition against category before updating
            effective_category = category_id or listing.category_id
            if effective_category:
                _validate_condition_for_category(client, condition, effective_category)
            inventory_payload["condition"] = condition.upper()
            update_inventory = True

        if update_inventory:
            print_info("Updating inventory item...")
            client.create_or_update_inventory_item(sku, inventory_payload)

        # Update offer
        current_offer = client.get_offer(listing.offer_id)
        offer_payload = current_offer.copy()
        for field in ["offerId", "status", "listing", "sku", "marketplaceId", "format"]:
            offer_payload.pop(field, None)

        if price or currency:
            if "pricingSummary" not in offer_payload:
                offer_payload["pricingSummary"] = current_offer.get("pricingSummary", {})
            if "price" not in offer_payload["pricingSummary"]:
                offer_payload["pricingSummary"]["price"] = current_offer.get("pricingSummary", {}).get("price", {})
            if price:
                offer_payload["pricingSummary"]["price"]["value"] = price
                update_offer = True
            if currency:
                offer_payload["pricingSummary"]["price"]["currency"] = currency
                update_offer = True

        if quantity is not None:
            offer_payload["availableQuantity"] = quantity
            update_offer = True

        if category_id:
            offer_payload["categoryId"] = category_id
            update_offer = True

        if fulfillment_policy_id or payment_policy_id or return_policy_id:
            if "listingPolicies" not in offer_payload:
                offer_payload["listingPolicies"] = current_offer.get("listingPolicies", {})
            if fulfillment_policy_id:
                offer_payload["listingPolicies"]["fulfillmentPolicyId"] = fulfillment_policy_id
                update_offer = True
            if payment_policy_id:
                offer_payload["listingPolicies"]["paymentPolicyId"] = payment_policy_id
                update_offer = True
            if return_policy_id:
                offer_payload["listingPolicies"]["returnPolicyId"] = return_policy_id
                update_offer = True

        if location_key:
            offer_payload["merchantLocationKey"] = location_key
            update_offer = True

        if from_json:
            with open(from_json, "r") as f:
                updates = json.load(f)
                offer_payload.update(updates)
                update_offer = True

        if update_offer:
            print_info("Updating offer...")
            client.update_offer(listing.offer_id, offer_payload)

        if not update_inventory and not update_offer:
            print_warning("No updates provided.")
            return

        print_success(f"Listing updated: {sku}")

        # Fetch and display updated listing
        updated = _get_listing_by_sku(client, sku)
        if updated:
            if table:
                summary = [{
                    "sku": updated.sku,
                    "title": updated.title[:40] + "..." if len(updated.title) > 40 else updated.title,
                    "price": f"{updated.price} {updated.currency}",
                    "quantity": updated.quantity,
                    "status": updated.status,
                }]
                print_table(
                    summary,
                    ["sku", "title", "price", "quantity", "status"],
                    ["SKU", "Title", "Price", "Qty", "Status"],
                )
            else:
                print_json(updated.to_dict())

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def listings_delete(
    sku: str = typer.Argument(..., help="SKU of the listing to delete"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
    keep_inventory: bool = typer.Option(False, "--keep-inventory", help="Keep inventory item, only delete offer"),
):
    """
    Delete a listing.

    If the listing is active, it will be withdrawn first. Then the offer is deleted.
    Optionally keep the inventory item for reuse.

    Examples:
        ebay listings delete SKU123
        ebay listings delete SKU123 --force
        ebay listings delete SKU123 --keep-inventory
    """
    try:
        client = get_client()

        listing = _get_listing_by_sku(client, sku)
        if not listing:
            print_error(f"Listing not found: {sku}")
            raise typer.Exit(1)

        if not listing.offer_id:
            print_error(f"Cannot delete legacy listing (no offer ID): {sku}")
            print_info("Use eBay Seller Hub to manage legacy listings.")
            raise typer.Exit(1)

        if not force:
            status_msg = f"ACTIVE (will be withdrawn)" if listing.is_active else "DRAFT"
            if not typer.confirm(f"Delete listing '{listing.title}' ({status_msg})?"):
                print_info("Deletion cancelled.")
                raise typer.Exit(0)

        # Withdraw if active
        if listing.is_active:
            print_info("Withdrawing active listing...")
            client.withdraw_offer(listing.offer_id)
            print_success("Listing withdrawn.")

        # Delete offer
        print_info("Deleting offer...")
        client.delete_offer(listing.offer_id)
        print_success(f"Offer deleted: {listing.offer_id}")

        # Delete inventory item unless --keep-inventory
        if not keep_inventory:
            try:
                print_info("Deleting inventory item...")
                client.delete_inventory_item(sku)
                print_success(f"Inventory item deleted: {sku}")
            except Exception as e:
                print_warning(f"Could not delete inventory item: {e}")
        else:
            print_info("Inventory item kept (--keep-inventory).")

        # Remove from draft tracking
        DraftStorage().remove_draft(sku)

        print_success(f"Listing deleted: {sku}")

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("publish")
def listings_publish(
    sku: str = typer.Argument(..., help="SKU of the listing to publish"),
    price: Optional[str] = typer.Option(None, "--price", "-p", help="Set final price (required for pseudo-drafts)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display result as table"),
):
    """
    Publish a draft listing or set final price on a pseudo-draft.

    For real drafts: Publishes the listing to make it live on eBay.
    For pseudo-drafts: Use --price to set the final price (required).

    Examples:
        ebay listings publish SKU123                  # Publish real draft
        ebay listings publish SKU123 --price 29.99   # Set price on pseudo-draft
    """
    try:
        client = get_client()

        listing = _get_listing_by_sku(client, sku)
        if not listing:
            print_error(f"Listing not found: {sku}")
            raise typer.Exit(1)

        if not listing.offer_id:
            print_error(f"Cannot publish legacy listing (no offer ID): {sku}")
            raise typer.Exit(1)

        if listing.is_active:
            # Check if it's a pseudo-draft that needs a real price
            if listing.is_pseudo_draft:
                if not price:
                    print_error(f"Listing is a pseudo-draft at ${listing.price}.")
                    print_info("Specify the final price with --price to publish at the real price.")
                    print_info("Example: ebay listings publish " + sku + " --price 29.99")
                    raise typer.Exit(1)
                # Update the price to the real price
                print_info(f"Setting price from ${listing.price} to ${price}")
                offer_payload = {"pricingSummary": {}}
                price_key = "auctionStartPrice" if listing.format.value == "auction" else "price"
                offer_payload["pricingSummary"][price_key] = {
                    "value": price,
                    "currency": listing.currency,
                }
                client.update_offer(listing.offer_id, offer_payload)
                print_success(f"Published! Price set to ${price}")
                if listing.url:
                    print_info(f"View listing: {listing.url}")
                # Output
                if table:
                    summary = [{
                        "sku": sku,
                        "item_id": listing.item_id,
                        "price": price,
                        "status": "active",
                        "url": listing.url or "-",
                    }]
                    print_table(
                        summary,
                        ["sku", "item_id", "price", "status", "url"],
                        ["SKU", "Item ID", "Price", "Status", "URL"],
                    )
                else:
                    print_json({
                        "sku": sku,
                        "offer_id": listing.offer_id,
                        "item_id": listing.item_id,
                        "price": price,
                        "status": "active",
                        "url": listing.url,
                    })
                return
            else:
                # Regular active listing - already published
                print_warning(f"Listing is already active: {sku}")
                if listing.url:
                    print_info(f"View listing: {listing.url}")
                raise typer.Exit(0)

        print_info(f"Publishing listing: {sku}")
        result = client.publish_offer(listing.offer_id)

        item_id = result.get("listingId")
        url = f"https://www.ebay.com/itm/{item_id}"

        # Remove from draft tracking
        DraftStorage().remove_draft(sku)

        print_success(f"Published! Listing ID: {item_id}")
        print_info(f"View listing: {url}")

        if table:
            summary = [{
                "sku": sku,
                "item_id": item_id,
                "status": "active",
                "url": url,
            }]
            print_table(
                summary,
                ["sku", "item_id", "status", "url"],
                ["SKU", "Item ID", "Status", "URL"],
            )
        else:
            print_json({
                "sku": sku,
                "offer_id": listing.offer_id,
                "item_id": item_id,
                "status": "active",
                "url": url,
            })

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("unpublish")
def listings_unpublish(
    sku: str = typer.Argument(..., help="SKU of the listing to unpublish"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
    table: bool = typer.Option(False, "--table", "-t", help="Display result as table"),
):
    """
    Unpublish (withdraw) an active listing back to draft status.

    The listing can be republished later.

    Examples:
        ebay listings unpublish SKU123
        ebay listings unpublish SKU123 --force
    """
    try:
        client = get_client()

        listing = _get_listing_by_sku(client, sku)
        if not listing:
            print_error(f"Listing not found: {sku}")
            raise typer.Exit(1)

        if not listing.offer_id:
            print_error(f"Cannot unpublish legacy listing (no offer ID): {sku}")
            raise typer.Exit(1)

        if listing.is_draft:
            print_warning(f"Listing is already a draft: {sku}")
            raise typer.Exit(0)

        if not force:
            if not typer.confirm(f"Unpublish '{listing.title}'? This will end the live listing."):
                print_info("Unpublish cancelled.")
                raise typer.Exit(0)

        print_info(f"Unpublishing listing: {sku}")
        client.withdraw_offer(listing.offer_id)

        print_success(f"Listing unpublished: {sku}")
        print_info("The listing is now a draft and can be republished later.")

        if table:
            summary = [{
                "sku": sku,
                "offer_id": listing.offer_id,
                "status": "draft",
            }]
            print_table(
                summary,
                ["sku", "offer_id", "status"],
                ["SKU", "Offer ID", "Status"],
            )
        else:
            print_json({
                "sku": sku,
                "offer_id": listing.offer_id,
                "status": "draft",
            })

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("preview")
def listings_preview(
    sku: str = typer.Argument(..., help="SKU of the listing to preview"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Save HTML to file instead of opening browser"),
):
    """
    Generate a visual preview of a listing before publishing.

    Opens an HTML preview in your browser showing how the listing will appear.

    Examples:
        ebay listings preview SKU123
        ebay listings preview SKU123 --output preview.html
    """
    try:
        client = get_client()

        listing = _get_listing_by_sku(client, sku)
        if not listing:
            print_error(f"Listing not found: {sku}")
            raise typer.Exit(1)

        print_info("Generating preview...")
        html = _generate_preview_html(listing)

        if output:
            Path(output).write_text(html)
            print_success(f"Preview saved to: {output}")
        else:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
                f.write(html)
                temp_path = f.name

            print_info("Opening preview in browser...")
            webbrowser.open(f"file://{temp_path}")

            if listing.is_draft:
                print_success(f"Preview opened. To publish this listing, run:")
                typer.echo(f"  ebay listings publish {sku}")
            else:
                print_success("Preview opened.")
                if listing.url:
                    print_info(f"Live listing: {listing.url}")

    except Exception as e:
        raise typer.Exit(handle_error(e))
