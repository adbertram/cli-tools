# Brick Owl CLI

A command-line interface for the [Brick Owl API](https://api.brickowl.com/v1). Manage orders, inventory, catalog data, messages, refunds, coupons, and quotes for your Brick Owl LEGO marketplace store.

## Installation

```bash
cd brickowl
./install.sh
```

The install script creates a virtual environment, installs the package in editable mode, and symlinks the `brickowl` command to `~/.local/bin/`. Ensure `~/.local/bin` is in your `PATH`:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Verify the installation:

```bash
brickowl --version
```

## Quick Start

```bash
# Configure your API key
brickowl auth login --api-key YOUR_API_KEY

# List recent orders
brickowl order list --limit 10 --table

# Check inventory statistics
brickowl inventory stats --table

# Search the catalog
brickowl catalog search "Millennium Falcon"

# View your store details
brickowl user details
```

## Commands

### auth

Manage Brick Owl API authentication. Credentials are stored in `.env` profile files.

```bash
# Interactive login (prompts for API key)
brickowl auth login

# Re-authenticate (clears existing credentials first)
brickowl auth login --force

# Login with a specific profile
brickowl auth login --profile staging

# Check authentication status
brickowl auth status
brickowl auth status --table

# Test credentials (makes API call + checks browser session)
brickowl auth test
brickowl auth test --verbose

# Clear stored credentials
brickowl auth logout
```

| Subcommand | Description |
|------------|-------------|
| `login` | Configure API key authentication |
| `status` | Check authentication status |
| `test` | Test credentials by making an API call |
| `logout` | Clear stored credentials |

**login options:**

| Option | Short | Description |
|--------|-------|-------------|
| `--force` | `-F` | Clear existing credentials and re-authenticate |
| `--profile` | `-p` | Profile name to save credentials to |

**status options:**

| Option | Short | Description |
|--------|-------|-------------|
| `--profile` | `-p` | Profile name to check |
| `--table` | `-t` | Display as table |

**test options:**

| Option | Short | Description |
|--------|-------|-------------|
| `--profile` | `-p` | Profile name to test |
| `--table` | `-t` | Display as table |
| `--verbose` | `-v` | Show detailed checks |

### order

Manage Brick Owl orders -- list, view details, update status, ship, and add tracking.

```bash
# List all store orders (received)
brickowl order list

# List orders by status (name or ID)
brickowl order list --status "payment received"
brickowl order list --status 2

# List multiple statuses (comma-separated)
brickowl order list --status 2,3,4

# List only not-yet-picked orders
brickowl order list --not-picked --table

# List shipped orders
brickowl order list --shipped --limit 10

# List customer orders (orders you placed)
brickowl order list --type customer

# Filter and select fields
brickowl order list --filter "buyer_name:contains:John"
brickowl order list --properties "order_id,status,buyer_name"

# Get full details for an order
brickowl order get 12345678
brickowl order get 12345678 --table

# Get items in an order
brickowl order items 12345678
brickowl order items 12345678 --table

# Set order status (0-8)
brickowl order status 12345678 4

# Mark order as shipped
brickowl order ship 12345678

# Mark shipped with tracking
brickowl order ship 12345678 --tracking 9400111899223456789012

# Add tracking to an order
brickowl order tracking 12345678 9400111899223456789012

# Set a seller note on an order
brickowl order note 12345678 "Shipped via USPS Priority"
```

| Subcommand | Description |
|------------|-------------|
| `list` | List orders with optional filtering |
| `get` | Get full details for a specific order |
| `items` | Get items in an order |
| `status` | Set the status of an order |
| `ship` | Mark an order as shipped, optionally with tracking |
| `tracking` | Add tracking information to an order |
| `note` | Set seller note on an order |

**Order status IDs:**

| ID | Status |
|----|--------|
| 0 | Pending |
| 1 | Payment Submitted |
| 2 | Payment Received |
| 3 | Processing |
| 4 | Processed |
| 5 | Shipped |
| 6 | Received |
| 7 | On Hold |
| 8 | Cancelled |

**list options:**

| Option | Short | Description |
|--------|-------|-------------|
| `--status` | `-s` | Filter by status (name, ID, or comma-separated) |
| `--type` | | Order type: `store` (received, default) or `customer` (placed) |
| `--limit` | `-l` | Maximum number of orders to return |
| `--sort` | | Sort by: `created` or `updated` |
| `--shipped` | | Show only shipped orders |
| `--not-shipped` | | Show only not-shipped orders |
| `--not-picked` | | Show only not-picked orders |
| `--table` | `-t` | Display as table |
| `--filter` | `-f` | Filter results (field:op:value) |
| `--properties` | `-p` | Comma-separated fields to include |

### inventory

Manage your Brick Owl store inventory -- list lots, view details, update prices/quantities, and delete lots.

```bash
# List all active inventory lots
brickowl inventory list

# List by item type
brickowl inventory list --type Part

# Include inactive lots
brickowl inventory list --all

# Limit and display as table
brickowl inventory list --limit 50 --table

# Filter by quantity
brickowl inventory list --filter "qty:gt:5"

# Select specific fields
brickowl inventory list --properties "lot_id,name,qty,price"

# Get details for a specific lot
brickowl inventory get LOT_ID
brickowl inventory get LOT_ID --table

# Show inventory statistics (totals and breakdown by type)
brickowl inventory stats
brickowl inventory stats --table

# Update lot price
brickowl inventory update LOT_ID --price 1.50

# Set absolute quantity
brickowl inventory update LOT_ID --quantity 10

# Adjust quantity (relative, positive or negative)
brickowl inventory update LOT_ID --adjust -2

# Set sale percentage (0 to remove)
brickowl inventory update LOT_ID --sale 20

# Hide or show a lot
brickowl inventory update LOT_ID --hide
brickowl inventory update LOT_ID --show

# Delete a lot
brickowl inventory delete LOT_ID
```

| Subcommand | Description |
|------------|-------------|
| `list` | List inventory lots |
| `get` | Get details for a specific lot |
| `stats` | Show inventory statistics (totals and breakdown by type) |
| `update` | Update an inventory lot (price, quantity, sale, visibility) |
| `delete` | Delete an inventory lot |

**list options:**

| Option | Short | Description |
|--------|-------|-------------|
| `--type` | | Filter by item type (Part, Set, Minifigure, etc.) |
| `--all` | | Include inactive lots (default: active only) |
| `--limit` | `-l` | Maximum number of lots to return |
| `--table` | `-t` | Display as table |
| `--filter` | `-f` | Filter results (field:op:value) |
| `--properties` | `-p` | Comma-separated fields to include |

**update options:**

| Option | Short | Description |
|--------|-------|-------------|
| `--price` | | Set price |
| `--quantity` | `-q` | Set absolute quantity |
| `--adjust` | | Adjust quantity (positive or negative) |
| `--sale` | | Set sale percentage (0 to remove) |
| `--hide` | | Hide lot (set for_sale=0) |
| `--show` | | Show lot (set for_sale=1) |

### catalog

Browse the Brick Owl catalog -- look up items, search, check availability, view set inventories, and list reference data.

```bash
# Look up an item by BOID
brickowl catalog lookup 123456
brickowl catalog lookup 123456 --table

# Search the catalog
brickowl catalog search "Millennium Falcon"
brickowl catalog search "3001" --table
brickowl catalog search "minifig" --page 2

# Look up an item by external ID
brickowl catalog id 3001 Part
brickowl catalog id 3001 Part --id-type design_id
brickowl catalog id 75192 Set --table

# Get pricing and availability
brickowl catalog availability 123456 US
brickowl catalog availability 123456 US --quantity 10
brickowl catalog availability 123456 US --table

# Get parts inventory for a set
brickowl catalog inventory 123456
brickowl catalog inventory 123456 --table

# List all colors
brickowl catalog colors
brickowl catalog colors --table

# List all conditions
brickowl catalog conditions
brickowl catalog conditions --table

# List all categories
brickowl catalog categories
brickowl catalog categories --table

# List all themes
brickowl catalog themes
brickowl catalog themes --table
```

| Subcommand | Description |
|------------|-------------|
| `lookup` | Look up a catalog item by BOID **(approval required)** |
| `search` | Search the catalog by keyword |
| `id` | Look up a catalog item by external ID (item_no, design_id, bl_item_no, set_number; alias: bricklink) |
| `availability` | Get pricing and availability for an item in a country **(approval required)** |
| `inventory` | Get the parts inventory for a set **(approval required)** |
| `colors` | List all available colors |
| `conditions` | List all available conditions |
| `categories` | List all catalog categories |
| `themes` | List all catalog themes |

**Note:** Commands marked **(approval required)** require special API access from Brick Owl. Contact [Brick Owl support](https://www.brickowl.com/contact) to request access. As an alternative, use `brickowl catalog id` to look up items by external ID (item_no, design_id, bl_item_no, set_number).

**search options:**

| Option | Short | Description |
|--------|-------|-------------|
| `--page` | | Page number (default: 1) |
| `--table` | `-t` | Display as table |

**id arguments and options:**

| Argument/Option | Description |
|-----------------|-------------|
| `ID_VALUE` | External ID value (positional) |
| `TYPE` | Item type: Part, Set, Minifigure, etc. (positional) |
| `--id-type` | ID type: `item_no`, `design_id`, `bl_item_no`, `set_number` (alias: `bricklink` -> `bl_item_no`) |
| `--table` / `-t` | Display as table |

**availability options:**

| Option | Short | Description |
|--------|-------|-------------|
| `--quantity` | `-q` | Quantity to check |
| `--table` | `-t` | Display as table |

### user

View your Brick Owl user and store details.

```bash
# Get your store details
brickowl user details
brickowl user details --table
```

| Subcommand | Description |
|------------|-------------|
| `details` | Get your Brick Owl user/store details |

### messages (browser automation -- not yet implemented)

Manage Brick Owl messages. These commands require browser automation and are currently placeholders.

```bash
# List inbox messages
brickowl messages list
brickowl messages list --status unread
brickowl messages list --table --limit 10

# Get a specific message
brickowl messages get MSG_ID
brickowl messages get MSG_ID --table

# View conversation thread for an order
brickowl messages conversation 12345678
brickowl messages conversation 12345678 --table

# Reply to a message on an order
brickowl messages reply 12345678 "Thank you for your order!"

# Send a new message to a user
brickowl messages send buyer123 "Order Question" "Hello, about your order..."

# Mark messages as read/unread
brickowl messages mark-read MSG_ID
brickowl messages mark-unread MSG_ID
```

| Subcommand | Description |
|------------|-------------|
| `list` | List messages in the inbox |
| `get` | Get a specific message |
| `conversation` | View the conversation thread for an order |
| `reply` | Reply to a message on an order |
| `send` | Send a new message to a user |
| `mark-read` | Mark a message as read |
| `mark-unread` | Mark a message as unread |

### refund (browser automation -- not yet implemented)

Manage Brick Owl refunds. These commands require browser automation and are currently placeholders.

```bash
# Get refund info for an order (total, prior refunds, max refund)
brickowl refund info 12345678
brickowl refund info 12345678 --table

# Issue a partial refund
brickowl refund issue 12345678 5.00
brickowl refund issue 12345678 5.00 --reason "Missing Items"
brickowl refund issue 12345678 5.00 --reason "Overcharged Shipping" --message "Refunding excess shipping"

# Issue a full refund
brickowl refund full 12345678
brickowl refund full 12345678 --reason "Cancel Order"
```

| Subcommand | Description |
|------------|-------------|
| `info` | Get refund information for an order (total, prior refunds, max refund) |
| `issue` | Issue a partial refund for an order |
| `full` | Issue a full refund for an order |

**issue arguments and options:**

| Argument/Option | Description |
|-----------------|-------------|
| `ORDER_ID` | The order ID (positional) |
| `AMOUNT` | Refund amount in dollars (positional) |
| `--reason` / `-r` | Refund reason |
| `--message` / `-m` | Message to buyer |

### coupon (browser automation -- not yet implemented)

Manage Brick Owl store coupons. These commands require browser automation and are currently placeholders.

```bash
# List store coupons
brickowl coupon list
brickowl coupon list --table

# Get coupon details
brickowl coupon get COUPON_ID
brickowl coupon get COUPON_ID --table

# Create a coupon for a specific user
brickowl coupon create-user buyer123 10
brickowl coupon create-user buyer123 15 --min-order 25.00 --free-shipping

# Create a coupon with a specific code
brickowl coupon create-code SAVE10 10
brickowl coupon create-code HOLIDAY20 20 --min-order 50 --limit 100

# Delete a coupon
brickowl coupon delete COUPON_ID
```

| Subcommand | Description |
|------------|-------------|
| `list` | List store coupons |
| `get` | Get details for a specific coupon |
| `create-user` | Create a coupon for a specific user |
| `create-code` | Create a coupon with a specific code |
| `delete` | Delete a coupon |

**create-user options:**

| Option | Description |
|--------|-------------|
| `--min-order` | Minimum order amount |
| `--max-discount` | Maximum discount amount |
| `--free-shipping` | Include free shipping |
| `--note` / `-n` | Coupon note |

**create-code options:**

| Option | Description |
|--------|-------------|
| `--min-order` | Minimum order amount |
| `--max-discount` | Maximum discount amount |
| `--free-shipping` | Include free shipping |
| `--limit` | Maximum number of redemptions |
| `--note` / `-n` | Coupon note |

### quotes (browser automation -- not yet implemented)

Manage Brick Owl quotes. These commands require browser automation and are currently placeholders.

```bash
# List quote requests
brickowl quotes list
brickowl quotes list --table

# Get quote details
brickowl quotes get QUOTE_ID
brickowl quotes get QUOTE_ID --table

# Create a new quote for a buyer
brickowl quotes create buyer123 "10x 3001 Red, 5x 3002 Blue"
brickowl quotes create buyer123 '{"items": [...]}' --shipping 5.99
```

| Subcommand | Description |
|------------|-------------|
| `list` | List quote requests |
| `get` | Get details for a specific quote |
| `create` | Create a new quote for a buyer |

**create options:**

| Option | Description |
|--------|-------------|
| `--shipping` | Shipping cost |
| `--note` / `-n` | Note for the buyer |

### profiles

Manage authentication profiles for multi-account support.

```bash
# List all profiles
brickowl auth profiles list
brickowl auth profiles list --table

# Get details for a specific profile
brickowl auth profiles get staging

# Create a new profile
brickowl auth profiles create staging

# Select the active profile
brickowl auth profiles select staging

# Delete a profile
brickowl auth profiles delete staging
brickowl auth profiles delete staging --force
```

| Subcommand | Description |
|------------|-------------|
| `list` | List all authentication profiles |
| `get` | Get details for a specific profile |
| `create` | Create a new profile from template |
| `select` | Set which profile is used by default |
| `delete` | Delete a profile and its data |

### Cache (`brickowl cache`)

Manage the response cache. Cached responses speed up repeated commands by avoiding redundant browser/API calls.

```bash
# Clear all cached responses
brickowl cache clear
```

## Output Formats

All commands output **JSON by default**. Use `--table` / `-t` for formatted table output.

### JSON (default)

```bash
brickowl order list --limit 2
```

```json
[
  {
    "order_id": "12345678",
    "order_date": "2025-01-15 10:30:00",
    "status": "Payment Received",
    "buyer_name": "JohnDoe",
    "base_order_total": "24.50",
    "total_lots": "8"
  }
]
```

### Table

```bash
brickowl order list --limit 2 --table
```

```
Order ID   Date                  Status             Buyer     Total   Lots
12345678   2025-01-15 10:30:00   Payment Received   JohnDoe   24.50   8
```

### Filtering

Use `--filter` / `-f` to filter results client-side. Format: `field:operator:value`.

```bash
# Exact match (default operator when omitted)
brickowl order list --filter "status:Payment Received"

# Comparison operators
brickowl inventory list --filter "qty:gt:5"
brickowl inventory list --filter "price:lte:2.00"

# String operators
brickowl order list --filter "buyer_name:contains:John"
brickowl order list --filter "buyer_name:startswith:A"

# Multiple filters (AND within a filter, OR between filters)
brickowl order list --filter "status:eq:Payment Received,buyer_name:contains:John"
```

**Supported operators:**

| Operator | Description |
|----------|-------------|
| `eq` | Equal (default) |
| `ne` | Not equal |
| `gt` | Greater than |
| `gte` | Greater than or equal |
| `lt` | Less than |
| `lte` | Less than or equal |
| `in` | In list (values separated by `\|`) |
| `nin` | Not in list |
| `like` | Pattern match (use `%` as wildcard) |
| `ilike` | Case-insensitive pattern match |
| `contains` | Contains substring |
| `startswith` | Starts with string |
| `endswith` | Ends with string |
| `null` | Value is null (no value needed) |
| `notnull` | Value is not null (no value needed) |

### Field Selection

Use `--properties` / `-p` to select specific fields. Supports dot notation for nested fields.

```bash
brickowl order list --properties "order_id,status,buyer_name"
brickowl inventory list --properties "lot_id,name,qty,price"
```

## Options Reference

Common options available across commands:

| Option | Short | Scope | Description |
|--------|-------|-------|-------------|
| `--table` | `-t` | All commands | Display output as a formatted table |
| `--limit` | `-l` | `list` commands | Maximum number of results to return |
| `--filter` | `-f` | `list` commands | Filter results (field:op:value) |
| `--properties` | `-p` | `list` commands | Comma-separated fields to include |
| `--version` | `-v` | Global | Show version and exit |

## Configuration

Authentication profile files live under `~/.local/share/cli-tools/brickowl/authentication_profiles/<profile>/`; non-auth defaults live in `~/.local/share/cli-tools/brickowl/.env`.

### Required

```bash
API_KEY=your_api_key
ACTIVE=true
```

Get your API key from your [Brick Owl account settings](https://www.brickowl.com/account/api).

### Optional

```bash
# API base URL (defaults to production)
BASE_URL=https://api.brickowl.com/v1

# Browser automation settings
HEADLESS=true
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### List unpicked orders in table format

```bash
brickowl order list --not-picked --table
```

### Get order details and pipe to jq

```bash
brickowl order get 12345678 | jq '.buyer_name, .base_order_total'
```

### Export inventory to a file

```bash
brickowl inventory list --properties "lot_id,boid,name,qty,price,condition" > inventory.json
```

### Find high-value inventory lots

```bash
brickowl inventory list --filter "price:gt:10" --table
```

### Look up a part across ID systems

```bash
# By design ID
brickowl catalog id 3001 Part --id-type design_id

# By Bricklink ID
brickowl catalog id 3001 Part --id-type bl_item_no
```

### Check part availability in the US

```bash
brickowl catalog availability 123456 US --quantity 50 --table
```

### Ship an order with tracking

```bash
brickowl order ship 12345678 --tracking 9400111899223456789012
```

### Bulk update: mark multiple orders as processed

```bash
for id in 11111111 22222222 33333333; do
  brickowl order status "$id" 4
done
```

### View inventory stats breakdown

```bash
brickowl inventory stats --table
```

## Requirements

- Python 3.9+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests
  - pydantic
- Playwright (installed automatically if browser automation module exists, for future browser commands)
