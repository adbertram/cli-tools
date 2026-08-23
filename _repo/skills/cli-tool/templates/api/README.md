# {{Name}} CLI

## DESCRIPTION

A command-line interface for {{Name}}. {{description}}.

Use this CLI when you need scriptable, JSON-first access to {{Name}} from agents, automation, or terminal workflows.

{{DOCS_SECTION}}
## Installation

```bash
cd <cli-tools-root>/{{name}}
uv tool install -e . --force --refresh
```

After installation, the `{{name}}` command will be available in your terminal.

## Quick Start

```bash
{{AUTH_QUICK_START}}# List items
{{name}} items list --limit 10

# Show table output
{{name}} items list --limit 10 --table

# Get one item
{{name}} items get ITEM_ID --table
```

## Commands

{{AUTH_COMMANDS_SECTION}}{{AUTH_PROFILES_SECTION}}### Items

```bash
# List items
{{name}} items list --limit 25

# List items with table output
{{name}} items list --limit 25 --table

# Filter items
{{name}} items list --filter "status:eq:active"

# Restrict output fields
{{name}} items list --properties "id,name"

# Get a specific item
{{name}} items get ITEM_ID --table

# Search items
{{name}} items search "widget" --limit 10
```

## Output Formats

- JSON is the default output format.
- Add `--table` / `-t` for human-readable table output.

## AI Instruction Results

Commands that reach a non-deterministic boundary may return an AI instruction result instead of normal resource data. This is JSON on stdout with `type: "ai_instruction"` and tells the calling AI agent what objective to complete, what context is available, what tools are allowed, and what success means.

The CLI must not call an LLM or include required pre-action command lists. Optional `verification_commands` and `follow_up_commands` may appear only for actions to run after the agent completes the instruction.

### JSON Output Example

```bash
{{name}} items list --limit 2
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
{{name}} items list --limit 5 --table
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

Non-authentication configuration is stored in `~/.local/share/cli-tools/{{name}}/.env`. CLI-managed runtime auth state is stored in the active profile at `~/.local/share/cli-tools/{{name}}/authentication_profiles/<profile>/.env`. The source repo only carries `.env.example`.

Reusable CLI credentials that agents or scripts need to store/retrieve are governed by the user-level `cli-tool` skill's `references/secrets.md`.

Do not put reusable credentials in any `.env` file. Store and retrieve them through `<cli-tools-root>/_repo/_secret-manager/secrets.sh`. `.env` files are limited to non-secret config and CLI-managed runtime auth state.

Root config variables:

```bash
# Optional: override the default API base URL
BASE_URL={{base_url}}

# Optional: response cache settings
CACHE_ENABLED=true
CACHE_TTL=3600
```

{{AUTH_CONFIG_SECTION}}
{{CACHE_SECTION}}
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
{{name}} items list --properties "id,name" | jq '.[].id'
```

### Export Items to JSON File

```bash
{{name}} items list --limit 200 > items.json
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
