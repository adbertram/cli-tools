# Nextdoor CLI

## DESCRIPTION

A command-line interface for Nextdoor. CLI for Nextdoorcom.

Use this CLI when you need scriptable, JSON-first access to Nextdoor from agents, automation, or terminal workflows.

## Docs

- Base URL: https://nextdoor.com/api/gql


## Installation

```bash
cd <cli-tools-root>/nextdoor
uv tool install -e . --force --refresh
```

After installation, the `nextdoor` command will be available in your terminal.

## Quick Start

```bash
# Authenticate with Nextdoor
nextdoor auth login

# List feed items
nextdoor feed --limit 10

# Show table output
nextdoor feed --limit 10 --table

# Get current user profile
nextdoor me --table
```

## Commands

### Authentication (`nextdoor auth`)

```bash
# Interactive login
nextdoor auth login

# Force re-authentication
nextdoor auth login --force

# Check authentication status
nextdoor auth status

# Run the configured live auth test
nextdoor auth test

# Clear saved credentials/session
nextdoor auth logout
```

### Profiles (`nextdoor auth profiles`)

```bash
# List all profiles
nextdoor auth profiles list

# Show a profile
nextdoor auth profiles get default

# Select the active profile for its auth type
nextdoor auth profiles select PROFILE_NAME

# Create a profile
nextdoor auth profiles create PROFILE_NAME

# Delete a profile
nextdoor auth profiles delete PROFILE_NAME
```

### Feed

```bash
# View feed
nextdoor feed --limit 25

# View feed with table output
nextdoor feed --limit 25 --table

# Filter feed
nextdoor feed --filter "type:eq:post"

# Restrict output fields
nextdoor feed --properties "id,title"
```

### Notifications

```bash
# View notifications
nextdoor notifications --table
```

### Me

```bash
# View current user profile
nextdoor me --table
```

### Search

```bash
# Search Nextdoor suggestions
nextdoor search "widget" --limit 10 --table
```

## Output Formats

- JSON is the default output format.
- Add `--table` / `-t` for human-readable table output.

## AI Instruction Results

Commands that reach a non-deterministic boundary may return an AI instruction result instead of normal resource data. This is JSON on stdout with `type: "ai_instruction"` and tells the calling AI agent what objective to complete, what context is available, what tools are allowed, and what success means.

The CLI must not call an LLM or include required pre-action command lists. Optional `verification_commands` and `follow_up_commands` may appear only for actions to run after the agent completes the instruction.

### JSON Output Example

```bash
nextdoor feed --limit 2
```

```json
[
  {
    "id": "item-1",
    "title": "Example Post",
    "type": "post"
  }
]
```

### Table Output Example

```bash
nextdoor feed --limit 5 --table
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

Non-authentication configuration is stored in `~/.local/share/cli-tools/nextdoor/.env`. CLI-managed runtime auth state is stored in the active profile at `~/.local/share/cli-tools/nextdoor/authentication_profiles/<profile>/.env`. The source repo only carries `.env.example`.

Reusable CLI credentials that agents or scripts need to store/retrieve are governed by the user-level `cli-tool` skill's `references/secrets.md`.

Do not put reusable credentials in any `.env` file. Store and retrieve them through `<cli-tools-root>/_repo/_secret-manager/secrets.sh`. `.env` files are limited to non-secret config and CLI-managed runtime auth state.

Root config variables:

```bash
# Optional: override the default API base URL
BASE_URL=https://nextdoor.com/api/gql

# Optional: response cache settings
CACHE_ENABLED=true
CACHE_TTL=3600
```

Authentication profile variables (CLI-managed runtime auth state):

```bash
ACTIVE=true
ACCESS_TOKEN=<access_token_written_by_cli>
REFRESH_TOKEN=<refresh_token_written_by_cli>
TOKEN_EXPIRES_AT=2026-01-01T00:00:00Z
```

Reusable raw credentials belong in the CLI-tools secret manager, not in `.env` files. If this CLI persists secret-manager references into the active profile, they look like:

```bash
API_KEY=secret://nextdoor-api-key
PERSONAL_ACCESS_TOKEN=secret://nextdoor-personal-access-token
CLIENT_ID=secret://nextdoor-client-id
CLIENT_SECRET=secret://nextdoor-client-secret
USERNAME=secret://nextdoor-username
PASSWORD=secret://nextdoor-password
```


## Cache

```bash
# Clear cached read responses
nextdoor cache clear

# Bypass the cache for one execution
nextdoor --no-cache feed --limit 10
```


## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Client/config/authentication error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### List Feed and Filter with jq

```bash
nextdoor feed --properties "id,title" | jq '.[].id'
```

### Export Feed to JSON File

```bash
nextdoor feed --limit 200 > feed.json
```

## Output Contract

Commands return plain JSON records. The default feed record shape is:

| Field | Description |
|-------|-------------|
| `id` | Stable item identifier |
| `title` | Item title or preview |
| `type` | Type of feed item |

## Requirements

- Python 3.11+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests

## License

MIT
