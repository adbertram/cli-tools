# Nextdoor CLI

## DESCRIPTION

A command-line interface for Nextdoor's GraphQL API, authenticated with a saved
browser session.

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
    "id": 489235186,
    "type": "POST",
    "title": "🐱 Kittens Looking for Loving Homes 🐱"
  },
  {
    "id": 6658602269397747960,
    "type": "PROMO",
    "title": "Homeaglow"
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

### Authentication (browser session)

This is a browser-session CLI. `nextdoor auth login` opens a persistent
Chromium profile; the logged-in Nextdoor session lives entirely in that profile
under
`~/.local/share/cli-tools/nextdoor/authentication_profiles/<profile>/browser-data/chromium-profile/`.
There are no API keys, passwords, or tokens to store. Data commands read the
live session cookies from that profile and replay them as GraphQL POST
requests.

Authentication is verified by a real server check, not by cookie presence:
Nextdoor sets a `ndp_session_id` cookie even for logged-out visitors, so
`auth status` loads an auth-required page and treats a redirect to `/login/` as
not authenticated, and `auth test` makes a live `getMe` call. If the session is
stale, data commands fail loudly with `session is not authenticated ... run
'nextdoor auth login --force'` (exit code 2 on `auth test`).

The profile `.env` carries only `ACTIVE=true` — no reusable credentials. Do not
put credentials in any `.env` file.


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

Commands return plain JSON records (a JSON array for list commands, a JSON
object for `me`). Each list command has a stable normalized record shape and a
matching default table column order; both are defined together in
`nextdoor_cli/client.py` so they cannot drift.

`feed` — personalized feed items (GraphQL `PersonalizedFeed`). Items are
heterogeneous (POST, PROMO ads, ...):

| Field | Description |
|-------|-------------|
| `id` | Item `contentId` |
| `type` | `feedItemType` (e.g. `POST`, `PROMO`) |
| `title` | POST → `post.subject`; PROMO → sponsor name; other types → `null` |

`search` — search-bar suggestions (GraphQL `getDynamicSearchBarSuggestions`).
The API returns a list of plain strings, each wrapped as a record:

| Field | Description |
|-------|-------------|
| `suggestion` | Suggestion text |

`notifications` — dashboard badge/shortcut entries (GraphQL `dashboardBadges`):

| Field | Description |
|-------|-------------|
| `id` | Shortcut `type` slug (e.g. `saved_bookmarks`, `events`) |
| `label` | Display title (e.g. `Bookmarks`) |
| `badges` | Unread badge value (`null` when none) |

`me` — the raw authenticated user object (GraphQL `getMe`, `data.me.user`),
returned as a JSON object. Top-level fields include `id`, `legacyUserId`,
`secureUserId`, `name` (`{displayName, ...}`), `avatar`, `hasUnverifiedFeed`,
`feedOrderingModePreferences`, and various NUX-state arrays. `--table` renders
it as a field/value table, summarizing nested objects/lists for readability
(use default JSON output for the full structure).

When a request hits a logged-out session, the affected command fails loudly
(exit code 1, error on stderr; `auth test` exits 2) rather than returning empty
or wrong data.

## Requirements

- Python 3.11+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests

## License

MIT
