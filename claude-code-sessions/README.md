# ClaudeCodeSessions CLI

## DESCRIPTION

The `claude-code-sessions` CLI wraps claude with standardized cli-tools behavior.

Use it when you need the underlying command exposed through cli-tools JSON/table conventions for agents, automation, or terminal workflows.

## Prerequisites

This CLI wraps the `claude` command-line tool. You must install it first:

```bash
# Install claude (customize for your tool)
# Example: brew install claude
```

## Installation

```bash
cd claude-code-sessions
pip install -e .
```

After installation, the `claude-code-sessions` command will be available in your terminal.

## Quick Start

```bash
# Check if underlying CLI is available
claude-code-sessions auth status

# Login (no-op for local files)
claude-code-sessions auth login

# List sessions for a project
claude-code-sessions sessions list --project ExampleProject
```

## How It Works

This CLI is a **wrapper** around the `claude` command-line tool:

- **Auth commands** delegate directly to `claude`'s authentication
- **Data commands** call `claude`, parse the output, and present it in standard JSON/table format
- **Configuration** is minimal - the underlying CLI handles credentials

## Commands

### Authentication

Authentication is handled by the underlying `claude` CLI.

```bash
# Login via claude
claude-code-sessions auth login

# Check status
claude-code-sessions auth status
claude-code-sessions auth status

# Logout
claude-code-sessions auth logout
```

### Projects

```bash
# List all projects
claude-code-sessions projects list
claude-code-sessions projects list
```

### Sessions

```bash
# List sessions for a project
claude-code-sessions sessions list --project ExampleProject
claude-code-sessions sessions list --project ExampleProject

# Get specific session
claude-code-sessions sessions get <session-id> --project ExampleProject
```

### Conversations

```bash
# List conversations for a project
claude-code-sessions conversations list --project ExampleProject
claude-code-sessions conversations list -p ExampleProject --session-id abc123
claude-code-sessions conversations list -p ExampleProject --since 1d --table

# Filter by message count
claude-code-sessions conversations list -p ExampleProject --filter "message_count:gt:10"

# Get a specific conversation
claude-code-sessions conversations get abc123:1 --project ExampleProject
```

### Subagent Activity

```bash
# List subagent activity for a project
claude-code-sessions subagent-activity list --project ExampleProject
claude-code-sessions subagent-activity list --project ExampleProject --since 1d

# Filter by agent type
claude-code-sessions subagent-activity list --project ExampleProject --filter "agent_type:eq:Explore"
```

### Tool Calls

```bash
# List tool calls for a project
claude-code-sessions tool-calls list --project ExampleProject
claude-code-sessions tool-calls list --project ExampleProject --since 1d

# Filter by tool name
claude-code-sessions tool-calls list --project ExampleProject --filter "tool:eq:Read"
```

### Todos

```bash
# List todos for a project
claude-code-sessions todos list --project ExampleProject
claude-code-sessions todos list --project ExampleProject --since 1d

# Filter by status
claude-code-sessions todos list --project ExampleProject --filter "status:eq:completed"

# Get specific todo
claude-code-sessions todos get <todo-id> --project ExampleProject
```

### Skills

```bash
# List skill/command invocations for a project
claude-code-sessions skills list --project ExampleProject
claude-code-sessions skills list --project ExampleProject --since 1h

# Filter by skill name
claude-code-sessions skills list --project ExampleProject --filter "name:eq:start-post-pipeline"

# Get specific skill invocation
claude-code-sessions skills get <skill-id> --project ExampleProject
```

### Timeline

```bash
# Consolidated timeline - show ALL activity for a session
claude-code-sessions timeline consolidated --session-id <session-id> --project ExampleProject
claude-code-sessions timeline consolidated -S <session-id> -p ExampleProject
claude-code-sessions timeline consolidated -S <session-id> -p ExampleProject --hide-agent-tools

# Get timeline for a specific session (positional session ID)
claude-code-sessions timeline get <session-id> --project ExampleProject

# List timeline across recent sessions
claude-code-sessions timeline list --project ExampleProject --since 1d
claude-code-sessions timeline list --project ExampleProject --limit 50
```

The `consolidated` command shows all activity in a single view:
- User prompts
- Skill invocations
- Main agent tool calls
- Subagent launches
- Subagent tool calls (can be hidden with `--hide-agent-tools`)

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping

## Configuration

The wrapper stores minimal configuration in `.env`:

```bash
# Underlying CLI command (defaults to claude)
CLAUDE_CODE_SESSIONS_CLI_COMMAND=claude

# Optional: Full path to CLI executable
# CLAUDE_CODE_SESSIONS_CLI_PATH=
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
claude-code-sessions items list | jq '.[].name'
```

### Export to JSON File

```bash
claude-code-sessions items list > items.json
```

## Models

This CLI uses Pydantic models for type-safe data handling. All commands return strongly-typed models.

### Available Models

| Model | Description | Required Fields |
|-------|-------------|-----------------|
| `Item` | Base item for list commands | `id`, `name` |
| `ItemDetail` | Extended item for get commands | `id`, `name` |

### Model Architecture

```
models/
├── __init__.py      # Exports all models
├── base.py          # CLIModel base class
└── item.py          # Item, ItemDetail models
```

### Creating Custom Models

1. Define your model in `models/`:

```python
from .base import CLIModel
from typing import Optional
from enum import Enum

class EntryType(str, Enum):
    LOGIN = "login"
    NOTE = "note"
    CARD = "card"

class VaultEntry(CLIModel):
    # Required fields - no default value
    id: str
    name: str

    # Optional fields with defaults
    entry_type: EntryType = EntryType.LOGIN
    url: Optional[str] = None
    username: Optional[str] = None
```

2. Export from `models/__init__.py`
3. Parse CLI output and return models from `client.py`

### Read-Only Fields

Pydantic supports read-only fields natively using `Field()` parameters:

| Pattern | Effect |
|---------|--------|
| `Field(frozen=True)` | Immutable after model creation (raises error on assignment) |
| `Field(exclude=True)` | Excluded from `model_dump()` output |
| `Field(init=False)` | Excluded from `__init__` (requires default value) |

```python
from pydantic import Field
from .base import CLIModel
from typing import Optional

class VaultEntry(CLIModel):
    # Read-only: assigned by underlying CLI, cannot be changed
    id: str = Field(frozen=True)

    # Regular writable field
    name: str

    # Read-only timestamps
    last_modified: Optional[str] = Field(default=None, frozen=True)
```

### Model Validation

Models enforce required fields at runtime:

```python
# This will raise ValidationError - missing required 'name'
entry = VaultEntry(id="123")

# This works - all required fields provided
entry = VaultEntry(id="123", name="My Login")
```

## Requirements

- Python 3.9+
- `claude` CLI installed and in PATH
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - pydantic

## License

MIT

## Additional Commands

### Search

```bash
claude-code-sessions search --help
```
