# Kick CLI - Claude Instructions

## Overview

This is a CLI tool for [Kick.co](https://www.kick.co) - an AI-powered "self-driving bookkeeping" platform. Kick automates financial management tasks including transaction categorization, receipt matching, and deduction tracking. The platform is backed by OpenAI and General Catalyst and auto-categorizes approximately 95% of transactions.

**Always read the README.md file first** when working with this CLI tool.

## Platform Context

Kick.co provides:
- AI-driven automatic transaction categorization
- Real-time financial reports (P&L statements, etc.)
- Integrations with Stripe, PayPal, Mercury, Gusto, Ramp
- Multi-entity support (business and personal accounts)
- Automated tax preparation workflows
- Rule-based categorization system

**Current limitations**: US-only availability, not suited for heavy inventory/fixed assets/complex e-commerce

## Architecture

### Directory Structure
```
kick/
├── kick_cli/
│   ├── __init__.py          # Version info
│   ├── main.py              # CLI entry point (Typer app)
│   ├── client.py            # KickClient - API client with retry logic
│   ├── config.py            # Configuration & OAuth token management
│   ├── output.py            # Table/JSON output formatting
│   ├── filters.py           # Filter parsing utilities
│   ├── filter_map.py        # Filter field mappings
│   └── commands/
│       ├── auth.py          # Authentication (OAuth PKCE)
│       ├── transactions.py  # Transaction management
│       ├── categories.py    # Category listing
│       ├── clients.py       # Client/counterparty management
│       ├── workspaces.py    # Workspace operations
│       ├── entities.py      # Entity operations
│       ├── statistics.py    # Aggregate statistics
│       └── rule_groups.py   # Rule group management
├── .env                     # OAuth tokens (auto-managed)
└── pyproject.toml           # Package configuration
```

### Key Components

1. **KickClient** (`client.py`): Central API client with:
   - Automatic token refresh when expired
   - Exponential backoff retry for transient errors (429, 5xx)
   - Retry-After header support
   - Filter translation to API query parameters

2. **Config** (`config.py`): Manages OAuth tokens via `.env` file
   - Uses Auth0 domain: `auth.kick.co`
   - API base URL: `https://use.kick.co`

3. **Commands**: Follow Typer pattern with `list`, `get`, `create`, `update`, `delete` operations

## Authentication

Uses **Auth0 OAuth with PKCE flow** (not API keys):
- User runs `kick auth login` to authenticate via browser
- Tokens stored in `.env` file in package directory
- Automatic token refresh handled by KickClient
- `kick auth refresh` for manual token refresh
- `kick auth logout` clears stored credentials

## API Patterns

### Resource Hierarchy
```
Workspace → Entities → Transactions
         ↳ Categories
         ↳ Clients (Counterparties)
         ↳ Rule Groups → Rules
```

### Common API Endpoints
- `GET /api/workspaces/` - List workspaces with entities
- `GET /api/transactions/` - List transactions (paginated)
- `GET /api/category/{workspaceId}` - List categories
- `GET /api/counterparty` - List clients
- `GET /api/rule-groups/{workspaceId}` - List rule groups

### Filter System
CLI filters use `field:value` or `field:op:value` syntax:
```bash
kick transactions list --filter "minAmount:1000"
kick transactions list --filter "direction:in"
kick clients list --filter "name:like:%Acme%"
```

Supported transaction filters: `minAmount`, `maxAmount`, `category`, `status`, `type`, `dateFrom`, `dateTo`, `direction`

## Development Guidelines

### Adding New Commands

1. Create new command module in `kick_cli/commands/`
2. Use Typer pattern:
   ```python
   app = typer.Typer()

   @app.command("list")
       client = get_client()
       result = client.list_items()
       output(result, as_table=table)
   ```
3. Register in `main.py`: `app.add_typer(module.app, name="items")`

### Adding New API Methods

Add to `KickClient` class in `client.py`:
- Use `_make_request()` for all API calls (handles auth, retry)
- Get workspace ID via `get_default_workspace_id()` if needed
- Follow existing method patterns for consistency

### Output Formatting

Use `output()` from `output.py`:
- JSON output (default): Machine-readable

### Error Handling

- Raise `ClientError` for API/auth errors
- Exit code 2 for authentication errors
- Exit code 1 for general errors
- Exit code 130 for user interrupts

## Testing Commands

```bash
# Authentication
kick auth status

# List resources
kick transactions list --limit 10
kick categories list --parents-only
kick clients list
kick entities list
kick workspaces list

# Filter examples
kick transactions list --filter "direction:in"
kick transactions list --filter "minAmount:500" --limit 20
```

## Important Notes

1. **Workspace context**: Most operations require a workspace ID, auto-fetched if not provided
2. **Entity filtering**: Transactions are filtered by entity IDs within a workspace
3. **Pagination**: API limits to 100 items per page; use `--page` and `--limit`
4. **Rate limiting**: Client handles 429 responses with exponential backoff
5. **Token expiry**: Tokens auto-refresh 5 minutes before expiration
