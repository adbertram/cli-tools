# Kick CLI

A command-line interface for [Kick.co](https://www.kick.co) - the self-driving bookkeeping platform.

## Installation

```bash
cd kick
pip install -e .
```

After installation, the `kick` command will be available in your terminal.

## Quick Start

```bash
# Authenticate with Kick (opens browser)
kick auth login

# Check authentication status
kick auth status

# List recent transactions
kick transactions list
```

## Commands

### Authentication

Kick CLI uses Auth0 OAuth with PKCE for secure authentication. When you run `kick auth login`, it will:
1. Open your browser to sign in with your Kick account
2. After signing in, copy the URL from your browser
3. Paste it to complete authentication

```bash
# Login (opens browser for OAuth)
kick auth login

# Check authentication status
kick auth status
kick auth status

# Refresh access token
kick auth refresh

# Clear stored credentials
kick auth logout
```

### Transactions

```bash
# List transactions (JSON output)
kick transactions list

# List with table format
kick transactions list

# Limit results
kick transactions list --limit 50

# Pagination
kick transactions list --page 1 --limit 50

# Filter by entity
kick transactions list --entity-id 16044

# Sort options
kick transactions list --sort-field date --sort-order ASC

# Get a specific transaction
kick transactions get 12345
kick transactions get 12345

# Filter transactions
kick transactions list --filter "minAmount:1000"
kick transactions list --filter "category:01956661-459c-74c3-94d8-b52a43fbae24"
kick transactions list --filter "direction:in"  # Money in only
kick transactions list --filter "direction:out" # Money out only

# Update a transaction
kick transactions update 12345 --category-id 01956661-459c-74c3-94d8-b52a43fbae24
kick transactions update 12345 --counterparty-id 019129dd-96c6-7747-ba23-3c1b5b2066e6
kick transactions update 12345 --account-id 019493a3-193e-790f-9f0c-c8c0fc21383b
kick transactions update 12345 --memo "Payment for invoice #123"
kick transactions update 12345 -c 01956661-459c-74c3-94d8-b52a43fbae24 -m "Note"

# Search transactions by text
kick transactions search "query"
kick transactions search "cursor"
kick transactions search "amazon" --limit 50
kick transactions search "payment" --filter "direction:out"
kick transactions search "AWS" --case-sensitive
```

### Clients

```bash
# List clients
kick clients list
kick clients list
kick clients list --limit 100

# Filter clients by name
kick clients list --filter "name:Acme"
kick clients list --filter "name:like:%Test%"
kick clients list --filter "name:ilike:%test%"  # Case-insensitive

# Get a specific client
kick clients get 019b7021-bfa4-7a86-b46f-304afb384221
kick clients get 019b7021-bfa4-7a86-b46f-304afb384221

# Create a new client
kick clients create "Acme Corporation"
kick clients create "New Client"
```

### Categories

```bash
# List all categories
kick categories list
kick categories list

# List parent categories only (no subcategories)
kick categories list --parents-only

# Get a specific category
kick categories get 01956661-459c-74c3-94d8-b52a43fbae24
kick categories get 01956661-459c-74c3-94d8-b52a43fbae24
```

### Workspaces

```bash
# List workspaces
kick workspaces list
kick workspaces list

# Get workspace details
kick workspaces get
kick workspaces get 019409a4-f7bd-7282-8325-3a417b0c7cd3
```

### Entities

Entities are business or personal units used to organize transactions.

```bash
# List entities
kick entities list
kick entities list

# Get entity details
kick entities get 16044
kick entities get 16044
```

### Statistics

Get aggregate transaction statistics.

```bash
# Get statistics for all entities
kick statistics get
kick statistics get

# Get statistics for specific entity
kick statistics get --entity-id 16044
```

### Rule Groups

Manage categorization rules that automatically assign categories to transactions.

```bash
# List rule groups
kick rule-groups list
kick rule-groups list
kick rule-groups list --type all
kick rule-groups list --include-rules

# Get a specific rule group
kick rule-groups get 43b5276c-57a5-4c5f-bf76-c71675d8662a
kick rule-groups get 43b5276c-57a5-4c5f-bf76-c71675d8662a
kick rule-groups get 43b5276c-57a5-4c5f-bf76-c71675d8662a --no-rules

# Create a rule group
kick rule-groups add "My Rules"
kick rule-groups add "Accounting Rules" --type accounting --icon bank

# Delete a rule group
kick rule-groups delete 019b6ff1-0d3b-76ad-8063-22dd79ef4402
kick rule-groups delete 019b6ff1-0d3b-76ad-8063-22dd79ef4402 --force

# List all rules across groups
kick rule-groups rules list
kick rule-groups rules list
kick rule-groups rules list --group 43b5276c-57a5-4c5f-bf76-c71675d8662a

# Add a rule to a group
kick rule-groups rules add -g <group-id> -c "Vendor Name" -e "Entity Name" --category "Category"

# Delete a rule
kick rule-groups rules delete <rule-id>
kick rule-groups rules delete <rule-id> --force

# View available condition and action types
kick rule-groups rules conditions
kick rule-groups rules actions
```

### Integrations

View and manage linked financial accounts (banks via Plaid, PayPal, Stripe, etc.).

```bash
# List all integrations
kick integrations list
kick integrations list
kick integrations list --provider Plaid

# Get integration details
kick integrations get 8531
kick integrations get 8531
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping

### JSON Output Example

```bash
kick transactions list --limit 2
```

```json
{
  "data": [...],
  "total": 10359,
  "pageCount": 2072,
  "page": 0
}
```

### Table Output Example

```bash
kick transactions list --limit 5
```

```
ID        Date        Description       Category              Amount  Status
-----------------------------------------------------------------------------
49604983  2025-12-29  BrickLink Order   Merchant & Bank Fees  -$1.85  completed
...
Showing 5 of 10359 transactions (page 1 of 2072)
```

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--limit` | `-l` | Maximum number of results (default: 100, max: 100) |
| `--page` | `-p` | Page number, 0-indexed (default: 0) |
| `--filter` | `-f` | Filter results (field:value format) |
| `--entity-id` | `-e` | Filter by entity ID |
| `--sort-field` | | Field to sort by (default: date) |
| `--sort-order` | | Sort order: ASC or DESC (default: DESC) |
| `--version` | `-v` | Show version and exit |

### Filter Fields (Transactions)

| Filter | Example | Description |
|--------|---------|-------------|
| `minAmount` | `--filter "minAmount:1000"` | Minimum transaction amount |
| `maxAmount` | `--filter "maxAmount:500"` | Maximum transaction amount |
| `category` | `--filter "category:UUID"` | Filter by category UUID |
| `direction` | `--filter "direction:in"` | Money direction: `in` or `out` |
| `status` | `--filter "status:completed"` | Transaction status |
| `type` | `--filter "type:external"` | Transaction type |
| `dateFrom` | `--filter "dateFrom:2024-01-01"` | Start date |
| `dateTo` | `--filter "dateTo:2024-12-31"` | End date |

## Configuration

Authentication profile files live under `~/.local/share/cli-tools/kick/authentication_profiles/<profile>/`; non-auth defaults live in `~/.local/share/cli-tools/kick/.env`. They are managed automatically after `kick auth login`.

```bash
# OAuth tokens (managed automatically after login)
KICK_ACCESS_TOKEN=<access_token>
KICK_REFRESH_TOKEN=<refresh_token>
KICK_TOKEN_EXPIRES_AT=<timestamp>

# API Base URL (optional - defaults to production)
KICK_BASE_URL=https://use.kick.co
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Requirements

- Python 3.9+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests

## License

MIT

## Additional Commands

### Cache

```bash
kick cache --help
```
