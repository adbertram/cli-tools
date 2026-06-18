# {{Name}} CLI

## DESCRIPTION

A standardized command-line wrapper for {{cli_command}}. {{description}}.

Use this CLI when you need the wrapped command exposed through the cli-tools JSON/table conventions for agents, automation, or terminal workflows.

{{DOCS_SECTION}}
## Prerequisites

This CLI wraps the `{{cli_command}}` command-line tool. Install that tool first.

## Installation

```bash
cd <cli-tools-root>/{{name}}
uv tool install -e . --force --refresh
```

After installation, the `{{name}}` command will be available in your terminal.

## Quick Start

```bash
# Verify the wrapped CLI is available
{{name}} --help

# List items
{{name}} items list --limit 10

# Show table output
{{name}} items list --limit 10 --table
```

## How It Works

This CLI is a wrapper around `{{cli_command}}`:

- The wrapped CLI owns authentication unless you extend this scaffold intentionally.
- Wrapper commands should call `{{cli_command}}`, parse deterministic output, and present standard JSON/table output.
- Wrapper-local configuration stores only settings such as `CLI_COMMAND` / `CLI_PATH`.

## Commands

### Items

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

## Configuration

The wrapper stores non-authentication configuration in `~/.local/share/cli-tools/{{name}}/.env`. Do not put reusable credentials in any `.env` file. This scaffold does not generate auth commands; if the wrapped CLI needs credentials, configure them through the wrapped CLI itself or extend this wrapper intentionally.

Root config variables:

```bash
# Underlying CLI command (defaults to {{cli_command}})
CLI_COMMAND={{cli_command}}

# Optional: full path to the wrapped CLI executable
# CLI_PATH=
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Client/configuration error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### List Items and Filter with jq

```bash
{{name}} items list --properties "id,name" | jq '.[].name'
```

### Export to JSON File

```bash
{{name}} items list > items.json
```

## Output Contract

Commands return plain JSON records. The default item record shape is:

| Field | Description |
|-------|-------------|
| `id` | Stable item identifier from the underlying CLI |
| `name` | Item display name |
| `status` | Item status |

Update `list_items()`, `get_item()`, `search_items()`, and `parse_cli_output()` to match the wrapped CLI's real command shape and output format. Keep the parser deterministic; do not add auto-detection or fallback parsing paths. Add local models only when validation, polymorphism, or serialization removes real complexity.

## Requirements

- Python 3.11+
- `{{cli_command}}` installed and available in PATH
- Dependencies (installed automatically):
  - typer
  - python-dotenv

## License

MIT
