# AdobePodcast CLI

## DESCRIPTION

A command-line interface for AdobePodcast. Adobe Podcast Enhance — upload audio/video, run AI speech enhancement, download result.

Use this CLI when you need scriptable, JSON-first access to AdobePodcast from agents, automation, or terminal workflows.

## Docs

- API documentation: https://podcast.adobe.com/en/enhance
- Base URL: https://phonos-server-flex.adobe.io


## Installation

```bash
cd <cli-tools-root>/adobe-podcast
uv tool install -e . --force --refresh
```

After installation, the `adobe-podcast` command will be available in your terminal.

## Quick Start

```bash
# Authenticate with AdobePodcast
adobe-podcast auth login

# List items
adobe-podcast items list --limit 10

# Show table output
adobe-podcast items list --limit 10 --table

# Get one item
adobe-podcast items get ITEM_ID --table
```

## Commands

### Authentication (`adobe-podcast auth`)

```bash
# Interactive login
adobe-podcast auth login

# Force re-authentication
adobe-podcast auth login --force

# Check authentication status
adobe-podcast auth status

# Run the configured live auth test
adobe-podcast auth test

# Clear saved credentials/session
adobe-podcast auth logout
```

### Profiles (`adobe-podcast auth profiles`)

```bash
# List all profiles
adobe-podcast auth profiles list

# Show a profile
adobe-podcast auth profiles get default

# Select the active profile for its auth type
adobe-podcast auth profiles select PROFILE_NAME

# Create a profile
adobe-podcast auth profiles create PROFILE_NAME

# Delete a profile
adobe-podcast auth profiles delete PROFILE_NAME
```

### Items

```bash
# List items
adobe-podcast items list --limit 25

# List items with table output
adobe-podcast items list --limit 25 --table

# Filter items
adobe-podcast items list --filter "status:eq:active"

# Restrict output fields
adobe-podcast items list --properties "id,name"

# Get a specific item
adobe-podcast items get ITEM_ID --table

# Search items
adobe-podcast items search "widget" --limit 10
```

## Output Formats

- JSON is the default output format.
- Add `--table` / `-t` for human-readable table output.

## AI Instruction Results

Commands that reach a non-deterministic boundary may return an AI instruction result instead of normal resource data. This is JSON on stdout with `type: "ai_instruction"` and tells the calling AI agent what objective to complete, what context is available, what tools are allowed, and what success means.

The CLI must not call an LLM or include required pre-action command lists. Optional `verification_commands` and `follow_up_commands` may appear only for actions to run after the agent completes the instruction.

### JSON Output Example

```bash
adobe-podcast items list --limit 2
```

```json
[
  {
    "id": "item-1",
    "name": "Example Item",
    "status": "active"
  }
]
```

### Table Output Example

```bash
adobe-podcast items list --limit 5 --table
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

Non-authentication configuration is stored in `~/.local/share/cli-tools/adobe-podcast/.env`. CLI-managed runtime auth state is stored in the active profile at `~/.local/share/cli-tools/adobe-podcast/authentication_profiles/<profile>/.env`. The source repo only carries `.env.example`.

Reusable CLI credentials that agents or scripts need to store/retrieve are governed by the user-level `cli-tool` skill's `references/secrets.md`.

Do not put reusable credentials in any `.env` file. Store and retrieve them through `<cli-tools-root>/_repo/_secret-manager/secrets.sh`. `.env` files are limited to non-secret config and CLI-managed runtime auth state.

Root config variables:

```bash
# Optional: override the default API base URL
BASE_URL=https://phonos-server-flex.adobe.io

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
API_KEY=secret://adobe-podcast-api-key
PERSONAL_ACCESS_TOKEN=secret://adobe-podcast-personal-access-token
CLIENT_ID=secret://adobe-podcast-client-id
CLIENT_SECRET=secret://adobe-podcast-client-secret
USERNAME=secret://adobe-podcast-username
PASSWORD=secret://adobe-podcast-password
```


## Cache

```bash
# Clear cached read responses
adobe-podcast cache clear

# Bypass the cache for one execution
adobe-podcast --no-cache items list --limit 10
```


## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Client/config/authentication error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### List Items and Filter with jq

```bash
adobe-podcast items list --properties "id,name" | jq '.[].id'
```

### Export Items to JSON File

```bash
adobe-podcast items list --limit 200 > items.json
```

## Output Contract

Commands return plain JSON records. The default item record shape is:

| Field | Description |
|-------|-------------|
| `id` | Stable item identifier |
| `name` | Item display name |
| `status` | Item status |

Update `normalize_item()` and `normalize_item_detail()` in `client.py` to map the API response into the documented command output. Replace the placeholder `list_items()`, `get_item()`, and `search_items()` methods with the service's real endpoints. Add local models only when validation, polymorphism, or serialization removes real complexity.

## Requirements

- Python 3.11+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests

## License

MIT
