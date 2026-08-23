# Mercari CLI

## DESCRIPTION

A browser-automation command-line interface for Mercari US that provides
read-only access to Mercari listings. It searches other sellers' public
listings (`listings search`), reads the authenticated seller's own listings
(`listings list`), and returns full item detail (`listings get` and
`listings get-many`). Use this CLI
when you need repeatable, JSON-first access to Mercari listings without clicking
through the website.

## Docs

- Website: https://www.mercari.com

## Data source

Mercari US has no public individual-seller API. Its web app talks to an
internal GraphQL endpoint (`/v1/api`) that authenticates every request with a
short-lived `authorization` JWT plus device-bound headers (`x-csrf-token`,
`x-socure-device-token`) generated inside the page. A raw request replay — even
an in-page `fetch(url, {credentials:'include'})` — returns **HTTP 401** because
those headers cannot be reproduced outside the app's Apollo client (verified
live).

This CLI therefore lets the logged-in web app issue its own authenticated
GraphQL request and **captures the JSON response** via a `fetch` interceptor
injected before a client-side (SPA) route change. This reuses the app's real
auth and returns full-fidelity structured data — no DOM scraping, no token
extraction. All navigation runs through the shared
`cli_tools_shared.BrowserAutomation` engine (CDP / browser-harness).

Operations used (validated against the live authenticated session):

| Command | GraphQL operation | Returns |
|---------|-------------------|---------|
| `listings search` | `searchFacetQuery` | `data.search.itemsList[]` |
| `listings list` | `userItemsQuery` | `data.userItems.items[]` + pagination |
| `listings get`  | `productQuery`   | `data.item` (full item detail) |
| `listings get-many` | `productQuery` | One ordered result for each requested item |

Status mapping for `list`: `active` → `on_sale`, `inactive` → `stop`,
`complete` → `sold_out` (sold).

`search` filters are passed as `/search` URL query params that the SPA
translates into the `searchFacetQuery` criteria. Every mapping below was
validated live against the fired criteria and the returned result set:

| Option | URL param → criteria | Verified values |
|--------|----------------------|-----------------|
| `--status` | `itemStatuses` (repeated) | `on_sale`→[1], `sold`→[2,3] |
| `--condition` | `itemConditions` | `new`=1, `like_new`=2, `good`=3, `fair`=4, `poor`=5 |
| `--min-price` / `--max-price` | `minPrice` / `maxPrice` | US dollars → cents (×100) |
| `--sort` / `--desc` | `sortBy` | `newest`=2 (created-time desc), `price`=3 (low→high), `price --desc`=4 (high→low), `relevance`=omit (best match) |
| `--category-id` | `categoryIds` (repeated) | raw id (see result `categoryId`) |
| `--brand-id` | `brandIds` (repeated) | raw id (see result `brand.id`) |

`listings search` follows the **Source-CLI Sort Standard**: `--sort/-s <field>`
(default `newest`) plus `--desc/-d` to reverse a field's natural direction.
Valid fields are `newest` (created-time descending), `price` (natural low→high;
`--desc` = high→low), and `relevance` (best match). Each Mercari `sortBy` code
bakes in its own direction, and Mercari US search exposes **no oldest-first
order**, so `--sort newest --desc` and `--sort relevance --desc` are rejected
with a clear error (fail-fast, never a silent fallback). An unknown `--sort`
value likewise exits non-zero. Because the search command binds `-s` to
`--sort`, its `--status` filter is long-form only (`listings list` keeps
`--status/-s`).

Pagination is offset-based; `--limit` is merged across pages under the hood
(deduped by item id). Item prices in results are in **cents** (e.g. `17683` =
$176.83), matching what Mercari returns.

mercari.com sits behind Cloudflare. The CLI presents a pinned real-Chrome
User-Agent (derived from the installed Chrome version) so the same UA is sent
headed and headless — the default `HeadlessChrome` token trips Cloudflare and
invalidates the UA-bound `cf_clearance` cookie.

## Installation

```bash
cd <cli-tools-root>/mercari
uv tool install -e . --force --refresh
```

Browser automation is driven by `browser-harness` (CDP), a transitive
dependency of `cli-tools-shared`. No separate "install browsers" step is
required.

After installation, the `mercari` command is available in your terminal.

## Quick Start

```bash
# Authenticate with Mercari (see Authentication note below)
mercari auth login

# Search other sellers' listings
mercari listings search lego --limit 10 --table

# List your active listings (JSON)
mercari listings list --status active

# List your sold listings as a table, limited to 25
mercari listings list --status complete --limit 25 --table

# Get full detail for one listing/item (id from search or list)
mercari listings get m12345678901

# Get multiple items through one browser session
mercari listings get-many m12345678901 m10987654321
```

## Commands

### Listings (`mercari listings`)

```bash
# Search other sellers' public listings by keyword
mercari listings search lego
mercari listings search lego --table --limit 10

# Filter search by status (on_sale | sold), condition, price (US dollars), sort
mercari listings search lego --status on_sale --condition good --table
mercari listings search lego --min-price 20 --max-price 100 --sort price --table
mercari listings search lego --sort price --desc --limit 20 --table

# Sort by newest listed (the default) or by relevance
mercari listings search lego --sort newest --limit 20 --table
mercari listings search lego --sort relevance --table

# Filter by category id or brand id (repeatable; ids come from result fields)
mercari listings search lego --category-id 2211 --table
mercari listings search lego --brand-id 3752 --table

# Restrict search output fields; every result carries id + canonical url
mercari listings search lego --properties "id,url,name,price,status" --limit 5

# List your own listings for a status (active | inactive | complete)
mercari listings list --status active
mercari listings list -s inactive
mercari listings list -s complete

# Table output
mercari listings list --status active --table

# Limit results
mercari listings list --status active --limit 25

# Filter results (client-side: field:op:value)
mercari listings list --status active --filter "status:eq:on_sale"

# Restrict output fields (dot-notation supported)
mercari listings list --status active --properties "id,name,price,status"

# Get full detail for one listing/item by id or URL
mercari listings get m12345678901
mercari listings get "https://www.mercari.com/us/item/m12345678901/"

# Get with selected fields / table
mercari listings get m12345678901 --properties "id,name,price,status,created"
mercari listings get m12345678901 --table

# Get multiple items. Input order and coverage stay unchanged.
mercari listings get-many m12345678901 m10987654321
mercari listings get-many m12345678901 m10987654321 --properties "id,status"
```

`search` returns each `searchFacetQuery` item verbatim (every upstream field
preserved — `id`, `name`, `price`, `status`, `brand`, `itemCondition`,
`itemCategory`, `categoryTitle`, `seller`, `photos`, …) plus a convenience
`url`. `list` returns the item records exactly as Mercari's `userItemsQuery`
returns them (every upstream field preserved), plus convenience `id` and `url`
fields. `get` returns the full `productQuery` item object (all fields — `itemId`,
`name`, `price`, `description`, `status`, `itemCondition`, `itemSize`, `brand`,
`shippingClass`, `shippingFromArea`, `numLikes`, `created`, `updated`,
`photos[]`, `seller{}`, …) plus `id`, `url`,
`buyer_protection_fee_cents`, and `landed_total_cents`. The landed total
includes buyer-paid shipping. Both added cost fields use integer cents.

`get-many` returns one record for each input. A successful record contains
`item_id`, `status: "ok"`, and `item`. An item read error contains `item_id`,
`status: "error"`, `error_kind`, and `error`. The `error_kind` is `not_found`
only when Mercari returns no item. Other item read errors use `unreadable`.
A human verification challenge stops the command without partial JSON.

### Authentication (`mercari auth`)

```bash
# Interactive login (see note)
mercari auth login

# Force re-authentication
mercari auth login --force

# Check authentication status (JSON, from on-disk session)
mercari auth status

# Live session verification (drives the browser)
mercari auth test

# Clear saved session
mercari auth logout
```

**Authentication note:** Mercari requires an email one-time verification code
at login. The shared login flow opens the persistent browser session; complete
the email code step to finish. Once authenticated, the session persists in the
profile and all `listings` commands run headless.

### Profiles (`mercari auth profiles`)

```bash
mercari auth profiles list
mercari auth profiles get default
mercari auth profiles select PROFILE_NAME
mercari auth profiles create PROFILE_NAME
mercari auth profiles delete PROFILE_NAME
```

## Output Formats

- JSON is the default output format.
- Add `--table` / `-t` for human-readable table output.

## Options Reference

| Option | Short | Applies to | Description |
|--------|-------|-----------|-------------|
| `--status` | `-s` (list only) | `listings list` / `search` | list: `active`/`inactive`/`complete` (short `-s`); search: `on_sale`/`sold` (long only — `-s` is `--sort` there) |
| `--condition` | `-c` | `listings search` | `new`, `like_new`, `good`, `fair`, `poor` |
| `--min-price` |  | `listings search` | Minimum price in US dollars |
| `--max-price` |  | `listings search` | Maximum price in US dollars |
| `--sort` | `-s` | `listings search` | Sort field: `newest` (default), `price`, `relevance` (Source-CLI Sort Standard) |
| `--desc` | `-d` | `listings search` | Reverse the sort field's natural direction (only valid with `price`) |
| `--category-id` |  | `listings search` | Filter by category id (repeatable) |
| `--brand-id` |  | `listings search` | Filter by brand id (repeatable) |
| `--limit` | `-l` | `listings list` / `search` | Maximum number of results (merged across pages) |
| `--filter` | `-f` | `listings list` / `search` | Filter results using `field:op:value` syntax |
| `--properties` | `-p` | list / search / get / get-many | Restrict output to selected fields |
| `--table` | `-t` | list / search / get / get-many / auth test | Display data as a table |
| `--version` | `-v` | root | Show version and exit |
| `--no-cache` |  | root | Bypass cached read responses for this execution |

## Configuration

Non-authentication configuration is stored in
`~/.local/share/cli-tools/mercari/.env`. CLI-managed runtime auth state (the
persistent browser profile) is stored in the active profile at
`~/.local/share/cli-tools/mercari/authentication_profiles/<profile>/`. The
source repo only carries `.env.example`.

Do not put reusable credentials in any `.env` file. Store and retrieve them
through `<cli-tools-root>/_repo/_secret-manager/secrets.sh`. `.env` files are
limited to non-secret config and CLI-managed runtime auth state.

Root config variables:

```bash
# Optional: override the default site URL
BASE_URL=https://www.mercari.com

# Browser settings (true = invisible, false = visible browser)
HEADLESS=true

# Optional: override the auto-derived real-Chrome User-Agent
# BROWSER_USER_AGENT=
# BROWSER_WINDOW_SIZE=1440,900

# Response cache settings
CACHE_ENABLED=true
CACHE_TTL=3600
```

Browser-auth selectors, login URLs, and authenticated-page signals are defined
in `browser.py` as `BrowserAutomation` class constants, validated against the
live authenticated page.

## Cache

```bash
# Clear cached read responses
mercari cache clear

# Bypass the cache for one execution
mercari --no-cache listings list --status active
```

Browser session data is stored in the profile data directory for persistence
between commands.

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
- **`client.py`** — drives the app via SPA navigation and captures the app's own
  authenticated GraphQL responses through an injected `fetch` interceptor.
- **`parsers.py`** — normalizes `userItems.items[]` and `productQuery` item
  objects into public records (all upstream fields preserved).

CLIs never call browser binaries via subprocess and never import
`BrowserHarnessService` directly — all browser interaction flows through
`config.get_browser()` → `BrowserAutomation` → browser-harness.

## Debugging

```bash
# Run with a visible browser
export HEADLESS=false
mercari listings list --status active
```

## Requirements

- Python 3.11+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - cli-tools-shared (transitively pulls in browser-harness)

## License

MIT
