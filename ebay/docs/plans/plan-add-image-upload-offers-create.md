# Implementation Plan: Image Upload Support for `offers create` Command

## One-Line Summary

Add `--image` and `--image-url` options to `ebay offers create` to upload images and associate them with the listing.

## Why This Approach

This is the simplest solution because:
1. **Uses existing infrastructure** - All upload methods already exist in `client.py`
2. **Single file modification** - Only `offers.py` needs code changes (plus README)
3. **No new dependencies** - Reuses `ImageStorage`, `Path`, and existing client methods
4. **Follows established patterns** - Matches how `images upload` command works

## Discovery Summary

### Files Read:
- `ebay_cli/commands/offers.py` - Target file for modification (lines 69-168 for offers_create)
- `ebay_cli/commands/images.py` - Pattern for image upload with storage (lines 54-107)
- `ebay_cli/commands/inventory.py` - Shows how to update inventory item imageUrls
- `ebay_cli/client.py` - Has `upload_image_from_file()` (710-801), `upload_image_from_url()` (803-865), `create_or_update_inventory_item()` (556)
- `ebay_cli/storage.py` - `ImageStorage` class for local persistence

### APIs Verified:
- eBay Media API `createImageFromUrl` - Returns `{image_id, imageUrl, expirationDate}`
- eBay Inventory API - Images stored at `product.imageUrls` (up to 12 per item)
- Existing client methods tested and working

### Integration Points:
- `client.upload_image_from_file(path)` → returns `{image_id, imageUrl, expirationDate}`
- `client.upload_image_from_url(url)` → returns `{image_id, imageUrl, expirationDate}`
- `client.get_inventory_item(sku)` → returns inventory item with `product.imageUrls`
- `client.create_or_update_inventory_item(sku, payload)` → updates inventory item
- `ImageStorage.add_image(...)` → persists to `~/.ebay/images.json`

## The Plan

### Step 1: Add Import
**File:** `ebay_cli/commands/offers.py`
**Line:** After line 8 (after existing imports)
**Change:** Add `from pathlib import Path`

### Step 2: Add Helper Function
**File:** `ebay_cli/commands/offers.py`
**Location:** Insert before line 69 (before `@app.command("create")`)
**Change:** Add `_upload_images_for_offer()` function that:
- Parses comma-separated image paths and URLs
- Uploads each via existing client methods
- Stores in `ImageStorage` for reference
- Updates inventory item's `product.imageUrls`
- Returns `(uploaded_urls, errors)` tuple
- Continues with warnings on failures (doesn't abort)

### Step 3: Add CLI Options
**File:** `ebay_cli/commands/offers.py`
**Lines:** After line 82 (after `location_key`), before `from_json`
**Change:** Add two new options:
```python
image: Optional[str] = typer.Option(
    None, "--image", "-i",
    help="Local image file path(s) to upload (comma-separated for multiple)"
),
image_url: Optional[str] = typer.Option(
    None, "--image-url",
    help="External image URL(s) to upload (comma-separated for multiple)"
),
```

### Step 4: Update Docstring
**File:** `ebay_cli/commands/offers.py`
**Lines:** 86-97
**Change:** Expand docstring to document image options with examples

### Step 5: Add Image Processing Call
**File:** `ebay_cli/commands/offers.py`
**Location:** After line 99 (`client = get_client()`), before JSON loading
**Change:** Add call to `_upload_images_for_offer()` if `--image` or `--image-url` provided

### Step 6: Update Output
**File:** `ebay_cli/commands/offers.py`
**Lines:** Around 151-165
**Change:** Include image upload results in both table and JSON output

──────────────────────────
🧪 CHECKPOINT: Test basic functionality
   - Run: `ebay offers create --help` (verify new options appear)
   - Run: `ebay offers create --sku TEST --category 1 --price 1 --image /tmp/test.jpg` (with test image)
   - Expected: Options visible, image upload attempted
──────────────────────────

### Step 7: Update README
**File:** `README.md`
**Change:** Add documentation for new `--image` and `--image-url` options with examples

## The Todo List

1. Add Path import to offers.py
2. Add _upload_images_for_offer helper function
3. Add --image and --image-url options to offers_create
4. Update offers_create docstring with image examples
5. Add image processing logic after get_client()
6. Update output to include image upload results
7. Update README.md with new image options
8. Test: offers create with --image local file
9. Test: offers create with --image-url remote URL
10. Test: offers create with both options mixed

## Complexity Avoided

1. **No new files** - Everything in existing offers.py
2. **No new client methods** - Reuse existing upload methods
3. **No complex error handling** - Simple continue-on-failure with warnings
4. **No image validation** - Let eBay API handle format validation
5. **No async/parallel uploads** - Sequential is simpler and sufficient
6. **No Trading API** - Use modern Media API (existing infrastructure)

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Continue on upload failure | User requirement - don't abort entire operation |
| New images prepended to existing | Newly uploaded images appear first in listing |
| 12 image limit enforcement | eBay's limit for inventory items |
| Both options usable together | User requirement - mixed sources allowed |
| Store in ImageStorage | Consistency with `images upload` command |
| No validation beyond file exists | Let eBay API reject invalid formats |

## Error Handling

| Scenario | Behavior |
|----------|----------|
| File not found | Warning, skip, continue |
| URL upload fails | Warning, skip, continue |
| All uploads fail | Proceed with offer (no images) |
| Inventory item missing | Error - SKU must exist |
| Inventory update fails | Warning, images uploaded but not associated |
| Over 12 images | Warning, first 12 processed |
