# Plan: Fix eBay CLI Compliance Issues

## One-Line Summary
Add Feed API `listings list` command for all active listings and fix policy --limit defaults.

## Why This Approach
- Feed API (`LMS_ACTIVE_INVENTORY_REPORT`) is the modern REST way to get ALL active listings
- Uses existing OAuth scope (`sell.inventory`) already configured in the CLI
- Avoids deprecated Trading API (XML/SOAP)
- The Inventory API `offers list` correctly requires --sku (API limitation) - this is expected behavior

## Discovery Summary

### Files Read
| File | Key Findings |
|------|--------------|
| `client.py` | OAuth token management, retry logic (lines 196-244), existing API methods |
| `offers.py` | Requires --sku because eBay Inventory API genuinely requires it |
| `policies.py` | Line 19, 354, 474: --limit defaults to 0, should be 100 |
| `orders.py` | Already has date filtering via --filter "created:gte:YYYY-MM-DD" |

### API Research
- eBay Inventory API `getOffers` requires SKU - confirmed via direct API test (400 error without SKU)
- Feed API `createInventoryTask` with `LMS_ACTIVE_INVENTORY_REPORT` returns all active listings
- Feed API returns: ItemID, SKU, Price, Quantity, SiteID (no Title)
- Feed API uses same OAuth scope: `https://api.ebay.com/oauth/api_scope/sell.inventory`

### Verified OK (No Changes Needed)
- Retry logic uses proper `base_delay * (2 ** attempt)` formula (line 212)
- Retries on {429, 500, 502, 503, 504} and connection errors (line 21, 232-242)
- Orders already has date filtering
- No Pydantic models to update

---

## Implementation Steps

### Step 1: Add Feed API methods to client.py

**File:** `ebay_cli/client.py`

Add three methods after the existing Offer methods (~line 700):

```python
# Feed API Methods
def create_inventory_task(self, feed_type: str = "LMS_ACTIVE_INVENTORY_REPORT",
                          listing_format: Optional[str] = None) -> str:
    """Create inventory report task. Returns task_id from Location header."""
    endpoint = "/sell/feed/v1/inventory_task"
    payload = {
        "schemaVersion": "1.0",
        "feedType": feed_type
    }
    if listing_format:
        payload["filterCriteria"] = {"listingFormat": listing_format}
    # Need special handling to capture Location header for task_id

def get_inventory_task(self, task_id: str) -> Dict:
    """Get status of inventory task."""
    endpoint = f"/sell/feed/v1/inventory_task/{task_id}"
    return self._make_request("GET", endpoint)

def get_inventory_task_result(self, task_id: str) -> bytes:
    """Download result file for completed task."""
    endpoint = f"/sell/feed/v1/task/{task_id}/download_result_file"
    # Returns file content (gzipped XML), not JSON
```

**Verification:** `python -c "from ebay_cli.client import EbayClient; print('create_inventory_task' in dir(EbayClient()))"`

---

### Step 2: Create listings command module

**File:** `ebay_cli/commands/listings.py` (NEW)

Create new command file for Feed API listings:

```python
"""Listings commands using eBay Feed API."""
import typer
import time
from typing import Optional

from ..client import get_client
from ..output import print_json, print_table, handle_error, print_info

app = typer.Typer(help="List all active eBay listings")

@app.command("list")
def listings_list(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum listings to return"),
    format: Optional[str] = typer.Option(None, "--format", "-f",
        help="Filter by listing format: AUCTION, FIXED_PRICE"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p",
        help="Comma-separated fields to include"),
):
    """
    List all active eBay listings.

    Uses the Feed API to download a complete inventory report containing
    ItemID, SKU, Price, and Quantity for all active listings.

    Note: This is an async operation - waits for report generation (1-2 min).

    Examples:
        ebay listings list
        ebay listings list --limit 50
        ebay listings list --format FIXED_PRICE
    """
```

**Verification:** `ebay listings list --help`

---

### Step 3: Register listings command in main.py

**File:** `ebay_cli/main.py`

Add import and register:
```python
from .commands.listings import app as listings_app
app.add_typer(listings_app, name="listings")
```

**Verification:** `ebay --help` shows "listings" command

---

### CHECKPOINT 1: Verify Feed API Integration
```bash
ebay listings list --limit 5
# Expected: Creates task, polls status, returns listing data
```

---

### Step 4: Fix policy --limit defaults

**File:** `ebay_cli/commands/policies.py`

| Line | Change |
|------|--------|
| 19 | `typer.Option(0, ...)` → `typer.Option(100, ...)` |
| 354 | `typer.Option(0, ...)` → `typer.Option(100, ...)` |
| 474 | `typer.Option(0, ...)` → `typer.Option(100, ...)` |

Also update help text from `"(0 = all)"` to `"Maximum number of policies to return"`.

**Verification:** `ebay policies list --help` shows default=100

---

### Step 5: Update README.md with listings command

**File:** `README.md`

Add documentation for `listings list` command.

**Verification:** README contains listings command docs

---

### CHECKPOINT 2: Final Compliance Test
```bash
<cli-tools-root>/_repo/skills/cli-tool/scripts/test-cli-tool.sh ebay
# Expected: All PASS, no failures for --limit defaults
```

---

## Testing Strategy

1. After Step 3: Test `ebay listings list --limit 5`
2. After Step 4: Test `ebay policies list --help` shows default=100
3. Final: Re-run full compliance test script

## What's NOT Included

- Title field in listings (Feed API limitation)
- Modifying `offers list` --sku requirement (correct API behavior)
- Trading API integration (deprecated)
- Pydantic model changes (none exist)

## Todo List

1. Add Feed API methods to client.py
2. Create listings.py command module
3. Register listings app in main.py
4. Test listings list command
5. Fix policies.py line 19: --limit default 0 → 100
6. Fix policies.py line 354: --limit default 0 → 100
7. Fix policies.py line 474: --limit default 0 → 100
8. Update README.md with listings command
9. Run full compliance test
