# StockX CLI

## DESCRIPTION

A browser-automation command-line interface for StockX that provides read-only,
JSON-first access to the StockX catalog and its live resale market. It searches
products by keyword (`products search`), browses the catalog with no keyword
(`products list`), returns one product's catalog record (`products get`), and
returns live asks, bids, and sales data for one product (`products market`).
Use this CLI when you need repeatable, scriptable StockX market data without
clicking through the website.

## Docs

- Website: https://stockx.com
- Public API program: https://developer.stockx.com

## Data source

StockX's public REST API (developer.stockx.com) is an approval-gated seller and
catalog program, not a general search API. Its web app instead posts every
browse and product query to an internal GraphQL endpoint,
`POST https://stockx.com/api/graphql`, behind Cloudflare.

This CLI runs those requests inside a live stockx.com page through an in-page
`fetch`, so each one carries the real browser's Cloudflare clearance, cookies,
and network stack. Navigation runs through the shared
`cli_tools_shared.BrowserAutomation` engine (CDP / browser-harness).

Operations used (validated against the live site during CLI creation):

| Command | GraphQL operation | Returns |
|---------|-------------------|---------|
| `products search` | `getDiscoveryData` | `browse.results.edges[].node` |
| `products list` | `getDiscoveryData` (null `query`) | the same shape, for catalog browse |
| `products get` | `GetProduct` | `product` (catalog record) |
| `products market` | `GetMarketData` | `product.market` (asks, bids, sales, per-variant market) |

### User agent

stockx.com serves a "Please login to continue" bot wall to the default
`HeadlessChrome/<v>` User-Agent (verified live: page title `Error`, body
"Please log in to verify you are not a bot"). `Config.browser_user_agent` pins
the installed Chrome's real UA so the same identity is presented headed and
headless; with it, the full public catalog loads with no StockX account.

### Persisted queries

StockX uses Apollo **automatic persisted queries**: the request body carries
only `operationName`, `variables`, and
`extensions.persistedQuery.sha256Hash` — never the query text. Sending a
hand-written query document is rejected by Cloudflare with HTTP 403 (verified),
so the hash is mandatory.

Those hashes are build artifacts that change whenever StockX ships a new web
bundle, so this CLI hardcodes none of them. It reads the current hash out of
the app's own outgoing request by installing a `fetch` interceptor and driving
one client-side route change, then caches the result against StockX's own
`appVersion` (from `__NEXT_DATA__`). A new StockX deploy therefore produces a
cache miss and a fresh capture — one execution path, no stale-hash recovery
branch.

`/api/graphql` returns HTTP 404 for a bare `content-type` request and HTTP 200
once the app's client headers are present (verified). Every header value —
`App-Version`, `x-stockx-device-id`, `x-stockx-session-id` — is read from the
live page's `__NEXT_DATA__`, so nothing is minted or guessed.

### Filters and sort

Filters are `{id, selectedValues}` entries. Each id was confirmed by StockX's
own echo, where `browse.filtersConfig` reports the applied selection:

| Option | filter id | Verified values |
|--------|-----------|-----------------|
| `--brand` | `brand` | slugs, e.g. `nike`, `adidas`, `jordan` |
| `--gender` | `gender` | `men`, `women`, `unisex`, `kids` |
| `--category` | `category` | `sneakers`, `apparel`, `accessories`, `collectibles`, `shoes`, `trading-cards` |
| `--color` | `color` | `black`, `white`, `multi`, `blue`, `green`, `grey`, `red`, `pink`, `brown`, `orange`, `yellow`, `purple` |
| `--activity` | `activity` | slugs, e.g. `basketball`, `running`, `soccer` |
| `--below-retail` | `below-retail` | `true` |
| `--xpress-ship` | `xpress-ship` | `true` |
| `--min-price` / `--max-price` | `lowest-ask-range` | two values `[min, max]`; a single `min-max` string returns HTTP 400 |

**StockX silently ignores unknown filter ids, unknown filter values, and
unknown sort ids**, returning the unfiltered default instead of an error
(verified: `brand=Nike` in display case and `sort=bogus_sort` both echoed no
selection). Because a silently dropped filter is worse than a failure, this CLI
validates every option against the vocabulary StockX itself publishes.

`products search` follows the **Source-CLI Sort Standard**: `--sort/-s <field>`
(default `featured`) plus `--desc/-d`. Valid fields are `featured`,
`lowest-ask`, `highest-bid`, and `release-date`. StockX bakes direction into the
sort id itself: `sort.order` exists in the schema as a `BrowseSortOrder` enum,
but supplying it alongside a directional id silently reverts the applied sort to
`featured` (verified live), so it is never sent. No StockX sort publishes a
reverse order, so `--desc` is always rejected with a message naming the
alternative — use `--sort highest-bid` instead of `--sort lowest-ask --desc`.

Pagination is page-index based; `--limit` is merged across pages under the hood
and deduped by product id. StockX caps a result window at 1000 products.

## Installation

```bash
cd <cli-tools-root>/stockx
uv tool install -e . --force --refresh
```

Browser automation is driven by `browser-harness` (CDP), a transitive
dependency of `cli-tools-shared`. No separate "install browsers" step is
required.

After installation, the `stockx` command is available in your terminal.

## Quick Start

```bash
# Search the catalog
stockx products search "jordan 1" --limit 10 --table

# Cheapest first
stockx products search "air max" --sort lowest-ask --brand nike --table

# Browse a category with no keyword
stockx products list --category sneakers --limit 20 --table

# One product's catalog record and its live market
stockx products get air-jordan-1-retro-low-og-sp-travis-scott-sail-tropical-pink
stockx products market air-jordan-1-retro-low-og-sp-travis-scott-sail-tropical-pink
```

No StockX account is needed for any of the above — the catalog is public. See
[Authentication](#authentication-stockx-auth).

## Commands

### Products (`stockx products`)

```bash
# Search the catalog by keyword
stockx products search "jordan 1"
stockx products search "jordan 1" --table --limit 10

# Sort (Source-CLI Sort Standard): featured (default), lowest-ask, highest-bid, release-date
stockx products search "jordan 1" --sort lowest-ask --table
stockx products search "jordan 1" --sort highest-bid --table
stockx products search "jordan 1" --sort release-date --table

# Filter by brand, gender, category, color, activity (each repeatable)
stockx products search "air max" --brand nike --table
stockx products search dunk --brand nike --brand adidas --table
stockx products search hoodie --gender women --category apparel --table
stockx products search "jordan 1" --color black --activity basketball --table

# Boolean filters and the price range (both bounds required)
stockx products search "jordan 1" --below-retail --table
stockx products search "jordan 1" --xpress-ship --table
stockx products search "jordan 1" --min-price 100 --max-price 300 --table

# Restrict output fields; every result carries a canonical url
stockx products search "jordan 1" --properties "id,title,brand,url" --limit 5

# Filter results client-side (field:op:value)
stockx products search "jordan 1" --filter "brand:eq:Jordan"

# Browse the catalog with no keyword (same options as search)
stockx products list
stockx products list --category sneakers --limit 25 --table
stockx products list --brand adidas --sort lowest-ask --table
stockx products list --filter "gender:eq:men"
stockx products list --properties "id,title,brand"

# Get one product's catalog record by url key or product URL
stockx products get air-jordan-1-retro-low-og-sp-travis-scott-sail-tropical-pink
stockx products get "https://stockx.com/air-jordan-1-retro-low-og-sp-travis-scott-sail-tropical-pink"
stockx products get air-jordan-1-retro-low-og-sp-travis-scott-sail-tropical-pink --properties "title,brand,styleId"
stockx products get air-jordan-1-retro-low-og-sp-travis-scott-sail-tropical-pink --table

# Get live market data (asks, bids, sales) for one product
stockx products market air-jordan-1-retro-low-og-sp-travis-scott-sail-tropical-pink
stockx products market "https://stockx.com/air-jordan-1-retro-low-og-sp-travis-scott-sail-tropical-pink"
stockx products market air-jordan-1-retro-low-og-sp-travis-scott-sail-tropical-pink --properties "title,market"
stockx products market air-jordan-1-retro-low-og-sp-travis-scott-sail-tropical-pink --table
```

`search` and `list` return each browse node verbatim (every upstream field
preserved — `id`, `title`, `name`, `urlKey`, `brand`, `gender`, `model`,
`condition`, `productCategory`, `styleId`, `categories`, `variants[]`,
`media`, `traits[]`, `market`) plus a convenience `url`. `get` returns the full
`GetProduct` record (`primaryTitle`, `secondaryTitle`, `description`,
`sizeDescriptor`, `conditions`, `styleId`, …). `market` returns the
`GetMarketData` record: `market.state` (lowest ask, highest bid, ask service
levels, ask and bid counts), `market.salesInformation` (last sale, sales in the
last 72 hours), `market.statistics` (90-day history), and per-size
`variants[].market`. All records carry `url`.

### Authentication (`stockx auth`)

The StockX catalog is public, so every `products` command works on a cold
profile with no StockX account. `auth login` exists so a signed-in session can
be saved for account-scoped work.

```bash
# Interactive login
stockx auth login

# Force re-authentication
stockx auth login --force

# Check authentication status (JSON, from on-disk session)
stockx auth status

# Live session verification (drives the browser)
stockx auth test

# Clear saved session
stockx auth logout
```

### Profiles (`stockx auth profiles`)

```bash
stockx auth profiles list
stockx auth profiles get default
stockx auth profiles select PROFILE_NAME
stockx auth profiles create PROFILE_NAME
stockx auth profiles delete PROFILE_NAME
```

### Cache (`stockx cache`)

```bash
# Clear cached read responses (also clears cached persisted-query hashes)
stockx cache clear

# Bypass the cache for one execution
stockx --no-cache products search "jordan 1"
```

## Output Formats

- JSON is the default output format.
- Add `--table` / `-t` for human-readable table output.

## Options Reference

| Option | Short | Applies to | Description |
|--------|-------|-----------|-------------|
| `--sort` | `-s` | `search` / `list` | Sort field: `featured` (default), `lowest-ask`, `highest-bid`, `release-date` |
| `--desc` | `-d` | `search` / `list` | Reverse the sort field's natural direction (StockX publishes none, so always rejected) |
| `--brand` | `-b` | `search` / `list` | Brand slug, repeatable (e.g. `nike`, `adidas`) |
| `--gender` | `-g` | `search` / `list` | Gender, repeatable: `men`, `women`, `unisex`, `kids` |
| `--category` | `-c` | `search` / `list` | Category, repeatable: `sneakers`, `apparel`, `accessories`, `collectibles`, `shoes`, `trading-cards` |
| `--color` | | `search` / `list` | Color, repeatable (e.g. `black`, `white`, `blue`) |
| `--activity` | | `search` / `list` | Activity slug, repeatable (e.g. `basketball`, `running`) |
| `--below-retail` | | `search` / `list` | Only products asking below retail |
| `--xpress-ship` | | `search` / `list` | Only products eligible for Xpress Ship |
| `--min-price` | | `search` / `list` | Minimum lowest ask in US dollars (needs `--max-price`) |
| `--max-price` | | `search` / `list` | Maximum lowest ask in US dollars (needs `--min-price`) |
| `--limit` | `-l` | `search` / `list` | Maximum number of products (merged across pages) |
| `--filter` | `-f` | `search` / `list` | Filter results using `field:op:value` syntax |
| `--properties` | `-p` | `search` / `list` / `get` / `market` | Restrict output to selected fields |
| `--table` | `-t` | `search` / `list` / `get` / `market` | Display data as a table |
| `--version` | `-v` | root | Show version and exit |
| `--no-cache` | | root | Bypass cached read responses for this execution |

## Configuration

Non-authentication configuration is stored in
`~/.local/share/cli-tools/stockx/.env`. CLI-managed runtime auth state (the
persistent browser profile) is stored in the active profile at
`~/.local/share/cli-tools/stockx/authentication_profiles/<profile>/`. The
source repo only carries `.env.example`.

Do not put reusable credentials in any `.env` file. Store and retrieve them
through `<cli-tools-root>/_repo/_secret-manager/secrets.sh`. `.env` files are
limited to non-secret config and CLI-managed runtime auth state.

Root config variables:

```bash
# Optional: override the default site URL
BASE_URL=https://stockx.com

# Browser settings (true = invisible, false = visible browser)
HEADLESS=true

# Optional: override the auto-derived real-Chrome User-Agent
# BROWSER_USER_AGENT=
# BROWSER_WINDOW_SIZE=1440,900

# Response cache settings
CACHE_ENABLED=true
CACHE_TTL=3600
```

Browser-auth login URLs and authenticated-page signals are defined in
`browser.py` as `BrowserAutomation` class constants.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General / authentication error |
| 130 | User interrupted (Ctrl+C) |

## Architecture

This CLI uses `cli_tools_shared.auth.BrowserAutomation` with the
browser-harness-backed Chrome automation engine:

- **`browser.py`** — declarative `BrowserAutomation` subclass (auth hooks only).
- **`config.py`** — `BaseConfig` subclass; pins the real-Chrome UA and exposes
  `get_browser()` and `test_connection()` (live session check).
- **`client.py`** — drives a live stockx.com page, captures StockX's own
  persisted-query hashes, and runs its GraphQL operations through an in-page
  `fetch`, with exponential-backoff retry that honors `Retry-After`.
- **`parsers.py`** — adds the documented `url` convenience key; every upstream
  field is preserved.

CLIs never call browser binaries via subprocess and never import
`BrowserHarnessService` directly — all browser interaction flows through
`config.get_browser()` → `BrowserAutomation` → browser-harness.

## Debugging

```bash
# Run with a visible browser
export HEADLESS=false
stockx products search "jordan 1"
```

stockx.com rate-limits rapid repeat sessions. If a run reports that StockX did
not serve its app payload, wait a few seconds and retry.

## Requirements

- Python 3.11+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - cli-tools-shared (transitively pulls in browser-harness)

## License

MIT
