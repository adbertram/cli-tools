# Depop CLI

## DESCRIPTION

A command-line interface for Depop. Search the public Depop resale marketplace by keyword with price, condition, gender, category, and sort filters, driven through a Cloudflare-cleared browser session since Depop has no public marketplace-search API (see "Data source" below for why).

Use this CLI when you need scriptable, JSON-first access to Depop search results from agents, automation, or terminal workflows.

## Data source

Depop's only official API (`partnerapi.depop.com`, the "Selling API") is private/partner-gated and is seller-inventory/order management only — it has no product-search endpoint, so it cannot serve marketplace search even with partner access. This CLI instead uses Depop's own internal web-app search endpoint, the same one `depop.com/search/` calls in the browser.

That endpoint sits behind Cloudflare Bot Management. `depop auth login` opens a one-time headed real-Chrome session; Cloudflare's Managed Challenge clears silently within a few seconds (no interactive "verify you are human" step has ever been observed live), and the resulting `cf_clearance` cookie is saved to a persistent browser profile. Every `depop search` call afterward runs the actual HTTP fetch **inside that Cloudflare-cleared browser page** (`page.evaluate` + `fetch(..., {credentials:'include'})`) so the request always carries a real browser's cookies, TLS, and HTTP/2 fingerprint — a standalone HTTP client replaying just the cookie value would very likely get re-challenged. Subsequent calls run fully headless (no visible window) by pinning the browser's User-Agent to the real (non-`Headless`) Chrome string that earned the clearance.

No Depop account, username, or password is required — Depop's marketplace search is public. "Authentication" in this CLI means "this profile has a live Cloudflare clearance," not a logged-in Depop account.

## Installation

```bash
cd <cli-tools-root>/depop
uv tool install -e . --force --refresh --python "$(command -v python3)"
```

After installation, the `depop` command will be available in your terminal.

## Quick Start

```bash
# One-time: open a headed browser, let Cloudflare clear, save the session
depop auth login

# Check the saved session is still valid
depop auth status

# Search (headless from here on)
depop search "nike jacket"

# With filters and table output
depop search "nike jacket" --price-min 10 --price-max 50 --condition used_good --gender female --sort price --limit 25 --table
```

## Commands

### Authentication (`depop auth`)

```bash
# Open a headed browser and wait for Cloudflare's challenge to clear
depop auth login

# Force a fresh clearance (e.g. after Chrome's major version updates)
depop auth login --force

# Check whether the saved profile still has a live cf_clearance cookie
depop auth status

# Run the configured live auth test (navigates depop.com and re-checks)
depop auth test

# Clear the saved browser profile/session
depop auth logout
```

### Profiles (`depop auth profiles`)

```bash
depop auth profiles list
depop auth profiles get default
depop auth profiles select PROFILE_NAME
depop auth profiles create PROFILE_NAME
depop auth profiles delete PROFILE_NAME
```

### Search (`depop search`)

```bash
# Basic keyword search (JSON output, default limit 24)
depop search "vintage levis 501"

# Price range (US dollars)
depop search "jacket" --price-min 10 --price-max 50

# Condition (repeatable): brand_new, used_like_new, used_excellent, used_good, used_fair
depop search "jacket" --condition used_good --condition used_like_new

# Gender: male, female, or unisex
depop search "jacket" --gender female

# Category group slug (matches a result's own "category" field), e.g.
# coats-jackets, tops, bottoms, dresses, jeans, sweaters, footwear
depop search "jacket" --category coats-jackets

# Sort field (Source-CLI Sort Standard): price or relevance (default).
# --desc / -d reverses the field's natural direction.
depop search "jacket" --sort price            # price low -> high (natural)
depop search "jacket" --sort price --desc     # price high -> low

# Depop's search API has NO usable chronological ("newest") sort: its recency
# value is blocked by Depop on the endpoint this CLI uses, and unrecognized
# sort values are silently ignored (relevance order). So `--sort newest` is
# rejected with a clear error rather than silently returning arbitrary order.
# `relevance` has no direction, so `--desc` is rejected with it.

# Maximum results (drives API-level pagination, not client-side truncation)
depop search "jacket" --limit 100

# Table output
depop search "jacket" --table

# Restrict output fields
depop search "jacket" --properties "id,brand_name,price,url"

# Post-fetch filter on any returned field (field:op:value)
depop search "jacket" --filter "brand_name:eq:Nike"
```

All filters above are sent to Depop's own search API server-side (validated live against the real search UI) — none are applied client-side. `--filter`/`--properties` operate afterward on the already-filtered result set, same as every other CLI in this repo.

**Size filtering is intentionally not implemented.** Depop's size taxonomy is a nested per-category/region composite id (e.g. `"101.16-EUR"`), not a flat enum, resolved from a separate `sizeFilters` endpoint. Guessing a flat `--size` value risked silently filtering nothing. Inspect a result's own `sizes[].name` values and post-filter with `jq`/`--filter` instead.

### Sort (`--sort` / `--desc`)

This CLI follows the repo's Source-CLI Sort Standard: `--sort/-s <field>` picks the sort field and `--desc/-d` reverses that field's natural direction.

| `--sort` | Natural (no `--desc`) | With `--desc` |
|----------|-----------------------|---------------|
| `price` | low → high | high → low |
| `relevance` (default) | Depop relevance order | rejected — relevance has no direction |

**No chronological (`newest`) sort — recency-sort exception.** The standard's default sort field is `newest`, but Depop's search endpoint used by this CLI (`presentation/api/v1/search/products/`) has no usable chronological ordering: its documented recency value `newlyListed` is deterministically blocked by Depop with a Cloudflare 403 on this endpoint (verified live), and any unrecognized sort value is silently ignored (relevance order), so there is no oldest/newest ordering available. Per the standard's recency-sort exception, `depop search --sort newest` is therefore **rejected with a clear error** rather than silently returning arbitrary order, and the default is `relevance`. Unknown `--sort` values are likewise rejected (non-zero exit) with the valid-values list — never silently defaulted.

## Output Formats

- JSON is the default output format.
- Add `--table` / `-t` for human-readable table output.

## Output Contract

`depop search` returns Depop's full search result object for every listing — every field the API provides (`id`, `brand_name`, `brand_id`, `category`, `category_name`, `categories`, `description`, `slug`, `country`, `location`, `attributes` (condition/colour/brand/gender/is_kids/group/product_type), `pricing` (full price breakdown), `shipping_method`, `sizes[]`, `variants_all[]`, `pictures[]`, `preview`, `like_count`, `listed_quantity`, `status`, `is_boosted`, etc.) — plus five non-destructive convenience fields added on top so common lookups and `--filter`/`--properties`/table columns do not need to reach into nested objects:

| Convenience field | Derived from |
|--------------------|--------------|
| `url` | `https://www.depop.com/products/{slug}/` |
| `price` | `pricing.current_price.total_price` |
| `currency` | `pricing.currency` |
| `condition` | `attributes.condition` |
| `gender` | `attributes.gender` |
| `category` | `attributes.group` |

No upstream field is ever dropped or overwritten by a convenience field.

## AI Instruction Results

Commands that reach a non-deterministic boundary may return an AI instruction result instead of normal resource data. This is JSON on stdout with `type: "ai_instruction"` and tells the calling AI agent what objective to complete, what context is available, what tools are allowed, and what success means.

The CLI must not call an LLM or include required pre-action command lists. Optional `verification_commands` and `follow_up_commands` may appear only for actions to run after the agent completes the instruction.

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--price-min` |  | Minimum price in US dollars |
| `--price-max` |  | Maximum price in US dollars |
| `--condition` | `-c` | Condition (repeatable) |
| `--gender` |  | male, female, or unisex |
| `--category` |  | Category group slug |
| `--sort` | `-s` | Sort field: `price` (natural low->high) or `relevance` (default). No chronological `newest` sort — see note below |
| `--desc` | `-d` | Reverse the sort field's natural direction (`price` high->low). Not valid with `relevance` |
| `--table` | `-t` | Display data as a table |
| `--limit` | `-l` | Maximum number of results |
| `--filter` | `-f` | Filter results using `field:op:value` syntax |
| `--properties` | `-p` | Restrict output to selected fields |
| `--version` | `-v` | Show version and exit |
| `--no-cache` |  | Bypass cached read responses for this execution |

## Configuration

Non-authentication configuration is stored in `~/.local/share/cli-tools/depop/.env`. CLI-managed runtime auth state (the persistent Cloudflare-cleared browser profile) is stored in the active profile at `~/.local/share/cli-tools/depop/authentication_profiles/<profile>/`. The source repo only carries `.env.example`.

Depop requires no reusable human-supplied credential (no username/password/API key) — the only thing `auth login` earns is a Cloudflare clearance cookie in the browser profile, so there is nothing to store in the CLI-tools secret manager for this CLI.

Root config variables:

```bash
# Optional: override the default site URL
BASE_URL=https://www.depop.com

# Optional: force headed browser mode for search calls (default: headless)
HEADLESS=true

# Optional: override the auto-derived real-Chrome User-Agent
BROWSER_USER_AGENT=

# Optional: response cache settings
CACHE_ENABLED=true
CACHE_TTL=3600
```

## Cache

```bash
# Clear cached read responses
depop cache clear

# Bypass the cache for one execution
depop --no-cache search "jacket" --limit 10
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Client/config/authentication error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### Search and extract with jq

```bash
depop search "vintage levis" --properties "id,price,url" | jq '.[].url'
```

### Export search results to a file

```bash
depop search "y2k jacket" --limit 100 > jackets.json
```

## Requirements

- Python 3.11+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - cli-tools-shared (browser automation engine)

## License

MIT
