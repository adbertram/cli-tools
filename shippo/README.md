# Shippo CLI

A command-line interface for the [Shippo API](https://docs.goshippo.com/) - Create USPS shipping labels, get rates, and track packages.

## Installation

```bash
cd shippo
pip install -e .
```

After installation, the `shippo` command will be available in your terminal.

## Quick Start

```bash
# 1. Authenticate with Shippo (get your API key from https://apps.goshippo.com/settings/api)
shippo auth login

# 2. Create a shipment and get rates
shippo shipments create \
  --from-name "Your Name" --from-address "123 Main St" \
  --from-city "San Francisco" --from-state CA --from-zip 94102 \
  --to-name "Recipient" --to-address "456 Oak Ave" \
  --to-city "Los Angeles" --to-state CA --to-zip 90001 \
  --weight 8

# 3. Purchase a label using a rate ID from the shipment
shippo labels create RATE_ID

# 4. Track the shipment
shippo tracking get TRACKING_NUMBER
```

## Commands

### Authentication

```bash
# Login with API key (prompts for key)
shippo auth login

# Login with API key directly
shippo auth login --api-key YOUR_API_KEY

# Force re-authentication
shippo auth login --force

# Check authentication status
shippo auth status
shippo auth status --table

# Clear stored credentials
shippo auth logout
```

### Profiles

```bash
# List all profiles
shippo auth profiles list
shippo auth profiles list --table

# Create a new profile
shippo auth profiles create staging

# Select active profile
shippo auth profiles select staging

# Delete a profile
shippo auth profiles delete staging
```

### Addresses

```bash
# List saved addresses
shippo addresses list
shippo addresses list --table
shippo addresses list --limit 10
shippo addresses list --properties "object_id,name,city,state"

# Get address details
shippo addresses get ADDRESS_ID
shippo addresses get ADDRESS_ID --table

# Create an address
shippo addresses create \
  -n "John Doe" \
  -a "123 Main St" \
  -c "San Francisco" \
  -s CA \
  -z 94102

# Create and validate an address
shippo addresses create \
  -n "Jane Doe" \
  -a "456 Oak Ave" \
  -c "Los Angeles" \
  -s CA \
  -z 90001 \
  --validate

# Validate an existing address
shippo addresses validate ADDRESS_ID
```

### Shipments

```bash
# List shipments
shippo shipments list
shippo shipments list --table
shippo shipments list --limit 10

# Get shipment details (includes rates)
shippo shipments get SHIPMENT_ID
shippo shipments get SHIPMENT_ID --table

# Create a shipment and get rates
shippo shipments create \
  --from-name "Sender Name" \
  --from-address "123 Main St" \
  --from-city "San Francisco" \
  --from-state CA \
  --from-zip 94102 \
  --to-name "Recipient Name" \
  --to-address "456 Oak Ave" \
  --to-city "Los Angeles" \
  --to-state CA \
  --to-zip 90001

# Create with custom parcel dimensions
shippo shipments create \
  --from-name "Sender" --from-address "100 First St" \
  --from-city "New York" --from-state NY --from-zip 10001 \
  --to-name "Recipient" --to-address "200 Second Ave" \
  --to-city "Chicago" --to-state IL --to-zip 60601 \
  --length 10 --width 8 --height 4 --weight 16

# Display rates as table
shippo shipments create ... --table
```

### Rates

```bash
# List rates for a shipment
shippo rates list SHIPMENT_ID
shippo rates list SHIPMENT_ID --table

# Filter rates by provider
shippo rates list SHIPMENT_ID --filter "provider:usps"

# Filter rates by service
shippo rates list SHIPMENT_ID --filter "service:priority"

# Get rate details
shippo rates get RATE_ID
shippo rates get RATE_ID --table

# Estimate shipping rates (no label created)
# Weight is in OUNCES (4oz = 0.25 lbs, 8oz = 0.5 lbs, 16oz = 1 lb)

# Domestic US estimate
shippo rates estimate --weight 8 --to-country US --to-zip 90210

# International estimate (customs auto-generated with defaults)
shippo rates estimate --weight 4 --to-country FR
shippo rates estimate --weight 4 --to-country CA --filter "provider:usps"
shippo rates estimate --weight 8 --to-country GB --json

# International with custom item value
shippo rates estimate --weight 8 --to-country FR --value 50

# International with custom description (for customs)
shippo rates estimate --weight 4 --to-country DE --description "Collectible toys" --value 30
```

### Labels (Transactions)

```bash
# List purchased labels
shippo labels list
shippo labels list --table
shippo labels list --limit 20

# Filter labels by status
shippo labels list --filter "status:success"
shippo labels list --filter "tracking_status:delivered"

# Get label details
shippo labels get TRANSACTION_ID
shippo labels get TRANSACTION_ID --table

# Purchase a label from a rate
shippo labels create RATE_ID

# Purchase with PNG format
shippo labels create RATE_ID --format PNG

# Purchase with metadata
shippo labels create RATE_ID --metadata "Order #12345"

# Download a label file
shippo labels download TRANSACTION_ID
shippo labels download TRANSACTION_ID -o my_label.pdf

# Void (refund) a label
shippo labels void TRANSACTION_ID
```

### Tracking

```bash
# Get tracking information
shippo tracking get TRACKING_NUMBER
shippo tracking get TRACKING_NUMBER --carrier usps
shippo tracking get TRACKING_NUMBER --table

# Get tracking for UPS
shippo tracking get 1Z999AA10123456784 --carrier ups

# Register for tracking webhooks
shippo tracking register TRACKING_NUMBER
shippo tracking register TRACKING_NUMBER --carrier usps
shippo tracking register TRACKING_NUMBER --metadata "Order #123"
```

### Carriers

```bash
# List all carrier accounts
shippo carriers list
shippo carriers list --table

# Filter by carrier
shippo carriers list --carrier fedex
shippo carriers list --carrier usps

# Include service levels
shippo carriers list --service-levels
shippo carriers list --carrier fedex --service-levels

# Custom fields
shippo carriers list --properties "carrier,carrier_name,active"

# Get carrier account details
shippo carriers get CARRIER_ACCOUNT_ID
shippo carriers get CARRIER_ACCOUNT_ID --table
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping
- **Table** (`--table` or `-t`): Human-readable table format

### JSON Output Example

```bash
shippo addresses list | jq '.[0]'
```

### Table Output Example

```bash
shippo labels list --table
```

## Common Options

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display output as table |
| `--limit` | `-l` | Maximum number of results |
| `--filter` | `-f` | Filter results (field:value) |
| `--properties` | `-p` | Comma-separated fields to include |
| `--version` | `-v` | Show version and exit |

## Configuration

Authentication profile files live under `~/.local/share/cli-tools/shippo/authentication_profiles/<profile>/`; non-auth defaults live in `~/.local/share/cli-tools/shippo/.env`:

```bash
ACTIVE=true

# API Key (get from https://apps.goshippo.com/settings/api)
API_KEY=shippo_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Optional: API base URL (defaults to https://api.goshippo.com)
BASE_URL=https://api.goshippo.com
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Complete Workflow Example

```bash
# 1. Create a shipment to get rates
shippo shipments create \
  --from-name "ACME Corp" \
  --from-address "123 Business Dr" \
  --from-city "San Francisco" \
  --from-state CA \
  --from-zip 94102 \
  --to-name "Customer Name" \
  --to-address "456 Residential St" \
  --to-city "Los Angeles" \
  --to-state CA \
  --to-zip 90001 \
  --weight 12 \
  --table

# 2. Get the rate ID from output and purchase label
shippo labels create RATE_ID_HERE

# 3. Download the label
shippo labels download TRANSACTION_ID

# 4. Track the shipment
shippo tracking get TRACKING_NUMBER --table
```

## Filtering with jq

```bash
# Get all tracking numbers from labels
shippo labels list | jq '.[].tracking_number'

# Get cheapest rate for a shipment
shippo shipments get SHIPMENT_ID | jq '.rates | sort_by(.amount | tonumber) | .[0]'

# Export addresses to CSV
shippo addresses list | jq -r '.[] | [.object_id, .name, .city, .state] | @csv'
```

## Models

This CLI uses Pydantic models for type-safe data handling:

| Model | Description |
|-------|-------------|
| `Address` | Saved addresses with validation results |
| `Parcel` | Package dimensions and weight |
| `Shipment` | Shipment with addresses, parcels, and rates |
| `Rate` | Shipping rate with price and delivery estimate |
| `Transaction` | Purchased label with tracking number |
| `TrackingInfo` | Tracking status and history |
| `Refund` | Label void/refund status |
| `CarrierAccount` | Connected carrier account (USPS, FedEx, UPS, etc.) |

## Requirements

- Python 3.9+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests
  - pydantic
  - shippo (official SDK)

## License

MIT

## Cache

```bash
shippo cache status
shippo cache clear
```
