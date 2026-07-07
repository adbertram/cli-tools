# Poshmark CLI

## DESCRIPTION

A browser-automation command-line interface for Poshmark. Use this CLI to search
Poshmark listings from the terminal when no official API is available.

## Docs

- Website: https://poshmark.com


## Installation

```bash
cd <cli-tools-root>/poshmark
uv tool install -e . --force --refresh
```

Browser automation is driven by `browser-harness` (CDP), a transitive
dependency of `cli-tools-shared`. No separate "install browsers" step is
required — the harness manages its own browser binary.

After installation, the `poshmark` command will be available in your terminal.

## Quick Start

```bash
# Search for listings
poshmark listings search "nike shoes" --limit 10 --table

# Get raw JSON output
poshmark listings search "nike shoes" --limit 5
```

## Commands

### Authentication (`poshmark auth`)

Authentication is only required for authenticated Poshmark workflows; basic
listing search works without logging in.

```bash
# Interactive login
poshmark auth login

# Force re-authentication
poshmark auth login --force

# Check authentication status
poshmark auth status

# Run the configured live auth test
poshmark auth test

# Clear saved credentials/session
poshmark auth logout
```

### Profiles (`poshmark auth profiles`)

```bash
# List all profiles
poshmark auth profiles list

# Show a profile
poshmark auth profiles get default

# Select the active profile for its auth type
poshmark auth profiles select PROFILE_NAME

# Create a profile
poshmark auth profiles create PROFILE_NAME

# Delete a profile
poshmark auth profiles delete PROFILE_NAME
```



### Listings (`poshmark listings`)

```bash
# Search for listings (JSON output)
poshmark listings search "nike shoes"

# Search with table format
poshmark listings search "nike shoes" --table

# Limit results
poshmark listings search "nike shoes" --limit 10

# Restrict output fields
poshmark listings search "nike shoes" --properties "id,title,price"
```

## Output Formats

- JSON is the default output format.
- Add `--table` / `-t` for human-readable table output.

## AI Instruction Results

Commands that reach a non-deterministic boundary may return an AI instruction result instead of normal resource data. This is JSON on stdout with `type: "ai_instruction"` and tells the calling AI agent what objective to complete, what context is available, what tools are allowed, and what success means.

The CLI must not call an LLM or include required pre-action command lists. Optional `verification_commands` and `follow_up_commands` may appear only after the agent completes the instruction.

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display data as a table |
| `--limit` | `-l` | Maximum number of results |
| `--properties` | `-p` | Restrict output to selected fields |
| `--version` | `-v` | Show version and exit |
| `--no-cache` |  | Bypass cached read responses for this execution |

## Configuration

Non-authentication configuration is stored in `~/.local/share/cli-tools/poshmark/.env`. CLI-managed runtime auth state is stored in the active profile at `~/.local/share/cli-tools/poshmark/authentication_profiles/<profile>/.env`. The source repo only carries `.env.example`.

Reusable CLI credentials that agents or scripts need to store/retrieve are governed by the user-level `cli-tool` skill's `references/secrets.md`.

Do not put reusable credentials in any `.env` file. Store and retrieve them through `<cli-tools-root>/_repo/_secret-manager/secrets.sh`. `.env` files are limited to non-secret config and CLI-managed runtime auth state.

Root config variables:

```bash
# Optional: override the default site URL
BASE_URL=https://poshmark.com

# Browser settings (true = invisible, false = visible browser)
# Poshmark blocks headless automation, so the CLI defaults to headed.
HEADLESS=false

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
poshmark cache clear

# Bypass the cache for one execution
poshmark --no-cache listings search "nike shoes" --limit 10
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

### Customizing for Your Site

1. Update `browser.py` with the real login/authenticated selectors and URLs.
2. Implement the placeholder methods in `client.py`.
3. Normalize extracted page data in `parsers.py` to the documented command output.

## Browser Automation Notes

- **First run**: Run `poshmark auth login` to launch the persistent browser session and complete login
- **Headless mode**: Poshmark blocks headless Chrome; the CLI defaults to headed (`HEADLESS=false`)
- **Session persistence**: Login sessions are saved under the active profile's browser-data directory
- **Rate limiting**: Be respectful of the site's terms of service

## Debugging

To debug browser automation issues:

```bash
# Run with visible browser (default for this CLI)
export HEADLESS=false
poshmark listings search "nike shoes"
```

## Output Contract

Commands return plain JSON records. The listing search record shape is:

| Field | Description |
|-------|-------------|
| `id` | Stable Poshmark listing id |
| `lister_id` | Seller user id |
| `title` | Item title |
| `price` | Listing price (e.g. "$42") |
| `size` | Item size (e.g. "US 5") |
| `image` | Cover image URL |
| `url` | Absolute Poshmark listing URL |

Capture real DOM data first, then update `normalize_items()` and `normalize_item_detail()` in `parsers.py` to map page data into the documented command output. Add local models only when validation, polymorphism, or serialization removes real complexity.

## Requirements

- Python 3.11+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - cli-tools-shared (transitively pulls in browser-harness)

## License

MIT
