# Monarch CLI - Claude Instructions

Always read the README.md file first when working with this CLI tool.

## Key Concepts

- **SDK wrapper**: Wraps `monarchmoney` Python library directly (not subprocess)
- **Async handling**: All SDK methods are async, wrapped with `asyncio.run()`
- **Session persistence**: Uses `.profiles/<profile>/mm_session.pickle` for session caching

## Architecture

```
monarch <command> --> client.py --> monarchmoney SDK --> Monarch API
                           |
                     asyncio.run()
```

## Important Notes

1. **Authentication**: Email/password with optional TOTP MFA
2. **Session management**: Session pickle stored at `.profiles/<profile>/mm_session.pickle` (CLI-managed, not SDK default `~/.mm/`)
3. **API domain**: `api.monarch.com` (changed from `api.monarchmoney.com` in SDK v1.3.0). The SDK's `MonarchMoneyEndpoints.BASE_URL` controls this, not the CLI config.
4. **MFA_SECRET**: Can be either a base32 TOTP secret (for auto-generation) or a one-time numeric code. TOTP secrets are preferred for non-interactive use.
5. **Server-side filtering**: `get_transactions()` supports date/category/account filters
6. **Response structure**: API returns nested dicts that need extraction

## Command Groups

- `auth` - Login, logout, status
- `accounts` - List, get, history, holdings, sync
- `transactions` - List, get, update, recurring
- `budgets` - List (with month filter)
- `categories` - List
- `category-groups` - List, get
- `tags` - List
- `cashflow` - Summary, list
- `institutions` - List
- `merchants` - List, get (extracted from cashflow byMerchant data)
