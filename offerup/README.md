# OfferUp CLI

## DESCRIPTION

A browser-automation command-line interface for OfferUp that provides
read-only, JSON-first access to the OfferUp local marketplace. It searches
public listings by keyword (`listings search`), browses the local feed with no
keyword (`listings list`), and returns the full detail record for one item
(`listings get`). Use this CLI when you need repeatable, scriptable OfferUp
data without clicking through the website.

## Docs

- Website: https://offerup.com

## Data source

OfferUp publishes no public API. Its web app posts every feed and detail query
to an internal GraphQL endpoint, `POST https://offerup.com/api/graphql`. The
app attaches a signed `userdata` JWT (the visitor's resolved location), a device
token, and a session id that are all minted inside the page.

Rather than transplant those into a second HTTP stack, this CLI lets the live
offerup.com page issue the request itself through an in-page `fetch`, so it
carries the real browser's cookies (`credentials: 'include'`) and its real
network stack. Navigation runs through the shared
`cli_tools_shared.BrowserAutomation` engine (CDP / browser-harness).

Operations used (validated against the live site during CLI creation):

| Command | GraphQL operation | Returns |
|---------|-------------------|---------|
| `listings search` | `GetModularFeed` | `modularFeed.looseTiles[].listing` + `modules[].grid.tiles[].listing` |
| `listings list` | `GetModularFeed` (no `q` param) | the same shape, for the local feed |
| `listings get` | `GetListingDetailByListingId` | `listing` (full item detail) |

A plain `content-type: application/json` header plus `credentials: 'include'`
is accepted — the app's extra `x-ou-*` headers are **not** required (verified:
HTTP 200 with listings).

Search parameters are `{key, value}` entries in `modularFeed(params:)`. Every
name below was confirmed by OfferUp's own filter echo, where
`modularFeed.filters[].targetName` reports the applied value:

| Option | param | Verified values |
|--------|-------|-----------------|
| `<query>` argument | `q` | free text |
| `--sort` / `--desc` | `sort` | `best_match`, `-posted`, `distance`, `price`, `-price` |
| `--condition` | `condition` | `NEW`, `OPEN_BOX`, `REFURBISHED`, `USED`, `BROKEN`, `OTHER` |
| `--min-price` / `--max-price` | `price_min` / `price_max` | US dollars (echoed as `PRICE_MIN` / `PRICE_MAX`) |
| `--radius` | `radius` | `5`, `10`, `20`, `30`, `50` miles (echoed as `DISTANCE`) |
| `--latitude` / `--longitude` | `lat` / `lon` | decimal degrees |
| (pagination) | `page_cursor` | opaque cursor from `pageCursor` |

**OfferUp silently ignores unknown parameters and unknown values** — a nonsense
key returned the unfiltered baseline, and `conditions` / `condition_ids`
produced an empty `CONDITION` echo. Because a silently dropped filter is worse
than an error, this CLI validates every option value against the vocabulary
OfferUp itself publishes and fails fast on anything else.

`listings search` follows the **Source-CLI Sort Standard**: `--sort/-s <field>`
(default `relevance`) plus `--desc/-d` to reverse a field's natural direction.
Valid fields are `relevance`, `newest`, `distance`, and `price`. Each OfferUp
`sort` token bakes in its own direction, and OfferUp exposes **no oldest-first
order**, so `--desc` is accepted only with `--sort price` and is rejected
elsewhere with a clear error (fail-fast, never a silent fallback). An unknown
`--sort` value likewise exits non-zero.

Pagination is cursor-based; `--limit` is merged across pages under the hood and
deduped by listing id. Prices come back as strings in whole US dollars, exactly
as OfferUp returns them.

Search location defaults to the location OfferUp resolves from the connection's
IP address. Pass `--latitude` and `--longitude` to search anywhere else.

## Installation

```bash
cd <cli-tools-root>/offerup
uv tool install -e . --force --refresh
```

Browser automation is driven by `browser-harness` (CDP), a transitive
dependency of `cli-tools-shared`. No separate "install browsers" step is
required.

After installation, the `offerup` command is available in your terminal.

## Quick Start

```bash
# Search public listings near the resolved location
offerup listings search lego --limit 10 --table

# Search a specific area
offerup listings search lego --latitude 47.6062 --longitude -122.3321 --table

# Browse the local feed with no keyword
offerup listings list --limit 20 --table

# Get full detail for one listing
offerup listings get 2a8b6eda-4b05-33a2-be75-2eb33966b8c1
```

No OfferUp account is needed for any of the above — the marketplace feed is
public. See [Authentication](#authentication-offerup-auth).

## Commands

### Listings (`offerup listings`)

```bash
# Search public listings by keyword
offerup listings search lego
offerup listings search lego --table --limit 10

# Sort (Source-CLI Sort Standard): relevance (default), newest, distance, price
offerup listings search lego --sort newest --table
offerup listings search lego --sort distance --table
offerup listings search lego --sort price --table
offerup listings search lego --sort price --desc --table

# Filter by condition (repeatable), price in US dollars, and radius in miles
offerup listings search lego --condition NEW --condition OPEN_BOX --table
offerup listings search lego --min-price 20 --max-price 100 --table
offerup listings search lego --radius 10 --table

# Search another area by coordinates
offerup listings search lego --latitude 47.6062 --longitude -122.3321 --table

# Restrict output fields; every result carries id + canonical url
offerup listings search lego --properties "id,title,price,locationName,url" --limit 5

# Filter results client-side (field:op:value)
offerup listings search lego --filter "price:gt:50"

# Browse the local feed with no keyword (same options as search)
offerup listings list
offerup listings list --limit 25 --table
offerup listings list --sort newest --radius 5 --table
offerup listings list --filter "locationName:contains:Seattle"
offerup listings list --properties "id,title,price"

# Get full detail for one listing by id or URL
offerup listings get 2a8b6eda-4b05-33a2-be75-2eb33966b8c1
offerup listings get "https://offerup.com/item/detail/2a8b6eda-4b05-33a2-be75-2eb33966b8c1"

# Get with selected fields / table
offerup listings get 2a8b6eda-4b05-33a2-be75-2eb33966b8c1 --properties "id,title,price,state"
offerup listings get 2a8b6eda-4b05-33a2-be75-2eb33966b8c1 --table
```

`search` and `list` return each feed listing verbatim (every upstream field
preserved — `listingId`, `title`, `price`, `conditionText`, `locationName`,
`isFirmPrice`, `flags`, `vehicleMiles`, `image`, `video`) plus convenience `id`
and `url` fields. `get` returns the full `listing` object (`description`,
`condition`, `state`, `postDate`, `photos[]`, `locationDetails`,
`listingCategory`, `fulfillmentDetails`, `shippingOptions[]`, `owner{}`,
`vehicleAttributes`, …) plus `id` and `url`.

### Authentication (`offerup auth`)

The OfferUp marketplace feed is public, so `listings search`, `listings list`,
and `listings get` all work on a cold profile with no OfferUp account. `auth
login` exists so a signed-in session can be saved for account-scoped work.

```bash
# Interactive login
offerup auth login

# Force re-authentication
offerup auth login --force

# Check authentication status (JSON, from on-disk session)
offerup auth status

# Live session verification (drives the browser)
offerup auth test

# Clear saved session
offerup auth logout
```

### Profiles (`offerup auth profiles`)

```bash
offerup auth profiles list
offerup auth profiles get default
offerup auth profiles select PROFILE_NAME
offerup auth profiles create PROFILE_NAME
offerup auth profiles delete PROFILE_NAME
```

### Cache (`offerup cache`)

```bash
# Clear cached read responses
offerup cache clear

# Bypass the cache for one execution
offerup --no-cache listings search lego
```

## Output Formats

- JSON is the default output format.
- Add `--table` / `-t` for human-readable table output.

## Options Reference

| Option | Short | Applies to | Description |
|--------|-------|-----------|-------------|
| `--sort` | `-s` | `search` / `list` | Sort field: `relevance` (default), `newest`, `distance`, `price` |
| `--desc` | `-d` | `search` / `list` | Reverse the sort field's natural direction (only valid with `price`) |
| `--condition` | `-c` | `search` / `list` | Item condition, repeatable: `NEW`, `OPEN_BOX`, `REFURBISHED`, `USED`, `BROKEN`, `OTHER` |
| `--min-price` | | `search` / `list` | Minimum price in US dollars |
| `--max-price` | | `search` / `list` | Maximum price in US dollars |
| `--radius` | `-r` | `search` / `list` | Search radius in miles: `5`, `10`, `20`, `30`, `50` |
| `--latitude` | | `search` / `list` | Search latitude in decimal degrees |
| `--longitude` | | `search` / `list` | Search longitude in decimal degrees |
| `--limit` | `-l` | `search` / `list` | Maximum number of listings (merged across pages) |
| `--filter` | `-f` | `search` / `list` | Filter results using `field:op:value` syntax |
| `--properties` | `-p` | `search` / `list` / `get` | Restrict output to selected fields |
| `--table` | `-t` | `search` / `list` / `get` | Display data as a table |
| `--version` | `-v` | root | Show version and exit |
| `--no-cache` | | root | Bypass cached read responses for this execution |

## Configuration

Non-authentication configuration is stored in
`~/.local/share/cli-tools/offerup/.env`. CLI-managed runtime auth state (the
persistent browser profile) is stored in the active profile at
`~/.local/share/cli-tools/offerup/authentication_profiles/<profile>/`. The
source repo only carries `.env.example`.

Do not put reusable credentials in any `.env` file. Store and retrieve them
through `<cli-tools-root>/_repo/_secret-manager/secrets.sh`. `.env` files are
limited to non-secret config and CLI-managed runtime auth state.

Root config variables:

```bash
# Optional: override the default site URL
BASE_URL=https://offerup.com

# Browser settings (true = invisible, false = visible browser)
HEADLESS=true

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
- **`config.py`** — `BaseConfig` subclass; exposes `get_browser()` and
  `test_connection()` (live session check).
- **`client.py`** — drives a live offerup.com page and runs OfferUp's own
  GraphQL operations through an in-page `fetch`, with exponential-backoff retry
  that honors `Retry-After`.
- **`parsers.py`** — adds the documented `id` / `url` convenience keys; every
  upstream field is preserved.

CLIs never call browser binaries via subprocess and never import
`BrowserHarnessService` directly — all browser interaction flows through
`config.get_browser()` → `BrowserAutomation` → browser-harness.

## Debugging

```bash
# Run with a visible browser
export HEADLESS=false
offerup listings search lego
```

## Requirements

- Python 3.11+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - cli-tools-shared (transitively pulls in browser-harness)

## License

MIT
