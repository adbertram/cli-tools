# Auctionzip CLI

## DESCRIPTION

A browser-automation command-line interface for AuctionZip that searches auction lots and reads a lot's full detail — current bid, buyer's premium, close time, status, and shipping or pickup terms. Because AuctionZip returns a hard Cloudflare block to headless browsers, it reads pages through a persistent Cloudflare-cleared browser session that a one-time headed `auctionzip auth login` establishes, with no AuctionZip account needed to read lots. Use it for repeatable, JSON-first access to AuctionZip lot data (Invaluable-powered and cross-listed with LiveAuctioneers) from agents, automation, or terminal workflows.

## Docs

- Website: https://www.auctionzip.com


## Installation

```bash
cd <cli-tools-root>/auctionzip
uv tool install -e . --force --refresh
```

Browser automation is driven by `browser-harness` (CDP), a transitive
dependency of `cli-tools-shared`. No separate "install browsers" step is
required — the harness manages its own browser binary.

After installation, the `auctionzip` command will be available in your terminal.

## Quick Start

```bash
# One-time headed pass to clear Cloudflare (opens a Chrome window)
auctionzip auth login

# Confirm the session cleared Cloudflare
auctionzip auth status

# Search for lots
auctionzip search "lego" --limit 10 --table

# Get full detail for one lot (paste a URL from a search result)
auctionzip get "https://www.auctionzip.com/auction-lot/large-group-of-lego-pieces_26D5CDA127" --table
```

## Commands

### Authentication (`auctionzip auth`)

```bash
# Interactive login
auctionzip auth login

# Force re-authentication
auctionzip auth login --force

# Check authentication status
auctionzip auth status

# Run the configured live auth test
auctionzip auth test

# Clear saved credentials/session
auctionzip auth logout
```

### Profiles (`auctionzip auth profiles`)

```bash
# List all profiles
auctionzip auth profiles list

# Show a profile
auctionzip auth profiles get default

# Select the active profile for its auth type
auctionzip auth profiles select PROFILE_NAME

# Create a profile
auctionzip auth profiles create PROFILE_NAME

# Delete a profile
auctionzip auth profiles delete PROFILE_NAME
```



### Search (`auctionzip search <query>`)

Search public AuctionZip lots by keyword. Returns a list of lot summaries.

```bash
# Search for lots (JSON output)
auctionzip search "lego"

# Search with table format
auctionzip search "lego star wars" --table

# Limit results
auctionzip search "lego" --limit 10

# Filter results (field:op:value)
auctionzip search "lego" --filter "bids:gt:0"

# Restrict output fields
auctionzip search "lego" --properties "ref,title,current_bid,url"

# Bypass the cache for a fresh read of current bids
auctionzip --no-cache search "lego"
```

Each search result includes: `ref`, `lot_number`, `title`, `auction_house`,
`current_bid` / `current_bid_amount`, `bids`, `time_remaining` (live/timed
lots), `close_time` (scheduled lots), `estimate`, and the lot `url`.

### Get lot detail (`auctionzip get <lot>`)

Get full detail for a single lot. Accepts a lot URL, a `slug_ref`, or a bare lot
reference (all as returned by `search`).

```bash
# By full URL (JSON)
auctionzip get "https://www.auctionzip.com/auction-lot/large-group-of-lego-pieces_26D5CDA127"

# By slug_ref
auctionzip get "large-group-of-lego-pieces_26D5CDA127" --table

# Restrict output fields
auctionzip get "large-group-of-lego-pieces_26D5CDA127" --properties "current_bid,buyer_premium,close_time,status"

# Bypass the cache for a fresh bid/status read
auctionzip --no-cache get "large-group-of-lego-pieces_26D5CDA127"
```

Lot detail includes: `ref`, `catalog_ref`, `lot_number`, `title`,
`auction_house`, `status` (`open`/`closed`), `auction_type`, `current_bid` /
`current_bid_amount`, `bids`, `next_bid` / `next_bid_amount`, `buyer_premium` /
`buyer_premium_pct`, `currency`, `close_time`, `time_remaining`, `category`,
`location`, `accepted_payment`, `shipping_terms`, `conditions_of_sale`,
`description`, and `url`.

## Output Formats

- JSON is the default output format.
- Add `--table` / `-t` for human-readable table output.

## AI Instruction Results

Commands that reach a non-deterministic boundary may return an AI instruction result instead of normal resource data. This is JSON on stdout with `type: "ai_instruction"` and tells the calling AI agent what objective to complete, what context is available, what tools are allowed, and what success means.

The CLI must not call an LLM or include required pre-action command lists. Optional `verification_commands` and `follow_up_commands` may appear only for actions to run after the agent completes the instruction.

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display data as a table |
| `--limit` | `-l` | Maximum number of results |
| `--filter` | `-f` | Filter results using `field:op:value` syntax |
| `--properties` | `-p` | Restrict output to selected fields |
| `--version` | `-v` | Show version and exit |
| `--no-cache` |  | Bypass cached read responses for this execution |

## Configuration

Non-authentication configuration is stored in `~/.local/share/cli-tools/auctionzip/.env`. CLI-managed runtime auth state is stored in the active profile at `~/.local/share/cli-tools/auctionzip/authentication_profiles/<profile>/.env`. The source repo only carries `.env.example`.

Reusable CLI credentials that agents or scripts need to store/retrieve are governed by the user-level `cli-tool` skill's `references/secrets.md`.

Do not put reusable credentials in any `.env` file. Store and retrieve them through `<cli-tools-root>/_repo/_secret-manager/secrets.sh`. `.env` files are limited to non-secret config and CLI-managed runtime auth state.

Root config variables:

```bash
# Optional: override the default site URL
BASE_URL=https://www.auctionzip.com

# Browser settings (true = invisible, false = visible browser)
HEADLESS=true

# Optional browser-harness runtime settings
# BROWSER_USER_AGENT=
# BROWSER_WINDOW_SIZE=1440,900

# Response cache settings
CACHE_ENABLED=true
CACHE_TTL=3600
```

Browser-auth selectors, login URLs, and other authenticated-page signals are defined in `browser.py` as `BrowserAutomation` class constants. Validate them against a real page snapshot before shipping.

## Cache

```bash
# Clear cached read responses
auctionzip cache clear

# Bypass the cache for one execution
auctionzip --no-cache search "lego" --limit 10
```

Browser session data is stored in the profile data directory for persistence between commands.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Architecture

This CLI uses `cli_tools_shared.auth.BrowserAutomation` with browser-harness-backed Chrome automation:

- **Session Persistence**: Browser context persists between commands (cookies, localStorage)
- **Interactive Login**: Opens browser for manual login, saves session automatically
- **Form Automation**: Fill forms, click buttons, select dropdowns
- **Data Extraction**: Extract tables, lists, and custom data from pages
- **Pagination**: Handle "Load More" buttons and multi-page results
- **Retry Logic**: Automatic retries with exponential backoff

### How pages are read

1. `browser.py` declares the Cloudflare-clearance auth model (`cf_clearance`
   cookie signal); no account login is used.
2. `client.py` navigates the cleared session to the search / lot URL, reads the
   rendered HTML (`page.content()`), and retries transient failures and
   Cloudflare re-challenges with exponential backoff.
3. `parsers.py` parses that HTML with BeautifulSoup into the documented records
   (validated against real DOM fixtures under `tests/fixtures/`).

## Browser Automation Notes

- **First run**: Run `auctionzip auth login` to launch the persistent browser session and complete login
- **Headless mode**: Set `HEADLESS=false` to watch the browser during debugging
- **Session persistence**: Login sessions are saved under the active profile's browser-data directory
- **Rate limiting**: Be respectful of the site's terms of service

## Debugging

To debug browser automation issues:

```bash
# Run with visible browser
export HEADLESS=false
auctionzip search "test"
```

## Output Contract

Commands return plain JSON records (add `--table`/`-t` for a table).

`search` returns a list of lot summaries; `get` returns one lot detail record.
The full field lists are documented under
[Search](#search-auctionzip-search-query) and
[Get lot detail](#get-lot-detail-auctionzip-get-lot) above. Bid, bid count, and
status are point-in-time snapshots — pass `--no-cache` for a fresh read.

## Requirements

- Python 3.11+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - beautifulsoup4
  - cli-tools-shared (transitively pulls in browser-harness)

## License

MIT
