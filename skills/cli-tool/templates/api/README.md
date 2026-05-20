# {{Name}} CLI

A command-line interface for the [{{Name}} API]({{docs_url}}). {{description}}

## Installation

```bash
cd {{name}}
pip install -e .
```

After installation, the `{{name}}` command will be available in your terminal.

## Quick Start

```bash
# Authenticate with {{Name}}
{{name}} auth login

# List items
{{name}} items list

# Get a specific item
{{name}} items get ITEM_ID
```

## Commands

### Authentication

```bash
# Login with API key
{{name}} auth login
{{name}} auth login --api-key YOUR_API_KEY

# Check authentication status
{{name}} auth status
{{name}} auth status

# Clear stored credentials
{{name}} auth logout
```

### Profiles (`{{name}} auth profiles`)

```bash
# List all profiles
{{name}} auth profiles list

# Show a profile
{{name}} auth profiles get default

# Switch default profile
{{name}} auth profiles set-default PROFILE_NAME

# Create a new profile
{{name}} auth profiles create PROFILE_NAME
```

### Items

```bash
# List all items (JSON output)
{{name}} items list

# List items with table format
{{name}} items list

# Limit results
{{name}} items list --limit 10

# Get a specific item
{{name}} items get ITEM_ID
{{name}} items get ITEM_ID
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping

## AI Instruction Results

Commands that reach a non-deterministic boundary may return an AI instruction result instead of normal resource data. This is JSON on stdout with `type: "ai_instruction"` and tells the calling AI agent what objective to complete, what context is available, what tools are allowed, and what success means.

The CLI must not call an LLM or include required pre-action command lists. Optional `verification_commands` and `follow_up_commands` may appear only for actions to run after the agent completes the instruction.

### JSON Output Example

```bash
{{name}} items list --limit 2
```

### Table Output Example

```bash
{{name}} items list --limit 5
```

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--limit` | `-l` | Maximum number of results (default: 50) |
| `--offset` | `-o` | Offset for pagination |
| `--version` | `-v` | Show version and exit |

## Configuration

Runtime configuration is stored in the active profile's `.env` file under `~/.local/share/cli-tools/{{name}}/.profiles/`. The source repo only carries `.env.example`.

Reusable CLI credentials that agents or scripts need to store/retrieve are governed by the user-level `cli-tool` skill's `references/secrets.md`.

Profile environment variables:

```bash
# API Key
{{NAME}}_API_KEY=your_api_key

# Or OAuth credentials
{{NAME}}_CLIENT_ID=your_client_id
{{NAME}}_CLIENT_SECRET=your_client_secret

# OAuth tokens (managed automatically after login)
{{NAME}}_ACCESS_TOKEN=<access_token>
{{NAME}}_REFRESH_TOKEN=<refresh_token>
{{NAME}}_TOKEN_EXPIRES_AT=<timestamp>

# Optional: API base URL
{{NAME}}_BASE_URL={{base_url}}
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### List Items and Filter with jq

```bash
{{name}} items list | jq '.items[].id'
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

Update `normalize_item()` and `normalize_item_detail()` in `client.py` to map the API response into the documented command output. Add local models only when validation, polymorphism, or serialization removes real complexity.

## Requirements

- Python 3.9+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests

## License

MIT
