# Plan: Unified Listings Command

## Summary
Replace the separate `offers` and `listings` command groups with a single `listings` command that abstracts away eBay's Inventory API, Offer API, and Trading API complexity.

## Why This Approach
- **Simplest user experience**: Users don't need to understand eBay's internal API distinctions
- **Single command group**: `listings` handles drafts (via Inventory/Offer API) and active listings (via Trading API)
- **Minimal file changes**: Create 2 new files, modify 1, delete 1

## Discovery Summary

### Files to Create
1. `ebay_cli/models.py` - Listing and Image dataclasses

### Files to Modify
1. `ebay_cli/commands/listings.py` - Complete rewrite with new commands
2. `ebay_cli/main.py` - Remove offers command group (line 18)

### Files to Delete
1. `ebay_cli/commands/offers.py` - Replaced by listings.py

### Existing Client Methods (Verified)
**Inventory API** (client.py lines 521-598):
- `get_inventory_items(limit, offset)` → dict with "inventoryItems"
- `get_inventory_item(sku)` → inventory item dict
- `create_or_update_inventory_item(sku, payload)` → creates/updates
- `delete_inventory_item(sku)` → deletes

**Offer API** (client.py lines 706-814):
- `get_offers(sku, limit, offset)` → dict with "offers"
- `get_offer(offer_id)` → offer dict
- `create_offer(payload)` → {"offerId": ...}
- `update_offer(offer_id, payload)` → updates
- `delete_offer(offer_id)` → deletes
- `publish_offer(offer_id)` → {"listingId": ...}
- `withdraw_offer(offer_id)` → withdraws

**Trading API** (client.py lines 1225-1334):
- `get_seller_list(entries_per_page, page_number)` → XML string

**Media API** (client.py lines 816-1026):
- `upload_image_from_file(path)` → {"image_id", "imageUrl", "expirationDate"}
- `upload_image_from_url(url)` → same

---

## Models

### Image Model
```python
@dataclass
class Image:
    url: str                    # eBay-hosted image URL
    thumbnail_url: str | None   # Thumbnail version (if available)
    position: int               # Order (0-indexed)
    source: str | None          # "local_file", "url", "photos_album"
    original_path: str | None   # Original file path or URL
```

### Listing Model
```python
@dataclass
class Listing:
    # Identifiers
    sku: str                    # PRIMARY KEY
    offer_id: str | None        # Inventory API offer ID
    item_id: str | None         # eBay listing ID (null for drafts)

    # Core details
    title: str
    description: str | None
    price: str
    currency: str
    quantity: int
    quantity_sold: int

    # Status & format
    status: str                 # "active" or "draft"
    format: str                 # "fixed_price" or "auction"

    # Classification
    category_id: str | None
    condition: str | None

    # Media
    images: list[Image]

    # Policies
    fulfillment_policy_id: str | None
    payment_policy_id: str | None
    return_policy_id: str | None

    # Location
    location_id: str | None

    # eBay URL
    url: str | None
```

---

## Commands

### 1. `listings list`
**Purpose**: List all listings (active + drafts)

**Algorithm**:
1. Fetch active listings via Trading API (`get_seller_list`)
2. Fetch all offers via Inventory API (`get_offers` with no SKU filter)
3. Merge by SKU:
   - If offer exists with PUBLISHED status → status="active" (use Trading API data for sold qty, url)
   - If offer exists with UNPUBLISHED status → status="draft"
   - If Trading API listing has no matching offer → status="active", offer_id=null (legacy)
4. Convert to Listing models
5. Output as JSON or table

**Options**:
- `--limit/-l` - Max results (default 100)
- `--offset/-o` - Pagination offset
- `--status/-s` - Filter: "active", "draft", or "all" (default: all)
- `--properties/-p` - Field filtering

### 2. `listings get <sku>`
**Purpose**: Get single listing by SKU

**Algorithm**:
1. Try to get inventory item by SKU
2. Try to get offers for that SKU
3. If offer is PUBLISHED, also fetch from Trading API for additional data
4. Merge into single Listing model
5. Output as JSON or table

**Options**:

### 3. `listings create`
**Purpose**: Create a draft listing (optionally publish immediately)

**Algorithm**:
1. Load template if `--template` specified
2. Create inventory item with SKU, title, description, condition, images
3. Create offer linked to inventory item
4. If `--publish` flag, call `publish_offer`
5. Return created Listing

**Options** (from existing offers create):
- `--sku/-s` (required)
- `--template` - Load defaults from template
- `--title` - Listing title
- `--description/-d` - Description
- `--price/-p` - Price
- `--currency` - Currency (default USD)
- `--quantity/-q` - Quantity
- `--category/-c` - Category ID
- `--condition` - Condition (NEW, USED_GOOD, etc.)
- `--format/-f` - FIXED_PRICE or AUCTION
- `--image` - Local file paths (comma-separated)
- `--image-folder` - Folder to scan for images
- `--image-url` - Remote URLs (comma-separated)
- `--photos-album` - macOS Photos album
- `--fulfillment-policy` - Policy ID
- `--payment-policy` - Policy ID
- `--return-policy` - Policy ID
- `--location` - Location key
- `--from-json` - Full payload from JSON file
- `--publish` - Publish immediately after creation

### 4. `listings update <sku>`
**Purpose**: Update existing listing

**Algorithm**:
1. Fetch current inventory item and offer by SKU
2. Apply updates to inventory item (title, description, images, condition)
3. Apply updates to offer (price, quantity, policies)
4. Save both
5. Return updated Listing

**Options**:
- `--title` - Update title
- `--description/-d` - Update description
- `--price/-p` - Update price
- `--currency` - Update currency
- `--quantity/-q` - Update quantity
- `--category/-c` - Update category
- `--condition` - Update condition
- `--fulfillment-policy` - Update policy
- `--payment-policy` - Update policy
- `--return-policy` - Update policy
- `--location` - Update location
- `--from-json` - Updates from JSON file

### 5. `listings delete <sku>`
**Purpose**: Withdraw (if active) and delete listing

**Algorithm**:
1. Fetch offers for SKU
2. If offer status is PUBLISHED, call `withdraw_offer` first
3. Delete the offer
4. Optionally delete the inventory item (ask or use --keep-inventory flag)

**Options**:
- `--force/-f` - Skip confirmation
- `--keep-inventory` - Don't delete the inventory item, only the offer

### 6. `listings publish <sku>`
**Purpose**: Publish a draft listing

**Algorithm**:
1. Fetch offer for SKU
2. Verify status is UNPUBLISHED
3. Call `publish_offer`
4. Return updated Listing with item_id and url

**Options**:

### 7. `listings unpublish <sku>`
**Purpose**: Withdraw an active listing back to draft

**Algorithm**:
1. Fetch offer for SKU
2. Verify status is PUBLISHED
3. Call `withdraw_offer`
4. Return updated Listing

**Options**:
- `--force/-f` - Skip confirmation

### 8. `listings preview <sku>`
**Purpose**: Preview a draft before publishing

**Algorithm**:
1. Fetch offer and inventory item for SKU
2. Generate HTML preview (reuse `_generate_preview_html` from offers.py)
3. Open in browser or save to file

**Options**:
- `--output/-o` - Save to file instead of opening browser

---

## Implementation Steps

### Step 1: Create models.py
Create `<cli-tools-root>/ebay/ebay_cli/models.py` with:
- `Image` dataclass
- `Listing` dataclass
- Helper functions: `listing_to_dict()`, `dict_to_listing()`

### Step 2: Rewrite listings.py
Replace `<cli-tools-root>/ebay/ebay_cli/commands/listings.py` with:
- Import models
- Helper functions for API data merging
- All 8 commands (list, get, create, update, delete, publish, unpublish, preview)
- Preserve image upload logic from offers.py
- Preserve template support from offers.py
- Preserve HTML preview generation from offers.py

──────────────────────────
🧪 CHECKPOINT: Verify list and get commands
   - Run: `ebay listings list --limit 5`
   - Expected: Both commands show merged data with status field
──────────────────────────

### Step 3: Add create command
Add `listings create` command with:
- Template support
- Image upload support (folder, files, URLs, Photos album)
- --publish flag for immediate publishing

### Step 4: Add update command
Add `listings update` command with:
- Partial update support
- Updates both inventory item and offer as needed

──────────────────────────
🧪 CHECKPOINT: Verify create and update
   - Run: `ebay listings create --sku TEST-SKU --title "Test" --price 9.99 --category 175673`
   - Run: `ebay listings update TEST-SKU --price 19.99`
   - Run: `ebay listings get TEST-SKU`
   - Expected: Draft listing created, price updated
──────────────────────────

### Step 5: Add delete, publish, unpublish commands
Add remaining lifecycle commands:
- `delete` with withdraw-first logic
- `publish` to make draft live
- `unpublish` to withdraw active listing

### Step 6: Add preview command
Port the preview HTML generation from offers.py

──────────────────────────
🧪 CHECKPOINT: Full command test
   - Run: `ebay listings list --status draft`
   - Run: `ebay listings preview TEST-SKU`
   - Run: `ebay listings delete TEST-SKU --force`
   - Expected: All commands work correctly
──────────────────────────

### Step 7: Update main.py
Edit `<cli-tools-root>/ebay/ebay_cli/main.py`:
- Remove line 18: `app.add_typer(offers.app, name="offers")`
- Remove the offers import

### Step 8: Delete offers.py
Delete `<cli-tools-root>/ebay/ebay_cli/commands/offers.py`

### Step 9: Update README.md
Update documentation to reflect new unified listings command

──────────────────────────
🧪 FINAL CHECKPOINT: Full integration test
   - Run: `ebay listings --help`
   - Run: `ebay offers --help` (should fail - command removed)
   - Run full create → publish → unpublish → delete flow
   - Expected: All commands work, offers command is gone
──────────────────────────

---

## What's NOT Included (Intentionally)
- Variation/multi-SKU support (user said skip entirely)
- Category name lookup (deferred - just use category_id)
- Location name lookup (deferred - just use location_id)
- Backwards compatibility alias for `offers` command (user said remove entirely)

---

## File Changes Summary

| File | Action | Lines Changed |
|------|--------|---------------|
| `ebay_cli/models.py` | CREATE | ~80 lines |
| `ebay_cli/commands/listings.py` | REWRITE | ~800 lines |
| `ebay_cli/main.py` | MODIFY | -2 lines |
| `ebay_cli/commands/offers.py` | DELETE | -1035 lines |
| `README.md` | MODIFY | Update docs |

**Net change**: Approximately same LOC, but much cleaner user experience.
