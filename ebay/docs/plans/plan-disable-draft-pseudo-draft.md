# Implementation Plan: Pseudo-Draft Listings

## Summary
eBay draft listings created via the API don't appear in eBay Seller Hub UI, making them unusable. This plan implements "pseudo-drafts" - published listings with a sentinel price of $99,999 that appear in the UI and can be edited there.

## Why This Approach
- **Simplest solution**: Uses existing publish/update infrastructure, no new commands needed
- **Visible in eBay UI**: Published listings (even at high prices) appear in Seller Hub
- **Backward compatible**: Real drafts still work for users who have them
- **Minimal code changes**: ~80 lines of modifications across 2 files

## What's NOT Included
- Configuration for sentinel price (hardcoded $99,999)
- Local storage of "intended prices" (users manage this themselves)
- Migration of existing real drafts

## Prerequisites
- None - uses existing eBay API infrastructure

## Implementation Steps

### Step 1: Add PSEUDO_DRAFT_PRICE constant to Listing model
**File:** `<cli-tools-root>/ebay/ebay_cli/models/listing.py`
**Location:** After line 14 (after `from .image import Image`)
**Current code:**
```python
from .image import Image


class ListingStatus(str, Enum):
```
**Action:** Add constant between import and class:
```python
from .image import Image

# Sentinel price for pseudo-draft listings (appear in eBay UI as editable published listings)
PSEUDO_DRAFT_PRICE = "99999.00"


class ListingStatus(str, Enum):
```
**Verify:** `python -c "from ebay_cli.models.listing import PSEUDO_DRAFT_PRICE; print(PSEUDO_DRAFT_PRICE)"`

---

### Step 2: Add is_pseudo_draft property to Listing class
**File:** `<cli-tools-root>/ebay/ebay_cli/models/listing.py`
**Location:** After line 141 (after `is_unsold` property)
**Current code:**
```python
    @property
    def is_unsold(self) -> bool:
        """Check if listing is unsold (ended without sale)."""
        return self.status == ListingStatus.UNSOLD


def is_valid_sku(sku: str) -> bool:
```
**Action:** Add new property before `is_valid_sku` function:
```python
    @property
    def is_unsold(self) -> bool:
        """Check if listing is unsold (ended without sale)."""
        return self.status == ListingStatus.UNSOLD

    @property
    def is_pseudo_draft(self) -> bool:
        """Check if listing is a pseudo-draft (active but at sentinel price $99,999)."""
        return self.is_active and self.price == PSEUDO_DRAFT_PRICE


def is_valid_sku(sku: str) -> bool:
```
**Verify:** `python -c "from ebay_cli.models.listing import Listing, ListingStatus; l = Listing(sku='TEST', status=ListingStatus.ACTIVE, price='99999.00'); print(l.is_pseudo_draft)"`
Expected: `True`

---

### Step 3: Import PSEUDO_DRAFT_PRICE in listings.py
**File:** `<cli-tools-root>/ebay/ebay_cli/commands/listings.py`
**Location:** Lines 28-36 (model imports)
**Current code:**
```python
from ..models import (
    Listing,
    ListingStatus,
    Image,
    is_valid_sku,
    listing_from_offer,
    listing_from_trading_api,
    merge_listing_data,
)
```
**Action:** Add PSEUDO_DRAFT_PRICE to imports:
```python
from ..models import (
    Listing,
    ListingStatus,
    Image,
    is_valid_sku,
    listing_from_offer,
    listing_from_trading_api,
    merge_listing_data,
    PSEUDO_DRAFT_PRICE,
)
```
**Verify:** `python -c "from ebay_cli.commands.listings import PSEUDO_DRAFT_PRICE; print(PSEUDO_DRAFT_PRICE)"`

---

### Step 4: Require --publish flag in listings_create
**File:** `<cli-tools-root>/ebay/ebay_cli/commands/listings.py`
**Location:** After line 1066 (after the `raise typer.Exit(1)` for missing_params)
**Current code at lines 1060-1069:**
```python
        if missing_params:
            print_error(f"Missing required parameters for {effective_format} listing:")
            for param in missing_params:
                print_error(f"  - {param}")
            if effective_format == "AUCTION":
                print_info("Example: ebay listings create --sku SKU123 --template lego-bulk-auction --price 9.99")
            raise typer.Exit(1)

        # Collect all image paths
        all_image_paths = image or ""
```
**Action:** Add --publish validation AFTER the missing_params check and BEFORE "Collect all image paths":
```python
        if missing_params:
            print_error(f"Missing required parameters for {effective_format} listing:")
            for param in missing_params:
                print_error(f"  - {param}")
            if effective_format == "AUCTION":
                print_info("Example: ebay listings create --sku SKU123 --template lego-bulk-auction --price 9.99")
            raise typer.Exit(1)

        # Require --publish flag (eBay drafts don't appear in Seller Hub)
        if not publish:
            print_error("The --publish flag is required.")
            print_info("eBay drafts don't appear in Seller Hub. Use --publish to create a pseudo-draft")
            print_info("at $99,999 that you can edit in the eBay UI, or specify --price for a real listing.")
            print_info("")
            print_info("Examples:")
            print_info("  ebay listings create --sku SKU123 --template lego-bulk --publish")
            print_info("  ebay listings create --sku SKU123 --template lego-bulk --publish --price 29.99")
            raise typer.Exit(1)

        # Collect all image paths
        all_image_paths = image or ""
```
**Verify:** `ebay listings create --sku TEST --category 1234 --price 10 2>&1 | grep -q "publish flag is required"`

---

### Step 5: Skip price validation when publishing (will use pseudo-draft price)
**File:** `<cli-tools-root>/ebay/ebay_cli/commands/listings.py`
**Location:** Lines 1051-1056 (price validation in missing_params check)
**Current code:**
```python
        if not has_price:
            if effective_format == "AUCTION":
                missing_params.append("--price (auction starting price)")
            else:
                missing_params.append("--price")
```
**Action:** Don't require price when --publish is used (will default to pseudo-draft price):
```python
        # Price is only required if not publishing (pseudo-drafts default to $99,999)
        if not has_price and not publish:
            if effective_format == "AUCTION":
                missing_params.append("--price (auction starting price)")
            else:
                missing_params.append("--price")
```
**Verify:** No error when running with --publish but no --price (assuming --category is from template)

---

### Step 6: Default to pseudo-draft price when publishing without --price
**File:** `<cli-tools-root>/ebay/ebay_cli/commands/listings.py`
**Location:** Lines 1202-1209 (price setting in offer payload)
**Current code:**
```python
        if price:
            if "pricingSummary" not in offer_payload:
                offer_payload["pricingSummary"] = {}
            price_key = "auctionStartPrice" if offer_payload.get("format") == "AUCTION" else "price"
            offer_payload["pricingSummary"][price_key] = {
                "value": price,
                "currency": currency or "USD",
            }
```
**Action:** Add else branch to default to pseudo-draft price when publishing:
```python
        if price:
            if "pricingSummary" not in offer_payload:
                offer_payload["pricingSummary"] = {}
            price_key = "auctionStartPrice" if offer_payload.get("format") == "AUCTION" else "price"
            offer_payload["pricingSummary"][price_key] = {
                "value": price,
                "currency": currency or "USD",
            }
        elif publish:
            # Default to pseudo-draft price when publishing without explicit price
            # Check if template already provided a price
            pricing = offer_payload.get("pricingSummary", {})
            price_key = "auctionStartPrice" if offer_payload.get("format") == "AUCTION" else "price"
            if not pricing.get(price_key, {}).get("value"):
                if "pricingSummary" not in offer_payload:
                    offer_payload["pricingSummary"] = {}
                offer_payload["pricingSummary"][price_key] = {
                    "value": PSEUDO_DRAFT_PRICE,
                    "currency": currency or "USD",
                }
                print_info(f"No price specified - creating pseudo-draft at ${PSEUDO_DRAFT_PRICE}")
```
**Verify:** Creating with --publish and no --price shows "creating pseudo-draft at $99999.00"

──────────────────────────
### CHECKPOINT: Verify create command changes
**Run:**
```bash
cd <cli-tools-root>/ebay
python -c "
from ebay_cli.models.listing import Listing, ListingStatus, PSEUDO_DRAFT_PRICE
print(f'PSEUDO_DRAFT_PRICE: {PSEUDO_DRAFT_PRICE}')
l = Listing(sku='TEST', status=ListingStatus.ACTIVE, price='99999.00')
print(f'is_pseudo_draft for 99999.00: {l.is_pseudo_draft}')
l2 = Listing(sku='TEST2', status=ListingStatus.ACTIVE, price='50.00')
print(f'is_pseudo_draft for 50.00: {l2.is_pseudo_draft}')
l3 = Listing(sku='TEST3', status=ListingStatus.DRAFT, price='99999.00')
print(f'is_pseudo_draft for draft: {l3.is_pseudo_draft}')
"
```
**Expected:**
```
PSEUDO_DRAFT_PRICE: 99999.00
is_pseudo_draft for 99999.00: True
is_pseudo_draft for 50.00: False
is_pseudo_draft for draft: False
```
**If failing:** Fix import or property issues before proceeding
──────────────────────────

---

### Step 7: Modify --status=draft filter to include pseudo-drafts
**File:** `<cli-tools-root>/ebay/ebay_cli/commands/listings.py`
**Location:** Lines 621-628 (status filter in _get_merged_listings)
**Current code:**
```python
    # Apply status filter
    if status_filter:
        if status_filter == "active":
            listings = [l for l in listings if l.is_active]
        elif status_filter == "draft":
            listings = [l for l in listings if l.is_draft]
        elif status_filter == "unsold":
            listings = [l for l in listings if l.is_unsold]
```
**Action:** Update to include pseudo-drafts in draft filter and exclude them from active:
```python
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
```
**Verify:** After creating a pseudo-draft, `ebay listings list --status=draft` includes it

---

### Step 8: Add --price option to listings_publish command
**File:** `<cli-tools-root>/ebay/ebay_cli/commands/listings.py`
**Location:** Lines 1505-1509 (publish command signature)
**Current code:**
```python
@app.command("publish")
def listings_publish(
    sku: str = typer.Argument(..., help="SKU of the listing to publish"),
):
```
**Action:** Add --price option:
```python
@app.command("publish")
def listings_publish(
    sku: str = typer.Argument(..., help="SKU of the listing to publish"),
    price: Optional[str] = typer.Option(None, "--price", "-p", help="Set final price (required for pseudo-drafts)"),
):
```
**Verify:** `ebay listings publish --help` shows --price option

---

### Step 9: Handle pseudo-drafts in listings_publish
**File:** `<cli-tools-root>/ebay/ebay_cli/commands/listings.py`
**Location:** Lines 1528-1532 (is_active check in publish command)
**Current code:**
```python
        if listing.is_active:
            print_warning(f"Listing is already active: {sku}")
            if listing.url:
                print_info(f"View listing: {listing.url}")
            raise typer.Exit(0)
```
**Action:** Replace with pseudo-draft handling:
```python
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
```
**Verify:** `ebay listings publish SKU --price 29.99` on a pseudo-draft updates the price

──────────────────────────
### CHECKPOINT: Verify publish command changes
**Run:**
```bash
cd <cli-tools-root>/ebay
ebay listings publish --help | grep -q "\-\-price" && echo "PASS: --price option added"
```
**Expected:** `PASS: --price option added`
**If failing:** Check Step 8 implementation
──────────────────────────

---

### Step 10: Update create command docstring
**File:** `<cli-tools-root>/ebay/ebay_cli/commands/listings.py`
**Location:** Lines 995-1005 (docstring after function signature)
**Current docstring:**
```python
    """
    Create a new listing (draft by default).

    Creates both an inventory item and an offer. Use --publish to make it live immediately.

    Examples:
        ebay listings create --sku SKU123 --title "My Item" --price 29.99 --category 175673
        ebay listings create --sku SKU123 --template vintage-camera
        ebay listings create --sku SKU123 --template vintage-camera --price 149.99 --publish
        ebay listings create --sku SKU123 --title "Item" --price 99 --image-folder ./photos/
    """
```
**Action:** Update to reflect pseudo-draft behavior:
```python
    """
    Create a new listing.

    The --publish flag is required. Creates a pseudo-draft at $99,999 (visible in eBay Seller Hub)
    unless --price is specified. Use 'ebay listings publish SKU --price X' to set the final price.

    Note: eBay API drafts don't appear in Seller Hub, so we create pseudo-drafts instead.

    Examples:
        ebay listings create --sku SKU123 --template lego-bulk --publish
        ebay listings create --sku SKU123 --template vintage-camera --publish --price 149.99
        ebay listings create --sku SKU123 --title "Item" --price 99 --category 175673 --publish
    """
```
**Verify:** `ebay listings create --help` shows updated docstring

---

### Step 11: Update publish command docstring
**File:** `<cli-tools-root>/ebay/ebay_cli/commands/listings.py`
**Location:** Lines 1510-1515 (docstring after function signature)
**Current docstring:**
```python
    """
    Publish a draft listing to make it live on eBay.

    Examples:
        ebay listings publish SKU123
    """
```
**Action:** Update to document pseudo-draft handling:
```python
    """
    Publish a draft listing or set final price on a pseudo-draft.

    For real drafts: Publishes the listing to make it live on eBay.
    For pseudo-drafts: Use --price to set the final price (required).

    Examples:
        ebay listings publish SKU123                  # Publish real draft
        ebay listings publish SKU123 --price 29.99   # Set price on pseudo-draft
    """
```
**Verify:** `ebay listings publish --help` shows updated docstring

---

### Step 12: Update README documentation
**File:** `<cli-tools-root>/ebay/README.md`
**Location:** Lines 162-219 (Listings section)
**Action:** Update the Listings section to document pseudo-draft behavior. Find the current "### Listings" section and update it to explain:
1. --publish flag is required
2. Pseudo-drafts are created at $99,999 when no price specified
3. Use `publish --price` to finalize pseudo-drafts
4. `--status=draft` includes pseudo-drafts

**Verify:** README accurately reflects the new behavior

──────────────────────────
### FINAL CHECKPOINT: Integration test
**Run:**
```bash
cd <cli-tools-root>/ebay

# Test 1: Verify model constant and property
python -c "
from ebay_cli.models.listing import Listing, ListingStatus, PSEUDO_DRAFT_PRICE
assert PSEUDO_DRAFT_PRICE == '99999.00', 'Constant wrong'
l = Listing(sku='T', status=ListingStatus.ACTIVE, price='99999.00')
assert l.is_pseudo_draft == True, 'is_pseudo_draft failed for pseudo-draft'
l2 = Listing(sku='T2', status=ListingStatus.ACTIVE, price='50.00')
assert l2.is_pseudo_draft == False, 'is_pseudo_draft failed for regular'
print('Model tests PASSED')
"

# Test 2: Verify imports work
python -c "
from ebay_cli.commands.listings import PSEUDO_DRAFT_PRICE
print(f'Import test PASSED: {PSEUDO_DRAFT_PRICE}')
"

# Test 3: Check CLI help
ebay listings create --help | grep -q "publish" && echo "Create help PASSED"
ebay listings publish --help | grep -q "price" && echo "Publish help PASSED"
```
**Expected:** All tests pass
**If failing:** Review the specific failing step
──────────────────────────

## Testing Strategy
1. **Unit test**: Verify `is_pseudo_draft` property returns True for price=99999.00 and status=active
2. **Unit test**: Verify `is_pseudo_draft` returns False for other prices or draft status
3. **Integration**: Create a listing without --publish and verify error message
4. **Integration**: Create a listing with --publish and no --price, verify $99,999 price
5. **Integration**: `listings list --status=draft` includes pseudo-drafts
6. **Integration**: `listings list --status=active` excludes pseudo-drafts
7. **Integration**: `listings publish SKU --price X` updates pseudo-draft price

## Success Criteria
- [ ] Creating a listing without `--publish` shows helpful error
- [ ] Creating with `--publish` but no `--price` creates at $99,999
- [ ] Creating with `--publish --price X` creates at price X
- [ ] `--status=draft` filter returns real drafts AND pseudo-drafts
- [ ] `--status=active` filter excludes pseudo-drafts
- [ ] `listings publish SKU --price X` sets real price on pseudo-drafts
- [ ] Help text and docstrings updated
- [ ] README documentation updated
