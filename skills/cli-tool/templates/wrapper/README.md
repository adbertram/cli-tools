# {{Name}} CLI

A standardized command-line wrapper for [{{cli_command}}]({{docs_url}}). {{description}}

## Prerequisites

This CLI wraps the `{{cli_command}}` command-line tool. You must install it first:

```bash
# Install {{cli_command}} (customize for your tool)
# Example: brew install {{cli_command}}
```

## Installation

```bash
cd {{name}}
pip install -e .
```

After installation, the `{{name}}` command will be available in your terminal.

## Quick Start

```bash
# Check if underlying CLI is available
{{name}} auth status

# Login (delegates to {{cli_command}})
{{name}} auth login

# List items
{{name}} items list
```

## How It Works

This CLI is a **wrapper** around the `{{cli_command}}` command-line tool:

- **Auth commands** delegate directly to `{{cli_command}}`'s authentication
- **Data commands** call `{{cli_command}}`, parse the output, and present it in standard JSON/table format
- **Configuration** is minimal - the underlying CLI handles credentials

## Commands

### Authentication

Authentication is handled by the underlying `{{cli_command}}` CLI.

```bash
# Login via {{cli_command}}
{{name}} auth login

# Check status
{{name}} auth status
{{name}} auth status

# Logout
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
# List items
{{name}} items list
{{name}} items list

# Get specific item
{{name}} items get <item-id>
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping

## AI Instruction Results

Commands that reach a non-deterministic boundary may return an AI instruction result instead of normal resource data. This is JSON on stdout with `type: "ai_instruction"` and tells the calling AI agent what objective to complete, what context is available, what tools are allowed, and what success means.

The CLI must not call an LLM or include required pre-action command lists. Optional `verification_commands` and `follow_up_commands` may appear only for actions to run after the agent completes the instruction.

## Configuration

The wrapper stores minimal runtime configuration in the active profile's `.env` file. Reusable CLI credentials that agents or scripts need to store/retrieve are governed by the user-level `cli-tool` skill's `references/secrets.md`.

Profile environment variables:

```bash
IS_DEFAULT_PROFILE=1

# Underlying CLI command (defaults to {{cli_command}})
CLI_COMMAND={{cli_command}}

# Optional: Full path to CLI executable
# CLI_PATH=
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/CLI not available error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### List Items and Filter with jq

```bash
{{name}} items list | jq '.[].name'
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

Update `parse_cli_output()`, `normalize_item()`, and `normalize_item_detail()` to map the underlying CLI output into the documented command output. Add local models only when validation, polymorphism, or serialization removes real complexity.

## Requirements

- Python 3.9+
- `{{cli_command}}` CLI installed and in PATH
- Dependencies (installed automatically):
  - typer
  - python-dotenv

## License

MIT
