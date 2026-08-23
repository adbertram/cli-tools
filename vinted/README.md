# Vinted CLI

## DESCRIPTION

A command-line interface for the Vinted marketplace. It searches Vinted catalog listings and reads single listing detail through the internal API that the Vinted web app itself calls. Use this CLI when you need scriptable, JSON-first Vinted search from agents, automation, or terminal workflows.

## Docs

- Vinted has no usable public catalog API. The official Vinted Pro Integrations API (https://pro-docs.svc.vinted.com/) is allowlist-only, seller-side, and has no catalog search.
- This CLI calls the site's internal endpoint `GET /api/v2/catalog/items`, the same one the Vinted web front end uses.
- Base URL: https://www.vinted.com

## Authentication

No Vinted account is needed. There is no password, API key, or token.

Cloudflare fronts Vinted and challenges clients it does not trust, so a plain
HTTP client is refused. Run this once:

```bash
vinted auth login
```

That opens one real Chrome window, which passes the challenge and saves a
Cloudflare clearance into a persistent profile. Every later command reuses that
profile headless, so no window opens again. Check the session with
`vinted auth status`, and refresh it with `vinted auth login --force`.

## Installation

```bash
cd <cli-tools-root>/vinted
uv tool install -e . --force --refresh
```

After installation, the `vinted` command will be available in your terminal.

## Quick Start

```bash
# Search listings, newest first
vinted listings search "lego bulk lot" --limit 10

# Show table output
vinted listings search "lego bulk lot" --limit 10 --table

# Get one listing
vinted listings get 9571854910 --table
```

Results are strictly newest first by default. Every record carries `listed_at`,
so a caller can verify the order.

## Commands

### Listings

```bash
# Search listings (newest listed first by default)
vinted listings search "lego bulk lot" --limit 25

# Search with table output
vinted listings search "lego bulk lot" --limit 25 --table

# Cheapest first
vinted listings search "lego" --sort price --limit 10

# Most expensive first
vinted listings search "lego" --sort price --desc --limit 10

# Vinted relevance order
vinted listings search "lego star wars" --sort relevance --limit 10

# Price range in a currency
vinted listings search "lego" --min-price 5 --max-price 25 --currency USD

# Condition, repeatable
vinted listings search "lego" --condition new-with-tags --condition good

# Vinted catalog, brand, size, and color IDs
vinted listings search "lego" --catalog-id 1920 --brand-id 12 --size-id 7 --color-id 3

# Post-filter the returned records
vinted listings search "lego" --filter "brand:eq:LEGO" --filter "title:contains:bulk"

# Restrict output fields
vinted listings search "lego" --properties "id,title,price,url"

# Add the shipping summary (one extra page request per listing)
vinted listings search "lego" --limit 10 --include-shipping

# Get a specific listing by ID
vinted listings get 9571854910

# Get a listing as a table
vinted listings get 9571854910 --table

# Get selected fields only
vinted listings get 9571854910 --properties "id,title,description"
```

### Auth

```bash
# Open one real Chrome window to clear the Cloudflare check
vinted auth login

# Refresh a stale session
vinted auth login --force

# Check the saved session
vinted auth status
```

### Cache

```bash
# Clear cached read responses
vinted cache clear

# Bypass the cache for one execution
vinted --no-cache listings search "lego" --limit 10
```

## Sorting

`--sort` takes one field name. `--desc` reverses that field's natural
direction. Do not use directional field names such as `price_high`.

| `--sort` | Natural order (no `--desc`) | With `--desc` |
|----------|------------------------------|---------------|
| `newest` (default) | Most recently listed first | Rejected. Vinted has no oldest-first order. |
| `price` | Low to high | High to low |
| `relevance` | Vinted relevance order | Rejected. Vinted has no reverse relevance order. |

An unknown `--sort` value fails with exit code 1 and lists the valid values.

## Conditions

`--condition` is repeatable and maps to the Vinted `status_ids` parameter.

| `--condition` | Vinted label |
|---------------|--------------|
| `new-with-tags` | New with tags |
| `new-without-tags` | New without tags |
| `very-good` | Very good |
| `good` | Good |
| `satisfactory` | Satisfactory |

## Output Formats

- JSON is the default output format.
- Add `--table` / `-t` for human-readable table output.

### JSON Output Example

```bash
vinted listings search "lego" --limit 1 --properties "id,title,price,currency,url"
```

```json
[
  {
    "id": 9571933947,
    "title": "LEGO Friends Vet Clinic",
    "price": "12.0",
    "currency": "USD",
    "url": "https://www.vinted.com/items/9571933947-lego-friends-vet-clinic"
  }
]
```

### Table Output Example

```bash
vinted listings search "lego bulk lot" --limit 5 --table
```

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--sort` | `-s` | Sort field: `newest`, `price`, `relevance` |
| `--desc` | `-d` | Reverse the sort field's natural direction |
| `--condition` | `-c` | Item condition, repeatable |
| `--min-price` |  | Minimum price |
| `--max-price` |  | Maximum price |
| `--currency` |  | Currency code for the price range |
| `--catalog-id` |  | Vinted catalog (category) IDs, comma-separated |
| `--brand-id` |  | Vinted brand IDs, comma-separated |
| `--size-id` |  | Vinted size IDs, comma-separated |
| `--color-id` |  | Vinted color IDs, comma-separated |
| `--include-shipping` |  | Add the shipping summary. One page request per listing. |
| `--table` | `-t` | Display data as a table |
| `--limit` | `-l` | Maximum number of results |
| `--filter` | `-f` | Filter results using `field:op:value` syntax |
| `--properties` | `-p` | Restrict output to selected fields |
| `--version` | `-v` | Show version and exit |
| `--no-cache` |  | Bypass cached read responses for this execution |

## Configuration

Non-authentication configuration is stored in `~/.local/share/cli-tools/vinted/.env`. The source repo only carries `.env.example`.

This CLI stores no credentials. Reusable CLI credentials for other tools are governed by the user-level `cli-tool` skill's `references/secrets.md`.

Do not put reusable credentials in any `.env` file. Store and retrieve them through `<cli-tools-root>/_repo/_secret-manager/secrets.sh`. `.env` files are limited to non-secret config and CLI-managed runtime auth state.

Root config variables:

```bash
# Marketplace root. Change it to search another Vinted country site.
BASE_URL=https://www.vinted.com

# Optional: response cache settings
CACHE_ENABLED=true
CACHE_TTL=3600
```

### Other Vinted country sites

Each Vinted country site holds its own inventory and currency. Point `BASE_URL`
at the site you want, for example `https://www.vinted.co.uk` or
`https://www.vinted.fr`.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Client/config error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### Pull listing IDs with jq

```bash
vinted listings search "lego" --limit 50 --properties "id" | jq '.[].id'
```

### Export a search to a JSON file

```bash
vinted listings search "lego bulk lot" --limit 200 > listings.json
```

### Find cheap new-with-tags stock

```bash
vinted listings search "lego" --condition new-with-tags --sort price --max-price 15 --currency USD --limit 20 --table
```

## Output Contract

### `listings search` record

| Field | Description |
|-------|-------------|
| `id` | Vinted listing ID |
| `title` | Listing title |
| `url` | Canonical listing URL |
| `listed_at` | Listing time, ISO 8601 UTC. The signal the newest sort uses. |
| `price` | Item price |
| `currency` | Price currency code |
| `total_price` | Price including the buyer protection fee |
| `brand` | Brand name |
| `size` | Size label |
| `condition` | Condition label |
| `favourite_count` | Number of users who favourited the listing |
| `view_count` | Listing view count |
| `is_visible` | Whether the listing is visible |
| `promoted` | Whether the seller promoted the listing |
| `seller_id` | Seller ID |
| `seller_login` | Seller username |
| `seller_url` | Seller profile URL |
| `photo_url` | Primary photo URL |
| `shipping` | Shipping figures. Only with `--include-shipping`, otherwise absent. |

### `listings get` record

Vinted blocks `GET /api/v2/items/{id}` for anonymous sessions, so detail comes
from the public listing page. The page is a React Server Component page, and the
CLI reads its data payload. That payload adds the description, category, color,
and total price that catalog search omits. It does not carry the seller login or
the view count.

| Field | Description |
|-------|-------------|
| `id` | Vinted listing ID |
| `title` | Listing title |
| `url` | Canonical listing URL |
| `description` | Seller description |
| `price` | Seller asking price |
| `currency` | Price currency code |
| `total_price` | Price including the buyer protection fee |
| `brand` | Brand name |
| `category` | Category path, for example `Kids / Toys / Blocks & building toys` |
| `catalog_id` | Vinted catalog ID. Pass it to `--catalog-id` on a search. |
| `seller_id` | Seller ID |
| `size` | Size label. `null` when the listing has no size. |
| `condition` | Condition label, for example `Very good` |
| `color` | Color label |
| `is_reserved` | `true` when a buyer reserved the listing |
| `is_hidden` | `true` when the seller hid the listing |
| `is_closed` | `true` when the listing is closed |
| `shipping` | Shipping figures, always present. `null` if the listing has no shipping. |
| `photo_url` | Primary photo URL |

The `condition` value is the same label that `listings search` reports, so a
search result and a detail record compare directly.

## Shipping

Shipping is on the item page only, so `listings search` omits it by default.
Pass `--include-shipping` to add it. `listings get` always includes it, because
that command already reads the item page.

No account and no zip code are needed. Vinted renders the shipping figures into
the item page on the server, with no buyer address involved.

The `shipping` record:

| Field | Description |
|-------|-------------|
| `price` | What the buyer pays for shipping, for example `"0"` |
| `currency` | Shipping currency code |
| `discount` | The discount amount Vinted applied. `null` when there is none. |
| `free` | Vinted's own `isFreeShipping` flag |
| `pickup_only` | `true` when the buyer must collect the item |
| `multiple_options` | `true` when the listing offers more than one option |

A listing with no shipping summary reports `shipping: null`.

The figures come from the page's `shippingDetails` summary. Vinted also renders
a lower level shipping object twice, and those two copies can carry two
different undiscounted prices for the same listing. The CLI does not report an
undiscounted price, because there is no way to tell which copy the buyer sees.

### Why search cannot carry shipping

`GET /api/v2/catalog/items` returns 23 fields per listing and none of them is
shipping. The search results page carries none either. The item page is the only
source, so `--include-shipping` reads one item page per listing.

### What `--include-shipping` costs

One item page per listing, about 1.5 seconds each. A `--limit 25` search takes
roughly 40 seconds. Keep `--limit` small and leave the cache on.

### What this is not

`price` is Vinted's figure for a buyer with no address, so it is an estimate.
Vinted computes the exact cost at checkout, where it knows the delivery method
and the address. That needs a signed-in account and a purchase flow, which this
CLI does not do.

## Rate Limits

Vinted answers HTTP 429 when requests arrive too fast. Every request the CLI
sends passes through one rate limiter, so the CLI controls its own pace.

| Behaviour | Value |
|-----------|-------|
| Minimum gap between requests | 0.9 seconds |
| On HTTP 429 or 503 | Double the gap, wait, and retry the same request |
| Backoff delay | 2s, 4s, 8s, 16s, capped at 60s. A `Retry-After` header wins. |
| Retries per request | 4 |
| Maximum gap | 30 seconds |
| Recovery | Halve the gap after 5 clean requests, down to 0.9 seconds |

The limiter holds one gap for the whole command. Vinted pushback slows every
later request, and a run of clean answers speeds them up again. A command fails
only when Vinted still throttles it after all four retries.

## Limitations

- The endpoints are internal to Vinted and are not a published contract. Vinted can change them without notice.
- Vinted caps the catalog page size at 96. `--limit` pages through automatically, up to 50 pages. `--limit` above 4800 fails with an error rather than a silent cut.
- A search stops early when two pages in a row add no new listing. Vinted reports a large page total while it repeats the same listings, so without that stop one search could issue thousands of requests.
- Vinted ignores an unrecognized `order` value instead of rejecting it, so the CLI validates `--sort` before the request.
- Vinted also ignores an impossible price range and an unknown catalog ID. The CLI rejects a negative price and an inverted range before the request. It cannot check a catalog, brand, size, or color ID, so a wrong ID returns unfiltered results.
- Cloudflare fronts Vinted. Heavy use with `--no-cache` can raise a fresh challenge. The response cache absorbs repeated searches, so leave it on. Run `vinted auth login --force` if a command reports a Cloudflare check.
- Every listing on www.vinted.com currently reports `free: true`, because Vinted US discounts the shipping price to 0. The parser reads a priced listing correctly, but only the free case was confirmed against the live site.
- The item page is a React Server Component page, so `listings get` and the shipping figures come from its data payload. Vinted can change that payload without notice. The CLI does not read the `application/ld+json` block, because Vinted omits that block on a hidden listing.
- Some listings carry no shipping summary at all. Those report `shipping: null`. Confirmed live on electronics and furniture listings.
- Vinted's own newest-first order is only approximate. It injects some listings out of order, so the CLI sorts the result on `listed_at`. That sort covers the listings the command fetched, not the whole catalog.
- The catalog is ordered newest-first. A listing added between two page requests shifts the offset window, so pages can repeat a listing. The CLI keeps results unique by ID, which means a large `--limit` can return slightly fewer rows than requested.
- The response cache is keyed on the marketplace, so changing `BASE_URL` does not serve another country site's listings.

## Requirements

- Python 3.11+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests

## License

MIT
