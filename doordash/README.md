# DoorDash CLI

## DESCRIPTION

The `doordash` CLI provides a command-line interface for Doordash (browser automation).

Use it when you need repeatable access to doordash workflows that are only available through a signed-in website.

## Installation

```bash
cd doordash
pip install -e .

# Install Playwright browsers (required once)
playwright install chromium
```

After installation, the `doordash` command will be available in your terminal.

### Live browser auth (optional `webwright`)

`doordash auth login` and `doordash reorder` drive real local Chrome over CDP via the shared `WebwrightBrowserAutomation` (`local_cdp` mode), which lazy-imports [microsoft/Webwright](https://github.com/microsoft/Webwright) at browser-open time. Webwright is Git-only (not on PyPI), so it is intentionally **not** a resolved dependency — pinning it would make this CLI's environment non-portable. Install it out-of-band on any host that runs live DoorDash auth:

```bash
uv tool install -e doordash --with 'webwright @ git+https://github.com/microsoft/Webwright.git'
```

If webwright is absent, the CLI raises a clear error with this exact install command. Commands that don't open a browser (`orders`, `stores`, `auth status`) work without it.

## Quick Start

```bash
# Login to DoorDash (opens browser once)
doordash auth login

# Check login status
doordash auth status

# List recent orders
doordash orders list

# Get order details
doordash orders get ORDER_ID

# List nearby stores
doordash stores list
```

## Commands

### Authentication (`doordash auth`)

```bash
# Interactive login (opens browser)
doordash auth login

# Force re-login (clears existing session)
doordash auth login --force

# Check authentication status
doordash auth status
doordash auth status --table

# Test if session is valid
doordash auth test

# Clear stored session
doordash auth logout
```

### Orders (`doordash orders`)

```bash
# List recent orders (JSON output)
doordash orders list

# List orders with table format
doordash orders list --table

# Limit number of results
doordash orders list --limit 10

# Filter orders by status
doordash orders list --filter "current_status:delivered"

# Select specific properties
doordash orders list -p id,store,total

# Get order details
doordash orders get ORDER_ID
doordash orders get ORDER_ID --table
```

### Stores (`doordash stores`)

```bash
# List available stores
doordash stores list

# List stores with table format
doordash stores list --table

# Limit number of results
doordash stores list --limit 20

# Filter stores
doordash stores list --filter "is_open:eq:true"

# Select specific properties
doordash stores list -p id,name,rating

# Get a store by ID from the current store list
doordash stores get STORE_ID
doordash stores get STORE_ID --table
```

### Cache (`doordash cache`)

```bash
# Clear cached API responses
doordash cache clear
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping
- **Table** (`--table`): Human-readable tabular format

```bash
# Pipe JSON output to jq
doordash orders list | jq '.[0].store.name'

# Display as table
doordash orders list --table
```

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display output as table |
| `--limit` | `-l` | Maximum number of results |
| `--filter` | `-f` | Filter expression (e.g., `status:delivered`) |
| `--properties` | `-p` | Comma-separated list of properties to include |
| `--force` | `-F` | Force action (skip checks/confirmation) |
| `--version` | `-v` | Show version and exit |

## Configuration

Configuration is stored in `.env` file:

```bash
# Base URL
BASE_URL=https://www.doordash.com

# Default delivery address
ADDRESS="123 Main St"
LATITUDE=38.0505
LONGITUDE=-87.5005

# Browser settings (true = invisible, false = visible browser)
HEADLESS=true
```

Session data is stored in the standard `cli_tools_shared` profile directory for persistence between commands.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Architecture

This CLI uses a hybrid approach:

1. **Browser Authentication**: Opens Chrome browser once for secure OAuth login
2. **GraphQL API**: All subsequent data operations use pure HTTP calls with saved session cookies

This provides:
- **Security**: Proper OAuth flow, no password storage
- **Speed**: API calls are much faster than browser automation
- **Reliability**: No flaky DOM selectors or page timing issues

### Session Persistence

After logging in once, your session is saved in the active `cli_tools_shared` profile. The CLI will use this session for all API calls until it expires.

If the session expires, you'll see an error message prompting you to run `doordash auth login` again.

## Models

This CLI uses Pydantic models for type-safe data handling. All commands return strongly-typed models.

### Available Models

| Model | Description | Key Fields |
|-------|-------------|------------|
| `Order` | Order summary | `id`, `store`, `order_total`, `current_status` |
| `OrderDetail` | Full order details | All Order fields + `items`, `delivery_eta` |
| `Restaurant` | Restaurant info | `id`, `name`, `rating`, `cuisines` |

### Order Status Values

- `pending`, `confirmed`, `preparing`, `ready_for_pickup`
- `out_for_delivery`, `delivered`, `cancelled`

### Fulfillment Types

- `delivery`, `pickup`

## Requirements

- Python 3.9+
- Google Chrome browser (for authentication)
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - playwright
  - pydantic
  - httpx

## Debugging

To debug authentication issues:

```bash
# Run with visible browser
export HEADLESS=false
doordash auth login
```

To test if your session is still valid:

```bash
doordash auth test --verbose
```

## License

MIT
