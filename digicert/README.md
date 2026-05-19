# Digicert CLI

A command-line interface for the [Digicert API](https://dev.digicert.com/en/get-started/about-the-apis.html). CLI for DigiCert API workflows

## Installation

```bash
cd digicert
pip install -e .
```

After installation, the `digicert` command will be available in your terminal.

## Quick Start

```bash
# Authenticate with Digicert
digicert auth login

# List items
digicert items list

# Get a specific item
digicert items get ITEM_ID
```

## Commands

### Authentication

```bash
# Login with API key
digicert auth login
digicert auth login --api-key YOUR_API_KEY

# Check authentication status
digicert auth status
digicert auth status

# Clear stored credentials
digicert auth logout

# Run the scaffold auth test
digicert auth test
```

### Profiles

```bash
# List all profiles
digicert auth profiles list

# Show default profile
digicert auth profiles get default

# Switch default profile
digicert auth profiles set-default PROFILE_NAME

# Create a new profile
digicert auth profiles create PROFILE_NAME
```

### Cache

```bash
# Show cache status
digicert cache status

# Clear cached responses
digicert cache clear
```

### Items

```bash
# List all items (JSON output)
digicert items list

# List items with table format
digicert items list

# Limit results
digicert items list --limit 10

# Get a specific item
digicert items get ITEM_ID
digicert items get ITEM_ID
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping

## AI Instruction Results

Commands that reach a non-deterministic boundary may return an AI instruction result instead of normal resource data. This is JSON on stdout with `type: "ai_instruction"` and tells the calling AI agent what objective to complete, what context is available, what tools are allowed, and what success means.

The CLI must not call an LLM or include required pre-action command lists. Optional `verification_commands` and `follow_up_commands` may appear only for actions to run after the agent completes the instruction.

### JSON Output Example

```bash
digicert items list --limit 2
```

### Table Output Example

```bash
digicert items list --limit 5
```

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--limit` | `-l` | Maximum number of results (default: 50) |
| `--offset` | `-o` | Offset for pagination |
| `--version` | `-v` | Show version and exit |

## Configuration

Credentials are stored in a `.env` file in the package directory:

```bash
# API Key
DIGICERT_API_KEY=your_api_key

# Or OAuth credentials
DIGICERT_CLIENT_ID=your_client_id
DIGICERT_CLIENT_SECRET=your_client_secret

# OAuth tokens (managed automatically after login)
DIGICERT_ACCESS_TOKEN=<access_token>
DIGICERT_REFRESH_TOKEN=<refresh_token>
DIGICERT_TOKEN_EXPIRES_AT=<timestamp>

# Optional: API base URL
DIGICERT_BASE_URL=https://www.digicert.com/partners/value-added-reseller-affiliate/
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
digicert items list | jq '.items[].id'
```

### Export Items to JSON File

```bash
digicert items list --limit 200 > items.json
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

class MyStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"

class MyItem(CLIModel):
    # Required fields - no default value
    id: str
    name: str

    # Optional fields with defaults
    status: MyStatus = MyStatus.ACTIVE
    description: Optional[str] = None
```

2. Export from `models/__init__.py`
3. Use factory function in `client.py` to return models

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

class Item(CLIModel):
    # Read-only: server-assigned, cannot be changed after creation
    id: str = Field(frozen=True)

    # Regular writable field
    name: str

    # Read-only timestamps: server-assigned, immutable
    created_at: Optional[str] = Field(default=None, frozen=True)
    updated_at: Optional[str] = Field(default=None, frozen=True)

# Separate model for create payloads (no read-only fields)
class ItemCreate(CLIModel):
    name: str
    description: Optional[str] = None
```

### Model Validation

Models enforce required fields at runtime:

```python
# This will raise ValidationError - missing required 'name'
item = Item(id="123")

# This works - all required fields provided
item = Item(id="123", name="My Item")
```

## Requirements

- Python 3.9+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests
  - pydantic

## License

MIT
