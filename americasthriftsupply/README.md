# Americasthriftsupply CLI

## DESCRIPTION

A command-line interface for America's Thrift Supply (americasthriftsupply.com), a Shopify storefront selling LEGO mystery boxes and other liquidation/mystery-box products, reading the store's public, unauthenticated Shopify storefront JSON endpoints with no login, API key, or browser automation required. Use this CLI when you need scriptable, JSON-first access to the store's product catalog from agents, automation, or terminal workflows.

## Docs

- API documentation: https://shopify.dev/docs/api/ajax/reference/product
- Base URL: https://americasthriftsupply.com

## Authentication

None. This CLI reads the store's public storefront JSON endpoints
(`/products.json`, `/products/{handle}.js`, `/collections.json`,
`/collections/{handle}/products.json`), which any storefront visitor can read
without a login, API key, or session.

## Installation

```bash
cd <cli-tools-root>/americasthriftsupply
uv tool install -e . --force --refresh
```

After installation, the `americasthriftsupply` command will be available in your terminal.

## Quick Start

```bash
# List products
americasthriftsupply products list --limit 10

# Search the catalog (client-side --filter; the storefront has no full-text search JSON endpoint)
americasthriftsupply products list --filter "title:ilike:%lego%" --table

# Get one product by handle (richest detail: live availability, variants, images)
americasthriftsupply products get lego-mystery-box --table

# Browse collections (categories)
americasthriftsupply collections list --table
```

## Commands

### Products

```bash
# List products
americasthriftsupply products list --limit 25

# List products with table output
americasthriftsupply products list --limit 25 --table

# Search by title (client-side filter; substring, case-insensitive)
americasthriftsupply products list --filter "title:ilike:%mystery%"

# Filter by price (USD, derived from the first variant's price)
americasthriftsupply products list --filter "price_usd:lte:30"

# Filter by availability
americasthriftsupply products list --filter "available:eq:true"

# Restrict to one collection (server-side, via /collections/{handle}/products.json)
americasthriftsupply products list --collection mystery-box --table
americasthriftsupply products list --collection lego --table

# Sort newest-listed first (default) or oldest first with --desc
americasthriftsupply products list --sort newest --limit 25
americasthriftsupply products list --sort newest --desc --limit 25

# Sort by price low -> high (natural), or high -> low with --desc
americasthriftsupply products list --sort price --limit 25
americasthriftsupply products list --sort price --desc --limit 25

# Restrict output fields
americasthriftsupply products list --properties "handle,title,price_usd,available"

# Get a specific product by handle (from the product page URL:
# https://americasthriftsupply.com/products/lego-mystery-box?variant=...)
americasthriftsupply products get lego-mystery-box --table
```

### Collections

```bash
# List all collections (categories), e.g. 'mystery-box', 'lego', 'vintage-shop'
americasthriftsupply collections list --limit 50 --table

# Filter collections by name
americasthriftsupply collections list --filter "handle:ilike:%mystery%"

# Get one collection by handle
americasthriftsupply collections get mystery-box --table
```

## Output Formats

- JSON is the default output format.
- Add `--table` / `-t` for human-readable table output.

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display data as a table |
| `--limit` | `-l` | Maximum number of results |
| `--filter` | `-f` | Filter results using `field:op:value` syntax |
| `--properties` | `-p` | Restrict output to selected fields |
| `--sort` | `-s` | (`products list` only) Sort field: `newest` (default) or `price` |
| `--desc` | `-d` | (`products list` only) Reverse the sort field's natural direction |
| `--collection` | `-c` | (`products list` only) Restrict to one collection handle, server-side |
| `--version` | `-v` | Show version and exit |
| `--no-cache` |  | Bypass cached read responses for this execution |

### Sorting (`products list`)

The storefront's Shopify JSON endpoints ignore the `?sort_by=` parameter, so
`--sort`/`--desc` order the returned result set (up to `--limit`) **client-side**
on the returned fields. The canonical vocabulary:

| `--sort` | Natural direction (no `--desc`) | With `--desc` |
|----------|---------------------------------|---------------|
| `newest` (default) | newest-listed first (`created_at` desc) | oldest first |
| `price` | price low -> high | price high -> low |

An unknown `--sort` value is rejected with a clear error and a non-zero exit;
there is no silent fallback. Products without a resolved price sort after the
priced rows.

## Configuration

Non-authentication configuration is stored in `~/.local/share/cli-tools/americasthriftsupply/.env`. The source repo only carries `.env.example`.

This CLI has no reusable credentials to store or retrieve — it is a public,
unauthenticated read-only catalog client.

Root config variables:

```bash
# Optional: override the default API base URL
BASE_URL=https://americasthriftsupply.com

# Optional: response cache settings
CACHE_ENABLED=true
CACHE_TTL=3600
```

## Cache

```bash
# Clear cached read responses
americasthriftsupply cache clear

# Bypass the cache for one execution
americasthriftsupply --no-cache products list --limit 10
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Client/config/authentication error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### List Products and Filter with jq

```bash
americasthriftsupply products list --properties "handle,title,price_usd" | jq '.[].handle'
```

### Export Products to JSON File

```bash
americasthriftsupply products list --limit 200 > products.json
```

## Output Contract

`products list` and `products get` return the full Shopify product JSON object
(every field the API provides), plus these derived convenience fields:

| Field | Description |
|-------|-------------|
| `url` | Full product page URL (`{base_url}/products/{handle}`) |
| `price_usd` | First variant's price in US dollars (float) |
| `price_min_usd` / `price_max_usd` | Min/max variant price in USD (`products list` only) |
| `available` | True if any variant is in stock. `products list` sources this from `/products.json`; may be `None` if the API response for that record didn't report per-variant availability |
| `variant_count` | Number of variants |
| `image_count` | Number of images (`products list` only) |
| `image_urls` | Flat list of image URLs |
| `compare_at_price_usd` | Original/compare-at price in USD (`products get` only) |

`products get <handle>` uses the richer `/products/{handle}.js` endpoint, which
always reports live per-variant `available` status and prices in cents
(normalized here to `price_usd`).

`collections list` returns the full Shopify collection JSON object plus a
derived `url` field.

Update `normalize_product()`, `normalize_product_detail()`, and
`normalize_collection()` in `client.py` if the store's response shape changes.

## Requirements

- Python 3.11+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests

## License

MIT
