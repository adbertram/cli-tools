# Envato CLI

## DESCRIPTION

A read-only command-line interface for the Envato Market API that searches CodeCanyon, ThemeForest, and the other Envato marketplace sites by keyword and reads each item's sales count, rating, rating count, price, and publish/update dates.

Use this CLI when you need scriptable, JSON-first marketplace demand data (for example CodeCanyon opportunity research) from agents, automation, or terminal workflows.

## Docs

- API documentation: https://build.envato.com/api/
- Personal token creation: https://build.envato.com/create-token/
- Base URL: https://api.envato.com


## Installation

```bash
<cli-tools-root>/_repo/skills/cli-tool/scripts/install-cli-tool.sh --force-refresh envato
```

After installation, the `envato` command will be available in your terminal.

## Quick Start

```bash
# Check that the saved token works and show the account username
envato auth status

# Search CodeCanyon (newest first, 20 results)
envato search "wordpress dropbox"

# Best sellers first, as a table
envato search "wordpress dropbox" --sort sales --desc --limit 10 --table

# One item by ID
envato item 5529125
```

## Commands

### Authentication (`envato auth`)

The token is an Envato personal token with the "View and search Envato sites" and "View the user's Envato Account username" permissions. It lives in the CLI-tools secret manager as `envato-api-token`; the profile `.env` only holds the `secret://envato-api-token` reference.

```bash
# Interactive login (prompts for the personal token and stores it in the secret manager)
envato auth login

# Force re-authentication
envato auth login --force

# Check authentication status (live username lookup; includes "username")
envato auth status

# Run the configured live auth test
envato auth test

# Clear saved credentials/session
envato auth logout
```

### Profiles (`envato auth profiles`)

```bash
# List all profiles
envato auth profiles list

# Show a profile
envato auth profiles get default

# Select the active profile for its auth type
envato auth profiles select PROFILE_NAME

# Create a profile
envato auth profiles create PROFILE_NAME

# Delete a profile
envato auth profiles delete PROFILE_NAME
```

### Search (`envato search`)

Returns a JSON array of items. `--site`, `--sort`/`--desc`, `--page`, and `--limit` are sent to Envato's search API; `--filter` and `--properties` apply to the returned page.

```bash
# Search CodeCanyon (the default site), newest first
envato search "wordpress dropbox"

# Pick the site by short name or domain
envato search "portfolio" --site themeforest
envato search "portfolio" --site themeforest.net

# Sort: newest (default), updated, price, sales, rating, relevance
envato search "wordpress dropbox" --sort sales --desc
envato search "wordpress dropbox" --sort price
envato search "wordpress dropbox" --sort relevance

# Page size (1-100, default 20) and page number (1-60)
envato search "wordpress dropbox" --limit 100 --page 2

# Filter the returned page and choose fields
envato search "wordpress dropbox" --filter "number_of_sales:gt:100" --properties "id,title,number_of_sales,rating"

# Table output
envato search "wordpress dropbox" --limit 10 --table
```

| Option | Short | Description |
|--------|-------|-------------|
| `--site` | | `codecanyon` (default), `themeforest`, `videohive`, `audiojungle`, `graphicriver`, `photodune`, `3docean`, or the `.net` domain |
| `--sort` | `-s` | `newest` (default), `updated`, `price`, `sales`, `rating`, `relevance` |
| `--desc` | `-d` | Reverse the sort's natural direction (`newest`/`updated` are newest-first; `price`/`sales`/`rating` are low-to-high). Not valid with `relevance` |
| `--page` | `-P` | Result page, 1-60 |
| `--limit` | `-l` | Results per page, 1-100 (default 20) |
| `--filter` | `-f` | Filter the returned page using `field:op:value` |
| `--properties` | `-p` | Restrict output to selected fields |
| `--table` | `-t` | Display as a table |

### Item (`envato item`)

Returns one JSON object with the same shape as a search result.

```bash
# Get one item
envato item 5529125

# Table output
envato item 5529125 --table

# Selected fields
envato item 5529125 --properties "title,number_of_sales,rating,rating_count"
```

An unknown ID exits `1` with `Error: HTTP 404: Item not found with that ID` on stderr.

## Output Formats

- JSON is the default output format (stdout carries data only; messages and errors go to stderr).
- Add `--table` / `-t` for human-readable table output.

## AI Instruction Results

Commands that reach a non-deterministic boundary may return an AI instruction result instead of normal resource data. This is JSON on stdout with `type: "ai_instruction"` and tells the calling AI agent what objective to complete, what context is available, what tools are allowed, and what success means.

The CLI must not call an LLM or include required pre-action command lists. Optional `verification_commands` and `follow_up_commands` may appear only for actions to run after the agent completes the instruction.

### JSON Output Example

```bash
envato item 5529125
```

```json
{
  "id": 5529125,
  "title": "Out-of-the-Box | Dropbox plugin for WordPress",
  "url": "https://codecanyon.net/item/outofthebox-dropbox-plugin-for-wordpress-/5529125",
  "price": 69.0,
  "number_of_sales": 8184,
  "rating": 4.83,
  "rating_count": 236,
  "published_at": "2013-09-10T22:10:47+10:00",
  "updated_at": "2026-10-14T20:43:58+11:00",
  "site": "codecanyon.net"
}
```

### Table Output Example

```bash
envato search "wordpress dropbox" --sort sales --desc --limit 5 --table
```

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

Non-authentication configuration is stored in `~/.local/share/cli-tools/envato/.env`. CLI-managed runtime auth state is stored in the active profile at `~/.local/share/cli-tools/envato/authentication_profiles/<profile>/.env`. The source repo only carries `.env.example`.

Reusable CLI credentials that agents or scripts need to store/retrieve are governed by the repo-owned `cli-tool` skill's `references/secrets.md`.

Do not put reusable credentials in any `.env` file. Store and retrieve them through `<cli-tools-root>/_repo/_secret-manager/secrets.sh`. `.env` files are limited to non-secret config and CLI-managed runtime auth state.

Root config variables:

```bash
# Optional: override the default API base URL
BASE_URL=https://api.envato.com

# Optional: response cache settings
CACHE_ENABLED=true
CACHE_TTL=3600
```

Authentication profile variables (written by `envato auth login`):

```bash
ACTIVE=true
PERSONAL_ACCESS_TOKEN=secret://envato-api-token
```

To rotate the token, store the new value in the secret manager:

```bash
<cli-tools-root>/_repo/_secret-manager/secrets.sh set envato-api-token
```


## Cache

```bash
# Clear cached read responses
envato cache clear

# Bypass the cache for one execution
envato --no-cache search "wordpress dropbox"
```


## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error (bad option value, 404, other API errors) |
| 2 | Authentication/credential error (missing or rejected token), or a Typer usage error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### Top CodeCanyon sellers for a niche

```bash
envato search "wordpress backup" --sort sales --desc --limit 50 --properties "id,title,price,number_of_sales,rating,updated_at"
```

### Stale best sellers (not updated recently)

```bash
envato search "wordpress dropbox" --sort sales --desc --limit 100 --filter "updated_at:lt:2023-01-01"
```

## Output Contract

`search` returns an array of item records; `item` returns one item record. Both use this shape:

| Field | Description |
|-------|-------------|
| `id` | Envato item ID |
| `title` | Item name |
| `url` | Item page URL |
| `price` | Price in US dollars (`price_cents / 100`) |
| `number_of_sales` | Lifetime sales count |
| `rating` | Average rating (0.0 when unrated) |
| `rating_count` | Number of ratings |
| `published_at` | First publish timestamp (ISO 8601) |
| `updated_at` | Last update timestamp (ISO 8601) |
| `site` | Envato site domain, e.g. `codecanyon.net` |

## Requirements

- Python 3.11+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests

## License

MIT
