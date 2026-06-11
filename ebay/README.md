# eBay CLI

## DESCRIPTION

The `ebay` CLI provides a command-line interface for eBay Fulfillment API.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Installation

```bash
# Clone and install
cd ebay
pip install -e .
```

After installation, the `ebay` command will be available in your terminal.

## Quick Start

```bash
# Authenticate with eBay (opens browser)
ebay auth login

# List your recent orders
ebay seller orders list

# Search public sold/completed marketplace listings
ebay listings search "LEGO 75357" --sold --limit 5

# Get details for a specific order
ebay seller orders get 12-12345-12345
```

## Commands

### Authentication

eBay uses OAuth 2.0 for authentication. You'll need to create an app at the [eBay Developer Portal](https://developer.ebay.com/my/keys) to get your credentials.

```bash
# Start OAuth flow (opens browser, prompts for code/URL)
ebay auth login

# Force re-authentication (even if already logged in)
ebay auth login --force

# Check authentication status
ebay auth status
ebay auth status

# Clear stored credentials
ebay auth logout
```

### Profiles

Manage multiple authentication profiles (e.g., production and sandbox accounts).

```bash
# List all profiles
ebay auth profiles list
ebay auth profiles list --table

# Get details for a specific profile
ebay auth profiles get production

# Create a new profile
ebay auth profiles create sandbox

# Set a profile as the default
ebay auth profiles select sandbox

# Delete a profile
ebay auth profiles delete sandbox
ebay auth profiles delete sandbox --force

# Use a specific profile for any command
ebay auth login --profile sandbox
ebay auth status --profile production
```

### whoami - User Info

```bash
# Display current authenticated user
ebay whoami
ebay whoami
```

### Categories

Search and browse eBay marketplace categories using the Taxonomy API.

```bash
# List (search) categories by keyword
ebay categories list "trading card storage"
ebay categories list "lego parts" --table
ebay categories list "vintage toys" --limit 5
ebay categories list "electronics" --marketplace EBAY_GB

# Get details for a specific category
ebay categories get 183448
ebay categories get 183448 --table
ebay categories get 261328 --aspects

# Browse the category tree from a parent category
ebay categories tree 220
ebay categories tree 220 --table
ebay categories tree 220 --depth 2
ebay categories tree 183448 --flat
```

**Available fields:** categoryId, categoryName, level, path, isLeaf

### Marketplace Search

Marketplace search uses browser automation to scrape eBay's public sold and
completed listing pages. It does not require a logged-in browser session.

```bash
ebay listings search "LEGO 75357" --sold --limit 5
ebay listings search "LEGO bulk" --table
```

### Seller Commands

All seller-related commands are grouped under `ebay seller`. Run `ebay seller --help` to see all available subcommands.

#### Orders

Query and view eBay orders using the Fulfillment API.

```bash
# List all orders (JSON output)
ebay seller orders list

# List orders with table format
ebay seller orders list

# Limit results
ebay seller orders list --limit 10

# Paginate through results
ebay seller orders list --limit 50 --offset 100

# Filter by fulfillment status
ebay seller orders list --status NOT_STARTED
ebay seller orders list --status IN_PROGRESS
ebay seller orders list --status FULFILLED

# Get specific orders by ID
ebay seller orders list --order-ids "12-12345-12345,12-12345-12346"

# Show only specific fields
ebay seller orders list --properties "order_id,total,buyer"
ebay seller orders list --limit 10 --properties "order_id,status,created"

# Get details for a specific order
ebay seller orders get 12-12345-12345
ebay seller orders get 12-12345-12345

# Get shipping fulfillments for an order
ebay seller orders fulfillments 12-12345-12345
ebay seller orders fulfillments 12-12345-12345
```

#### Shipping Labels

Create and purchase shipping labels for eBay orders.

```bash
# Create a shipping label for an order
ebay seller shipping-labels create 12-12345-12345 \
  --weight 1.5 --length 10 --width 8 --height 4

# Create with interactive rate selection
ebay seller shipping-labels create 12-12345-12345 \
  --weight 2.0 --length 12 --width 10 --height 6 \
  --interactive

# Dry run (show quotes without purchasing)
ebay seller shipping-labels create 12-12345-12345 \
  --weight 1.5 --length 10 --width 8 --height 4 \
  --dry-run
```

#### Messages

Query and manage all eBay messages (inbox + buyer questions) using the Trading API.

```bash
# List all messages (combines inbox and buyer questions)
ebay seller messages list
ebay seller messages list --table
ebay seller messages list --start-date 2025-01-01 --end-date 2025-01-31
ebay seller messages list --limit 50 --offset 100

# Get specific message(s)
ebay seller messages get 123456
ebay seller messages get 123456,789012

# Reply to a message
ebay seller messages reply 123456 --body "Thank you for your question..."
ebay seller messages reply 123456 --body-file response.txt
echo "Thanks!" | ebay seller messages reply 123456 --body-file -
ebay seller messages reply 123456 --body "Yes" --public --email-copy
```

**Available fields:** message_id, sender, subject, body, source (inbox/buyer_question), created_date, item_id, item_title, message_status, responses

#### Shipping Quotes

Get shipping rates for a package without purchasing.

```bash
# Create a shipping quote
ebay seller shipping-quote create \
  --to-name "Jane Smith" --to-street "456 Oak Ave" \
  --to-city "New York" --to-state NY --to-zip 10001 \
  --weight 1.5 --length 10 --width 8 --height 4

# With table output
ebay seller shipping-quote create \
  --to-name "Jane Smith" --to-street "456 Oak Ave" \
  --to-city "New York" --to-state NY --to-zip 10001 \
  --weight 1.5 --length 10 --width 8 --height 4
```

#### Inventory Items

Manage your eBay inventory items using the Inventory API.

```bash
# List all inventory items
ebay seller inventory list
ebay seller inventory list

# Paginate through inventory
ebay seller inventory list --limit 50 --offset 100

# Show only specific fields
ebay seller inventory list --properties "sku,condition"

# Get a specific inventory item
ebay seller inventory get MY-SKU-123
ebay seller inventory get MY-SKU-123

# Create an inventory item
ebay seller inventory create SKU123 --title "My Product" --quantity 10 --condition NEW
ebay seller inventory create SKU123 --title "Used Widget" --condition USED_GOOD --quantity 5 --description "Gently used"

# Create from JSON file
ebay seller inventory create SKU123 --from-json payload.json

# Update an inventory item
ebay seller inventory update SKU123 --quantity 20
ebay seller inventory update SKU123 --title "New Title"

# Delete an inventory item
ebay seller inventory delete SKU123
ebay seller inventory delete SKU123 --force
```

#### Listings

Manage eBay listings with two creation modes:

- **Without `--publish`**: Creates a pseudo-draft using a template. The listing is published
  at $99,999 then immediately ended, making it visible in eBay Seller Hub for editing.
- **With `--publish`**: Creates an active listing that stays live. Requires price and all
  other API parameters.

**Required Fields:**

The CLI validates that all required eBay fields are provided (via CLI options or template):

| Field | CLI Option | Description |
|-------|------------|-------------|
| Format | `--format` | AUCTION or FIXED_PRICE |
| Category | `--category` | eBay category ID |
| Fulfillment Policy | `--fulfillment-policy` | Shipping policy ID |
| Payment Policy | `--payment-policy` | Payment policy ID |
| Return Policy | `--return-policy` | Return policy ID |
| Location | `--location` | Merchant location key |
| Title | `--title` | Listing title |
| Description | `--description` or `--description-file` | Item description (HTML supported) |
| Weight | `--weight` | Package weight in pounds |
| Dimensions | `--dimensions` | Package dimensions as LxWxH in inches |
| Price | `--price` | Required only with `--publish` |

Templates can provide these fields. Use `ebay seller templates get <name>` to see what a template provides.

```bash
# List all listings (active and pseudo-drafts)
ebay seller listings list
ebay seller listings list --table

# Filter by status (draft includes pseudo-drafts at $99,999)
ebay seller listings list --status active
ebay seller listings list --status draft

# Paginate and filter
ebay seller listings list --limit 50 --offset 100
ebay seller listings list --properties "sku,title,price,status"

# Get a specific listing by SKU
ebay seller listings get MY-SKU-123
ebay seller listings get MY-SKU-123 --table

# Create a pseudo-draft (template provides policies, category, format)
ebay seller listings create --sku SKU123 --template lego-bulk-auction \
  --weight 5 --dimensions 12x10x8 --photos-album "My Album"

# Create with all required fields explicitly
ebay seller listings create --sku SKU123 --template base \
  --format AUCTION --category 175673 --title "My Item" \
  --weight 2 --dimensions 10x8x6 \
  --fulfillment-policy 246932501026

# Create an active listing (with --publish, price required)
ebay seller listings create --sku SKU123 --template lego-bulk-auction \
  --weight 5 --dimensions 12x10x8 --publish --price 29.99

# Create with images
ebay seller listings create --sku SKU123 --template lego-bulk-auction \
  --weight 5 --dimensions 12x10x8 --image-folder "/path/to/photos/"
ebay seller listings create --sku SKU123 --template lego-bulk-auction \
  --weight 5 --dimensions 12x10x8 --photos-album "eBay Listing"

# Update a listing
ebay seller listings update SKU123 --price 39.99
ebay seller listings update SKU123 --quantity 5
ebay seller listings update SKU123 --title "New Title" --price 29.99

# Set final price on a pseudo-draft
ebay seller listings publish SKU123 --price 29.99

# Publish a real draft listing (legacy)
ebay seller listings publish SKU123

# Unpublish (withdraw) an active listing
ebay seller listings unpublish SKU123
ebay seller listings unpublish SKU123 --force

# Preview a listing before publishing
ebay seller listings preview SKU123
ebay seller listings preview SKU123 --output preview.html

# Delete a listing
ebay seller listings delete SKU123
ebay seller listings delete SKU123 --force
ebay seller listings delete SKU123 --keep-inventory  # Keep inventory item
```

**Template Support:**
- Use `--template` to load default values from a saved template
- CLI options override template values (e.g., `--price` overrides template price)
- See `ebay seller templates --help` for managing templates

**Image Upload Notes:**
- Use `--image-folder` to scan a directory for images (jpg, png, gif, webp)
- Use `--image` for specific local files or `--image-url` for remote URLs
- Use `--photos-album` to export and upload images from a macOS Photos app album
- All image options can be combined together
- Maximum 12 images per listing (eBay limit)
- Images are uploaded to eBay and associated with the listing
- Upload failures produce warnings but don't stop listing creation
- Uploaded images are stored locally in `~/.ebay/images.json`
- Photos album feature requires the `photos-app` CLI to be installed

**Description Options:**
- Use `--description` for short inline descriptions (overrides template)
- Use `--description-file` to read large descriptions from a file
- Use `--description-file -` to read from stdin (pipe large text)
- Examples:
  ```bash
  # Inline description
  ebay seller listings create --sku SKU123 --template vintage-camera --description "Short description"

  # From file
  ebay seller listings create --sku SKU123 --template vintage-camera --description-file ./description.txt

  # From stdin (piping)
  cat description.html | ebay seller listings create --sku SKU123 --template vintage-camera --description-file -
  ```

**Available fields:** sku, offer_id, item_id, title, description, price, currency, quantity, quantity_sold, status, format, category_id, condition, images, fulfillment_policy_id, payment_policy_id, return_policy_id, location_id, url

#### Images

Upload and manage images for eBay listings using the Media API.
Uploaded images expire after 30 days if not used in a listing.

```bash
# Upload from local file
ebay seller images upload --file /path/to/image.jpg
ebay seller images upload --file "/path/one.jpg,/path/two.jpg"

# Upload from URL
ebay seller images upload --url "https://example.com/image.jpg"
ebay seller images upload --url "https://a.com/1.jpg,https://b.com/2.jpg"

# List locally-stored uploaded images
ebay seller images list
ebay seller images list
ebay seller images list --properties "image_id,imageUrl,expirationDate"

# Get fresh metadata from eBay API
ebay seller images get IMAGE_ID
ebay seller images get IMAGE_ID
```

**Available fields:** image_id, imageUrl, expirationDate, source, original, uploaded_at

**Note:** Uploaded image metadata is stored locally in `~/.ebay/images.json` for easy retrieval.

#### Templates

Manage local listing templates to quickly create draft offers with consistent settings. Templates are stored in `~/.ebay/templates.json`.

```bash
# List all templates
ebay seller templates list
ebay seller templates list

# Get a specific template
ebay seller templates get vintage-camera
ebay seller templates get vintage-camera

# Create a template from CLI options
ebay seller templates create vintage-camera --category 625 --price 99.99 \
  --description "Template for vintage cameras"

# Create with policies
ebay seller templates create standard-listing --category 175673 --price 29.99 \
  --fulfillment-policy 12345 --payment-policy 67890 --return-policy 11111

# Create a template from an existing offer
ebay seller templates create from-offer --from-offer 1234567890

# Create a template from a JSON file
ebay seller templates create from-json --from-json template.json

# Update an existing template
ebay seller templates update vintage-camera --price 129.99
ebay seller templates update vintage-camera --category 31388

# Delete a template
ebay seller templates delete old-template
ebay seller templates delete old-template --force
```

**Template Creation Options:**
- `--category`, `-c`: eBay category ID
- `--price`, `-p`: Listing price
- `--currency`: Currency code (default: USD)
- `--quantity`, `-q`: Available quantity
- `--listing-description`: Listing description text
- `--fulfillment-policy`: Fulfillment policy ID
- `--payment-policy`: Payment policy ID
- `--return-policy`: Return policy ID
- `--location`: Merchant location key
- `--from-offer`: Create template from existing offer ID
- `--from-json`: Create template from JSON file

**Usage:** Use templates with `ebay seller listings create --template <name>` to create listings with preset values. CLI options override template defaults.

#### Policies

Manage fulfillment, payment, and return policies.

```bash
# Fulfillment Policies
ebay seller policies list
ebay seller policies list --limit 5
ebay seller policies list --properties "fulfillmentPolicyId,name"
ebay seller policies get 12345678
ebay seller policies create --name "Standard Shipping" --handling-days 3
ebay seller policies update 12345678 --handling-days 2
ebay seller policies delete 12345678
ebay seller policies delete 12345678 --force

# Payment Policies
ebay seller payment-policies list
ebay seller payment-policies list --limit 3 --properties "paymentPolicyId,name"
ebay seller payment-policies get 12345678

# Return Policies
ebay seller return-policies list
ebay seller return-policies list --properties "returnPolicyId,name,returnsAccepted"
ebay seller return-policies get 12345678
```

#### Locations

Manage merchant inventory locations where your inventory is stored.

```bash
# List all locations
ebay seller locations list
ebay seller locations list --table
ebay seller locations list --limit 10 --properties "merchantLocationKey,name,location"

# Get a specific location
ebay seller locations get LOCATION_KEY
ebay seller locations get LOCATION_KEY --table
```

**Available fields:** merchantLocationKey, name, location, merchantLocationStatus, locationTypes

#### Store

Manage your eBay store settings and categories.

```bash
# List all store categories
ebay seller store categories list
ebay seller store categories list --table
ebay seller store categories list --flat --table
ebay seller store categories list --limit 10
ebay seller store categories list --filter "categoryName:ilike:%lego%"

# Get a specific store category by ID
ebay seller store categories get 12345
ebay seller store categories get 12345 --table
```

**Available fields:** categoryId, categoryName, level, order, path

### Cache

```bash
ebay cache status
ebay cache clear
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping

### JSON Output Example

```bash
ebay seller orders list --limit 2
```

```json
{
  "orders": [
    {
      "orderId": "12-12345-12345",
      "orderFulfillmentStatus": "NOT_STARTED",
      "buyer": {
        "username": "buyer123"
      },
      "pricingSummary": {
        "total": {
          "value": "29.99",
          "currency": "USD"
        }
      }
    }
  ],
  "total": 100,
  "offset": 0,
  "limit": 2
}
```

### Table Output Example

```bash
ebay seller orders list --limit 5
```

```
Order ID         Status        Buyer        Total   Created
------------------------------------------------------------
12-12345-12345   NOT_STARTED   buyer123     29.99   2025-01-15
12-12345-12346   FULFILLED     buyer456     49.99   2025-01-14
```

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--limit` | `-l` | Maximum number of results (default: 100, max: 200 for most commands) |
| `--offset` | `-o` | Offset for pagination |
| `--properties` | `-p` | Comma-separated list of fields to include in output |
| `--status` | `-s` | Filter by fulfillment status |
| `--order-ids` | | Comma-separated list of order IDs |
| `--weight` | `-w` | Package weight in pounds (required for listings) |
| `--dimensions` | | Package dimensions as LxWxH in inches, e.g., 12x10x8 (required for listings) |
| `--version` | `-v` | Show version and exit |

## Configuration

Authentication profile files live under `~/.local/share/cli-tools/ebay/authentication_profiles/<profile>/`; non-auth defaults live in `~/.local/share/cli-tools/ebay/.env`:

```bash
ACTIVE=true

# OAuth App Credentials (from eBay Developer Portal)
CLIENT_ID=your_client_id
CLIENT_SECRET=your_client_secret

# Redirect URI (RuName from eBay)
REDIRECT_URI=your_ru_name

# Environment: "sandbox" or "production"
ENVIRONMENT=production

# OAuth tokens (managed automatically after login)
ACCESS_TOKEN=<access_token>
REFRESH_TOKEN=<refresh_token>
TOKEN_EXPIRES_AT=<timestamp>
```

### Getting eBay API Credentials

1. Go to [eBay Developer Portal](https://developer.ebay.com/)
2. Create an account or sign in
3. Go to [Application Keys](https://developer.ebay.com/my/keys)
4. Create a new application (or use existing)
5. Copy Client ID (App ID) and Client Secret (Cert ID)
6. Create a RuName (Redirect URI) under "User Tokens"

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### List Unfulfilled Orders

```bash
ebay seller orders list --status NOT_STARTED
```

### Get Order Details and Extract Line Items

```bash
ebay seller orders get 12-12345-12345 | jq '.lineItems[] | {title, quantity, price: .lineItemCost.value}'
```

### Export All Orders to JSON File

```bash
ebay seller orders list --limit 200 > orders.json
```

### Check Order Shipping Status

```bash
ebay seller orders fulfillments 12-12345-12345
```

### Script-Friendly JSON Output

```bash
# Get all order IDs
ebay seller orders list | jq -r '.orders[].orderId'

# Get total value of orders
ebay seller orders list | jq '[.orders[].pricingSummary.total.value | tonumber] | add'

# List buyer usernames
ebay seller orders list | jq -r '.orders[].buyer.username'
```

## Requirements

- Python 3.9+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests

## License

MIT
