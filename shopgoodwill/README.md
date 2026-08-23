# ShopGoodwill CLI

## DESCRIPTION

The `shopgoodwill` CLI provides a command-line interface for ShopGoodwill.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Installation

```bash
# Clone and install
cd shopgoodwill
pip install -e .
```

After installation, the `shopgoodwill` command will be available in your terminal.

## Quick Start

```bash
# Search for items (no authentication required)
shopgoodwill search query "vintage camera"

# Get item details
shopgoodwill search get 123456789

# Login to your account (required for bidding features)
shopgoodwill auth login
```

## Commands

### Authentication

Authentication is optional for searching but required for account-specific features.

```bash
# Login with prompts
shopgoodwill auth login

# Login with credentials
shopgoodwill auth login -u your@email.com -p yourpassword

# Check authentication status
shopgoodwill auth status

# Validate token with API
shopgoodwill auth status --validate

# Logout and clear credentials
shopgoodwill auth logout
```

### Search

Search ShopGoodwill listings with various filters and sorting options.

```bash
# Basic search
shopgoodwill search query "nintendo"

# Table format output
shopgoodwill search query "vintage watch"

# Filter by price
shopgoodwill search query "laptop" --min-price 50 --max-price 200

# Sort field (default: newest = newest-listed first); --desc reverses it
shopgoodwill search query "furniture" --sort price --desc

# Pagination
shopgoodwill search query "books" --page 2 --limit 20

# Filter options
shopgoodwill search query "electronics" --buy-now      # Buy-now items only
shopgoodwill search query "antiques" --shipping        # Items that ship
shopgoodwill search query "furniture" --pickup         # Pickup only items
shopgoodwill search query "sold items" --closed        # Include closed auctions
```

### Item Details

Get detailed information about a specific listing.

```bash
# JSON output (default)
shopgoodwill search get 123456789

# Table format
shopgoodwill search get 123456789
```

When ShopGoodwill enables shipping calculation for a listing, item detail output
includes a `shippingEstimate` object calculated to ZIP `47725`. If ShopGoodwill
returns listing details but rejects the shipping estimate (for example,
`PACKAGE.WEIGHT.INVALID`), the command still returns the listing with
`shippingEstimate: null`, `shippingEstimateUnavailable: true`, and
`shippingEstimateError`.

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping

### JSON Output Example

```bash
shopgoodwill search query "camera" --limit 2
```

```json
{
  "total_count": 1547,
  "page": 1,
  "page_size": 2,
  "items": [
    {
      "itemId": 123456789,
      "title": "Vintage Polaroid Camera",
      "currentPrice": 15.50,
      "numBids": 3,
      "endTime": "2025-12-25T10:30:00",
      "sellerCity": "Seattle",
      "sellerState": "WA"
    }
  ]
}
```

### Table Output Example

```bash
shopgoodwill search query "camera" --limit 5
```

```
Found 1547 items (showing 5)
ID          Title                                     Price    Bids  Ends         Location
-------------------------------------------------------------------------------------------
123456789   Vintage Polaroid Camera                   $15.50   3     12/25 10:30  Seattle, WA
123456790   Canon DSLR Camera Body                    $45.00   7     12/24 14:00  Portland, OR
```

## Search Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--page` | `-p` | Page number (default: 1) |
| `--limit` | `-l` | Results per page (default: 40). `--sort newest`: up to 200. `--sort price/ending/bids`: max 40 |
| `--min-price` | | Minimum price filter |
| `--max-price` | | Maximum price filter |
| `--sort` | `-s` | Sort field (default: `newest`). Valid: `newest`, `price`, `ending`, `bids` |
| `--desc` | `-d` | Reverse the sort field's natural direction |
| `--buy-now` | | Only show buy-now items |
| `--shipping` | | Only show items that ship |
| `--pickup` | | Only show pickup-only items |
| `--closed` | | Include closed auctions |

### Sort Fields

Sorting follows the Source-CLI Sort Standard. `--sort` selects a field; each field
has a natural direction, and `--desc` reverses it. The default is `newest`, which
returns the most recently listed items first (what incremental crawlers rely on).
An unknown `--sort` value is rejected with an error listing the valid values and a
non-zero exit — there is no silent fallback.

| Field | Natural (no `--desc`) | With `--desc` |
|-------|-----------------------|---------------|
| `newest` (default) | most recently listed first | oldest listed first |
| `price` | low → high | high → low |
| `ending` | soonest ending first | latest ending first |
| `bids` | fewest bids first | most bids first |

`ending`, `bids`, and `price` map to ShopGoodwill's real integer sort columns
(`EndingDate=1`, `NumberofBids=3`, `BidPrice=4`) plus a descending flag, matching
the site's own sort dropdown.

**`newest` is a best-effort client-side refine (Sort Standard Rule 5).**
ShopGoodwill exposes no true listing-date sort column — its "Newly Listed" option
is really *ending-date descending*, which only approximates recency because auction
durations vary. So `--sort newest` fetches the "Newly Listed" window (at least
`--page * --limit` items, minimum 100) and then sorts that window client-side by
each item's real `startTime` (listing date) so results are genuinely
newest-listed-first, then slices out the requested `--page`. The window is capped
at 200 fetched items total (5 underlying API pages), so `(--page - 1) * --limit`
offsets beyond 200 return no results — this is the real ceiling for `--sort newest`,
regardless of `--limit`.

## Configuration

Authentication profile files live under `~/.local/share/cli-tools/shopgoodwill/authentication_profiles/<profile>/`; non-auth defaults live in `~/.local/share/cli-tools/shopgoodwill/.env`:

```
SHOPGOODWILL_USERNAME=your@email.com
SHOPGOODWILL_PASSWORD=yourpassword
SHOPGOODWILL_ACCESS_TOKEN=<jwt_token>
```

You can also set these as environment variables directly.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### Find Deals Ending Soon

```bash
shopgoodwill search query "electronics" --sort ending
```

### Find Popular Items

```bash
shopgoodwill search query "vintage" --sort bids --desc
```

### Search with Price Range

```bash
shopgoodwill search query "iphone" --min-price 100 --max-price 300 --shipping
```

### Script-Friendly JSON Output

```bash
# Get item IDs for processing
shopgoodwill search query "cameras" | jq '.items[].itemId'

# Get cheapest items
shopgoodwill search query "books" --sort price | jq '.items[:5]'
```

## Requirements

- Python 3.9+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests
  - pycryptodomex

## License

MIT

## Additional Commands

### Cache

```bash
shopgoodwill cache --help
```
