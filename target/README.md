# Target CLI

## DESCRIPTION

A command-line interface for [Target](https://www.target.com) using browser automation. Target consumer CLI for searching products, adding to cart, and checking out.

Use this CLI when you need repeatable access to Target workflows that are only available through the website.

## Installation

```bash
cd <cli-tools-root>/target
uv tool install -e . --force --refresh
```

Browser automation is driven by `browser-harness` (CDP), a transitive
dependency of `cli-tools-shared`. No separate "install browsers" step is
required — the harness manages its own browser binary.

After installation, the `target` command will be available in your terminal.

## Quick Start

```bash
# Authenticate with Target
target auth login

# Search for items
target search query "search terms" --limit 10 --table

# Get item details
target search item ITEM_ID --table
```

## Commands

### Authentication (`target auth`)

```bash
# Interactive login
target auth login

# Force re-authentication
target auth login --force

# Check authentication status
target auth status

# Run the configured live auth test
target auth test

# Clear saved credentials/session
target auth logout
```

### Profiles (`target auth profiles`)

```bash
# List all profiles
target auth profiles list

# Show a profile
target auth profiles get default

# Select the active profile for its auth type
target auth profiles select PROFILE_NAME

# Create a profile
target auth profiles create PROFILE_NAME

# Delete a profile
target auth profiles delete PROFILE_NAME
```



### Search (`target search`)

```bash
# Search for items (JSON output)
target search query "search terms"

# Search with table format
target search query "search terms" --table

# Limit results
target search query "search terms" --limit 10

# Filter results
target search list --filter "status:eq:active"

# Restrict output fields
target search list --properties "id,name"

# Get item details
target search item ITEM_ID

# List all items
target search list --table
```

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

Non-authentication configuration is stored in `~/.local/share/cli-tools/target/.env`. CLI-managed runtime auth state is stored in the active profile at `~/.local/share/cli-tools/target/authentication_profiles/<profile>/.env`. The source repo only carries `.env.example`.

Reusable CLI credentials that agents or scripts need to store/retrieve are governed by the user-level `cli-tool` skill's `references/secrets.md`.

Do not put reusable credentials in any `.env` file. Store and retrieve them through `<cli-tools-root>/_repo/_secret-manager/secrets.sh`. `.env` files are limited to non-secret config and CLI-managed runtime auth state.

Root config variables:

```bash
# Optional: override the default site URL
BASE_URL=https://www.target.com

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
target cache clear

# Bypass the cache for one execution
target --no-cache search list --limit 10
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

- **First run**: Run `target auth login` to launch the persistent browser session and complete login
- **Headless mode**: Set `HEADLESS=false` to watch the browser during debugging
- **Session persistence**: Login sessions are saved under the active profile's browser-data directory
- **Rate limiting**: Be respectful of the site's terms of service

## Debugging

To debug browser automation issues:

```bash
# Run with visible browser
export HEADLESS=false
target search query "test"
```

## Output Contract

Commands return plain JSON records. The default item record shape is:

| Field | Description |
|-------|-------------|
| `id` | Stable item identifier from the page |
| `name` | Item display name |
| `status` | Item status |

Capture real DOM data first, then update `normalize_items()` and `normalize_item_detail()` in `parsers.py` to map page data into the documented command output. Add local models only when validation, polymorphism, or serialization removes real complexity.

## Requirements

- Python 3.11+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - cli-tools-shared (transitively pulls in browser-harness)

## License

MIT
