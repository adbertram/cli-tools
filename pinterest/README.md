# Pinterest CLI

Command-line access to Pinterest API v5 for authenticated account, board, and pin reads.

Docs used for this CLI:
- OAuth setup: https://developers.pinterest.com/docs/getting-started/set-up-authentication-and-authorization/
- First API call: https://developers.pinterest.com/docs/getting-started/make-an-api-call/
- Boards and Pins guide: https://developers.pinterest.com/docs/work-with-organic-content-and-users/create-boards-and-pins/

## Installation

```bash
cd <cli-tools-root>/pinterest
uv tool install -e . --force
```

## Quick Start

```bash
pinterest auth login
pinterest account list
pinterest account get
pinterest boards list --table
pinterest pins list --limit 10
```

## Command Surface

### Account

```bash
# List the authenticated account as a single-item collection
pinterest account list

# Table output
pinterest account list --table

# Get the authenticated Pinterest account
pinterest account get

# Validate the current account against its ID
pinterest account get ACCOUNT_ID

# Show a subset of fields
pinterest account get --properties "id,username,monthly_views"

# Table output
pinterest account get --table
```

### Boards

```bash
# List boards
pinterest boards list

# Table output
pinterest boards list --table

# Limit via API page_size
pinterest boards list --limit 10

# Filter boards by privacy
pinterest boards list --filter "privacy:eq:SECRET"

# Select output fields
pinterest boards list --properties "id,name,privacy,created_at"

# Get one board
pinterest boards get BOARD_ID
pinterest boards get BOARD_ID --table
```

### Pins

```bash
# List pins
pinterest pins list

# Table output
pinterest pins list --table

# Limit via API page_size
pinterest pins list --limit 10

# Client-side filtering
pinterest pins list --filter "board_owner.username:contains:brand"

# Select output fields
pinterest pins list --properties "id,title,board_id,created_at"

# Get one pin
pinterest pins get PIN_ID
pinterest pins get PIN_ID --table
```

### Authentication

```bash
# Run Pinterest OAuth authorization-code login
pinterest auth login

# Force a fresh OAuth login
pinterest auth login --force

# Check saved credentials and live API validation
pinterest auth status
pinterest auth status --table

# Run explicit auth verification checks
pinterest auth test
pinterest auth test --table --verbose

# Refresh the current OAuth access token
pinterest auth refresh

# Clear saved credentials
pinterest auth logout
```

### Authentication Profiles

```bash
# List saved auth profiles
pinterest auth profiles list

# Create a new profile from .env.example
pinterest auth profiles create sandbox

# Inspect one profile
pinterest auth profiles get sandbox

# Make a profile the default
pinterest auth profiles select sandbox

# Delete a profile
pinterest auth profiles delete sandbox --force
```

### Cache

```bash
# Remove cached responses for the active profile
pinterest cache clear
```

## Output Rules

- JSON is the default for every command.
- `--table` / `-t` renders human-readable table output.
- List commands support `--filter`, `--limit`, and `--properties`.
- Get commands support `--table`.

## Configuration

The CLI stores profile env files in the standard cli-tools profile location. Start from `.env.example` or let `pinterest auth login` populate credentials.

```dotenv
ACTIVE=true
CLIENT_ID=
CLIENT_SECRET=
REDIRECT_URI=http://localhost/
BASE_URL=https://api.pinterest.com/v5
ACCESS_TOKEN=
REFRESH_TOKEN=
TOKEN_EXPIRES_AT=
REFRESH_TOKEN_EXPIRES_AT=
```

For Pinterest Sandbox, set:

```dotenv
BASE_URL=https://api-sandbox.pinterest.com/v5
```

## Notes

- OAuth login uses Pinterest’s authorization-code flow against `https://www.pinterest.com/oauth/`.
- Token exchange uses HTTP Basic auth with `continuous_refresh=true`, matching Pinterest’s current auth guide.
- `boards list` translates `privacy:eq:...` to Pinterest’s documented `privacy` query parameter.
- `pins list` keeps `--filter` support by applying standard client-side filters after fetching paginated API results.

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | General error |
| `2` | Authentication or credential error |
| `130` | User interrupted |
