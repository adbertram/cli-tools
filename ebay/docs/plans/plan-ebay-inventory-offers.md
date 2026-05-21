# Implementation Plan: eBay Inventory and Offers Commands

## Executive Summary

Add inventory management, offer management, and complete policy management (payment/return policies) to the eBay CLI. The implementation follows existing patterns and returns full API responses.

**Task:** Create `ebay inventory` and `ebay offers` command groups for CRUD operations on eBay store listings.

## Scope

### In Scope (This Plan)
- `ebay inventory` commands: list, get, create, update, delete, set-quantity
- `ebay offers` commands: list, get, create, update, delete, publish, withdraw, set-price
- `ebay payment-policies` commands: list, get
- `ebay return-policies` commands: list, get
- Client methods for all Inventory API endpoints
- OAuth scope updates for inventory/account APIs

### Out of Scope
- Full payment/return policy CRUD (create/update/delete) - can add later
- Inventory item groups (multi-variation listings)
- Bulk operations beyond bulkGetInventoryItems
- Inventory locations management

---

## Phase 1: OAuth Scope Updates and Client Foundation

### Step 1.1: Update OAuth Scopes in client.py

**File:** `ebay_cli/client.py`
**Location:** Lines 20-25

**Current:**
```python
SCOPES = [
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly",
    "https://api.ebay.com/oauth/api_scope/commerce.identity.readonly",
]
```

**Updated:**
```python
SCOPES = [
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly",
    "https://api.ebay.com/oauth/api_scope/commerce.identity.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.account",
    "https://api.ebay.com/oauth/api_scope/sell.account.readonly",
]
```

### Step 1.2: Add Inventory Item Methods to EbayClient

**File:** `ebay_cli/client.py`
**Location:** After the Identity Methods section (after line 375)

Add methods:
- `get_inventory_items(limit, offset)` - GET /sell/inventory/v1/inventory_item
- `get_inventory_item(sku)` - GET /sell/inventory/v1/inventory_item/{sku}
- `create_or_update_inventory_item(sku, payload)` - PUT /sell/inventory/v1/inventory_item/{sku}
- `delete_inventory_item(sku)` - DELETE /sell/inventory/v1/inventory_item/{sku}
- `bulk_get_inventory_items(skus)` - POST /sell/inventory/v1/bulk_get_inventory_item

### Step 1.3: Add Offer Methods to EbayClient

**File:** `ebay_cli/client.py`

Add methods:
- `get_offers(sku, marketplace_id, limit, offset)` - GET /sell/inventory/v1/offer
- `get_offer(offer_id)` - GET /sell/inventory/v1/offer/{offerId}
- `create_offer(payload)` - POST /sell/inventory/v1/offer
- `update_offer(offer_id, payload)` - PUT /sell/inventory/v1/offer/{offerId}
- `delete_offer(offer_id)` - DELETE /sell/inventory/v1/offer/{offerId}
- `publish_offer(offer_id)` - POST /sell/inventory/v1/offer/{offerId}/publish
- `withdraw_offer(offer_id)` - POST /sell/inventory/v1/offer/{offerId}/withdraw

### Step 1.4: Add Policy Methods to EbayClient

**File:** `ebay_cli/client.py`

Add methods for Payment and Return policies:
- `get_payment_policies(marketplace_id)` - GET /sell/account/v1/payment_policy
- `get_payment_policy(policy_id)` - GET /sell/account/v1/payment_policy/{policy_id}
- `get_return_policies(marketplace_id)` - GET /sell/account/v1/return_policy
- `get_return_policy(policy_id)` - GET /sell/account/v1/return_policy/{policy_id}

Note: The fulfillment policy methods may need to be added if they're not already in client.py (they're used by policies.py but not defined in client.py).

---

## Phase 2: Inventory Commands

### Step 2.1: Create inventory.py Command Module

**File:** `ebay_cli/commands/inventory.py` (NEW)

Commands:
- `list` - List all inventory items with pagination
- `get <sku>` - Get details for a specific inventory item
- `create <sku>` - Create/update an inventory item (supports --from-json)
- `update <sku>` - Update an existing inventory item
- `delete <sku>` - Delete an inventory item
- `set-quantity <sku> <quantity>` - Quick quantity update

**Core create flags:**
- `--title` (required)
- `--condition` (default: NEW)
- `--quantity` (default: 1)
- `--description`
- `--images` (comma-separated URLs)
- `--aspects` (JSON string)
- `--from-json` (full payload file)
- `--locale` (default: en_US)

---

## Phase 3: Offers Commands

### Step 3.1: Create offers.py Command Module

**File:** `ebay_cli/commands/offers.py` (NEW)

Commands:
- `list` - List all offers with pagination and SKU filter
- `get <offer_id>` - Get details for a specific offer
- `create` - Create an offer (draft)
- `update <offer_id>` - Update an existing offer
- `delete <offer_id>` - Delete an offer
- `publish <offer_id>` - Publish offer (make it live)
- `withdraw <offer_id>` - Withdraw published offer (end listing)
- `set-price <offer_id> <price>` - Quick price update

**Core create flags:**
- `--sku` (required)
- `--marketplace` (default: EBAY_US)
- `--format` (default: FIXED_PRICE)
- `--category` (eBay category ID)
- `--price`
- `--currency` (default: USD)
- `--quantity`
- `--description`
- `--fulfillment-policy`
- `--payment-policy`
- `--return-policy`
- `--location`
- `--from-json` (full payload file)

---

## Phase 4: Expand Policy Commands

### Step 4.1: Add Payment and Return Policy Commands to policies.py

**File:** `ebay_cli/commands/policies.py`

Add two new Typer apps:
- `payment_app` - Payment policy commands (list, get)
- `return_app` - Return policy commands (list, get)

---

## Phase 5: Update main.py

### Step 5.1: Register All Command Groups

**File:** `ebay_cli/main.py`

Update imports and registrations:
```python
from .commands import auth, orders, shipping, policies, inventory, offers

app.add_typer(auth.app, name="auth", help="Manage eBay API authentication")
app.add_typer(orders.app, name="orders", help="Manage eBay orders")
app.add_typer(shipping.app, name="shipping-quote", help="Manage eBay shipping quotes")
app.add_typer(inventory.app, name="inventory", help="Manage eBay inventory items")
app.add_typer(offers.app, name="offers", help="Manage eBay offers (listings)")
app.add_typer(policies.app, name="policies", help="Manage eBay fulfillment policies")
app.add_typer(policies.payment_app, name="payment-policies", help="Manage eBay payment policies")
app.add_typer(policies.return_app, name="return-policies", help="Manage eBay return policies")
```

---

## Phase 6: Update README.md

### Step 6.1: Add Documentation for New Commands

Add sections for:
- Inventory Items (list, get, create, update, delete, set-quantity)
- Offers (list, get, create, update, delete, publish, withdraw, set-price)
- Policies (fulfillment, payment, return)

---

## Test Checkpoints

### Checkpoint 1: After Phase 1 (Client Methods)
```bash
ebay auth logout
ebay auth login
ebay auth status
# Test client methods directly
python -c "from ebay_cli.client import get_client; c = get_client(); print(c.get_inventory_items(limit=1))"
```

### Checkpoint 2: After Phase 2 (Inventory Commands)
```bash
ebay inventory list --help
ebay inventory list
```

### Checkpoint 3: After Phase 3 (Offers Commands)
```bash
ebay offers list --help
ebay offers list
```

### Checkpoint 4: After Phase 4-5 (All Commands)
```bash
ebay --help
# Verify all command groups appear
ebay policies list
ebay payment-policies list
ebay return-policies list
```

### Final End-to-End Test
```bash
# 1. Verify policies exist
ebay policies list
ebay payment-policies list
ebay return-policies list

# 2. Create an inventory item
ebay inventory create TEST-SKU-001 \
  --title "Test Product" \
  --condition NEW \
  --quantity 10

# 3. Verify inventory item
ebay inventory get TEST-SKU-001

# 4. Create an offer (draft)
ebay offers create \
  --sku TEST-SKU-001 \
  --category 175673 \
  --price 29.99 \
  --fulfillment-policy <policy-id> \
  --payment-policy <policy-id> \
  --return-policy <policy-id>

# 5. Verify offer created
ebay offers list --sku TEST-SKU-001

# 6. Cleanup
ebay offers delete <offer-id> --force
ebay inventory delete TEST-SKU-001 --force
```

---

## Files Summary

| File | Action | Description |
|------|--------|-------------|
| `ebay_cli/client.py` | MODIFY | Add OAuth scopes, inventory/offer/policy methods |
| `ebay_cli/main.py` | MODIFY | Register new command groups |
| `ebay_cli/commands/inventory.py` | CREATE | Inventory item commands |
| `ebay_cli/commands/offers.py` | CREATE | Offer commands |
| `ebay_cli/commands/policies.py` | MODIFY | Add payment/return policy apps |
| `README.md` | MODIFY | Add documentation for new commands |

---

## API Reference

### Inventory API Endpoints
- GET /sell/inventory/v1/inventory_item - List items
- GET /sell/inventory/v1/inventory_item/{sku} - Get item
- PUT /sell/inventory/v1/inventory_item/{sku} - Create/update item
- DELETE /sell/inventory/v1/inventory_item/{sku} - Delete item
- POST /sell/inventory/v1/bulk_get_inventory_item - Bulk get items

### Offer API Endpoints
- GET /sell/inventory/v1/offer - List offers
- GET /sell/inventory/v1/offer/{offerId} - Get offer
- POST /sell/inventory/v1/offer - Create offer
- PUT /sell/inventory/v1/offer/{offerId} - Update offer
- DELETE /sell/inventory/v1/offer/{offerId} - Delete offer
- POST /sell/inventory/v1/offer/{offerId}/publish - Publish offer
- POST /sell/inventory/v1/offer/{offerId}/withdraw - Withdraw offer

### Account API Endpoints (Policies)
- GET /sell/account/v1/payment_policy - List payment policies
- GET /sell/account/v1/payment_policy/{policy_id} - Get payment policy
- GET /sell/account/v1/return_policy - List return policies
- GET /sell/account/v1/return_policy/{policy_id} - Get return policy
