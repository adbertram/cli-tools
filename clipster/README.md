# Clipster CLI

## DESCRIPTION

A command-line interface for Clipster. Read Clipster's public clipping campaign catalog.

Use this CLI when you need scriptable, JSON-first access to Clipster from agents, automation, or terminal workflows.

## Docs

- API documentation: https://www.clipster.gg/discover
- Base URL: https://api.clipster.gg


## Installation

```bash
<cli-tools-root>/_repo/skills/cli-tool/scripts/install-cli-tool.sh --force-refresh clipster
```

After installation, the `clipster` command will be available in your terminal.

## Quick Start

```bash
# List campaigns (default --limit 100)
clipster campaigns list

# Table output of the first 10
clipster campaigns list --limit 10 --table

# Get one campaign by id
clipster campaigns get 63d03ef9-d6b4-45b1-ada3-48f72bc2e948
```

Clipster's campaign catalog is public: no account, API key, or `auth` command is needed.

## Commands

### Campaigns

```bash
# List campaigns: every API field as returned, plus web_url
clipster campaigns list

# Read up to 250 campaigns (follows pages until the limit or the last page)
clipster campaigns list --limit 250

# Table output
clipster campaigns list --limit 25 --table

# Filter rows (applied to the rows read within --limit)
clipster campaigns list --filter "status:eq:CAMPAIGN_STATUS_ACTIVE"

# Restrict output fields
clipster campaigns list --properties "id,name,web_url"

# Get one campaign by id (found by reading the catalog; errors if the id is absent)
clipster campaigns get 63d03ef9-d6b4-45b1-ada3-48f72bc2e948

# Get one campaign as a field/value table
clipster campaigns get 63d03ef9-d6b4-45b1-ada3-48f72bc2e948 --table

# Get selected fields of one campaign
clipster campaigns get 63d03ef9-d6b4-45b1-ada3-48f72bc2e948 --properties "id,name,web_url"
```

`campaigns list` reads `https://api.clipster.gg/campaigns/public?page=N&limit=100`, sending an explicit `User-Agent` (the API answers Python's default one with HTTP 403) and `Accept: application/json`. It stops once `--limit` rows are collected or `metadata.pagination.total_pages` is reached. A response whose `data.campaigns` is not a list is an error. The catalog has no verified detail route, so `campaigns get` reads the whole catalog and returns the row with the matching id.

## Output Formats

- JSON is the default output format.
- Add `--table` / `-t` for human-readable table output.

## AI Instruction Results

Commands that reach a non-deterministic boundary may return an AI instruction result instead of normal resource data. This is JSON on stdout with `type: "ai_instruction"` and tells the calling AI agent what objective to complete, what context is available, what tools are allowed, and what success means.

The CLI must not call an LLM or include required pre-action command lists. Optional `verification_commands` and `follow_up_commands` may appear only for actions to run after the agent completes the instruction.

### JSON Output Example

```bash
clipster campaigns list --limit 1 --properties "id,name,status,web_url"
```

```json
[
  {
    "id": "63d03ef9-d6b4-45b1-ada3-48f72bc2e948",
    "name": "You cant please everyone (Slideshow)",
    "status": "CAMPAIGN_STATUS_ACTIVE",
    "web_url": "https://www.clipster.gg/discover?openedCampaignId=63d03ef9-d6b4-45b1-ada3-48f72bc2e948"
  }
]
```

### Table Output Example

```bash
clipster campaigns list --limit 5 --table
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

Non-authentication configuration is stored in `~/.local/share/cli-tools/clipster/.env`. CLI-managed runtime auth state is stored in the active profile at `~/.local/share/cli-tools/clipster/authentication_profiles/<profile>/.env`. The source repo only carries `.env.example`.

Reusable CLI credentials that agents or scripts need to store/retrieve are governed by the user-level `cli-tool` skill's `references/secrets.md`.

Do not put reusable credentials in any `.env` file. Store and retrieve them through `<cli-tools-root>/_repo/_secret-manager/secrets.sh`. `.env` files are limited to non-secret config and CLI-managed runtime auth state.

Root config variables:

```bash
# Optional: override the default API base URL
BASE_URL=https://api.clipster.gg

# Optional: response cache settings (catalog reads are cached 5 minutes regardless of CACHE_TTL)
CACHE_ENABLED=true
CACHE_TTL=3600
```


## Cache

```bash
# Clear cached read responses
clipster cache clear

# Bypass the cache for one execution
clipster --no-cache campaigns list --limit 10
```


## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Client/config/authentication error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### List Campaign IDs with jq

```bash
clipster campaigns list --limit 200 | jq -r '.[].id'
```

### Export the Catalog to a JSON File

```bash
clipster campaigns list --limit 200 > campaigns.json
```

## Output Contract

Both commands print JSON on stdout. Each campaign is the row exactly as the API returns it (all fields, nothing pruned) plus one added field:

| Field | Description |
|-------|-------------|
| `web_url` | `https://www.clipster.gg/discover?openedCampaignId=<id>` |

`campaigns list` prints an array of rows; `campaigns get` prints one row object (an array when `--properties` is given). Reads are cached for 5 minutes; pass `--no-cache` for a fresh read.

## Requirements

- Python 3.11+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests

## License

MIT
