# Instacart CLI

A command-line interface for Instacart using browser session authentication. Manage orders, view carts, and access your Instacart account from the terminal.

## Authentication

This CLI uses browser session cookies for authentication (not API keys). This approach works for consumer accounts.

### How to Authenticate

1. Use Playwright MCP to open https://www.instacart.com
2. Log in to your account
3. Capture cookies using `browser_run_code` to get cookies from the page context
4. Save the session to `~/.local/share/cli-tools/instacart/authentication_profiles/default/session.json`

The session.json file should contain:
```json
{
  "cookies": [...],
  "graphql_endpoint": "https://www.instacart.com/graphql",
  "persisted_queries": {
    "OrderDeliveriesConnection": {"sha256Hash": "...", "variables": {...}},
    ...
  }
}
```

## Installation

```bash
cd <cli-tools-root>/instacart
pip install -e .
```

After installation, the `instacart` command will be available in your terminal.

## Quick Start

```bash
# Check authentication status
instacart auth status

# List orders
instacart orders list

# View your carts
instacart user carts

# Get user info
instacart user me
```

## Commands

### Authentication

```bash
# Show authentication instructions
instacart auth login

# Force re-authentication (clears existing session)
instacart auth login --force

# Check authentication status
instacart auth status
instacart auth status --table

# Clear stored session
instacart auth logout
```

### Orders

```bash
# List all orders (JSON output)
instacart orders list

# List orders with table format
instacart orders list --table

# Limit results
instacart orders list --limit 10

# Filter by status
instacart orders list --filter "status:eq:delivered"

# Select specific fields
instacart orders list --properties "order_id,status,store_name"

# Get a specific order
instacart orders get ORDER_ID
instacart orders get ORDER_ID --table

# Track order delivery
instacart orders track ORDER_ID
instacart orders track ORDER_ID --table
```

### User Account

```bash
# Get current user info
instacart user me
instacart user me --table

# List delivery addresses
instacart user addresses
instacart user addresses --table

# View active shopping carts
instacart user carts
instacart user carts --table
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping
- **Table** (`--table` or `-t`): Human-readable formatted table

### JSON Output Example

```bash
instacart orders list --limit 2
```

### Table Output Example

```bash
instacart orders list --limit 5 --table
```

## Filtering

The `--filter` option supports the following operators:

| Operator | Description | Example |
|----------|-------------|---------|
| `eq` | Equal | `--filter "status:eq:delivered"` |
| `ne` | Not equal | `--filter "status:ne:canceled"` |
| `gt` | Greater than | `--filter "total.value:gt:100"` |
| `gte` | Greater than or equal | `--filter "created_at:gte:2024-01-01"` |
| `lt` | Less than | `--filter "total.value:lt:50"` |
| `lte` | Less than or equal | `--filter "quantity:lte:5"` |
| `like` | Pattern match | `--filter "store_name:like:ALDI*"` |
| `in` | In list | `--filter "status:in:pending,delivered"` |

Multiple filters can be combined:
```bash
instacart orders list --filter "status:eq:delivered" --filter "created_at:gte:2024-01-01"
```

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display output as formatted table |
| `--limit` | `-l` | Maximum number of results (default: 10) |
| `--filter` | `-f` | Filter results (field:op:value) |
| `--properties` | `-p` | Comma-separated fields to include |
| `--force` | `-F` | Force operation (e.g., clear session) |
| `--version` | `-v` | Show version and exit |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### List Orders and Filter with jq

```bash
# Get all order IDs
instacart orders list | jq '.[].order_id'

# Get delivered orders from a specific store
instacart orders list | jq '.[] | select(.store_name == "ALDI") | {id: .order_id, status: .status}'
```

### Export Orders to JSON File

```bash
instacart orders list --limit 100 > orders.json
```

### View Cart Items

```bash
# Get all items in your carts
instacart user carts | jq '.[].items[].name'
```

## Technical Details

### GraphQL API

This CLI uses Instacart's internal GraphQL API with persisted queries. The persisted queries are identified by sha256 hashes rather than full query strings.

### Session Storage

Session data is stored in `~/.local/share/cli-tools/instacart/authentication_profiles/<profile>/session.json` and includes:
- Browser cookies for authentication
- GraphQL endpoint URL
- Persisted query hashes and default variables

### Limitations

- **Order creation**: Creating orders requires cart operations and checkout flow which are not yet supported. Use the Instacart website or app to create orders.
- **Session expiration**: Browser sessions may expire. Re-authenticate by capturing new cookies when API calls fail.

## Requirements

- Python 3.9+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests
  - pydantic
  - rich

## License

MIT

## Additional Commands

### Cache

```bash
instacart cache --help
```
