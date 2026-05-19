# Easyship CLI

A command-line interface for the [Easyship API](https://developers.easyship.com/reference). Easyship Public API CLI

## Installation

```bash
cd easyship
pip install -e .
```

After installation, the `easyship` command will be available in your terminal.

## Quick Start

```bash
# Authenticate with an Easyship API access token
easyship auth login

# List active couriers
easyship couriers list

# Get the current Easyship account payload
easyship account get
```

## Commands

### Authentication

```bash
# Save a personal access token
easyship auth login

# Check authentication status
easyship auth status

# Test the saved token against /account
easyship auth test

# Clear stored credentials
easyship auth logout
```

### Profiles

```bash
# List all profiles
easyship auth profiles list

# Show default profile
easyship auth profiles get default

# Switch default profile
easyship auth profiles set-default PROFILE_NAME

# Create a new profile
easyship auth profiles create PROFILE_NAME
```

### Account

```bash
# Get the authenticated account payload
easyship account get

# Show the account payload as a table
easyship account get --table
```

### Couriers

```bash
# List active couriers
easyship couriers list

# Limit results
easyship couriers list --limit 10

# Filter by umbrella name
easyship couriers list --filter "umbrella_name:eq:DHL"

# Get a specific courier
easyship couriers get COURIER_ID
```

### Cache

```bash
# Show cached responses
easyship cache list

# Clear all cached responses
easyship cache clear
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping

## AI Instruction Results

Commands that reach a non-deterministic boundary may return an AI instruction result instead of normal resource data. This is JSON on stdout with `type: "ai_instruction"` and tells the calling AI agent what objective to complete, what context is available, what tools are allowed, and what success means.

The CLI must not call an LLM or include required pre-action command lists. Optional `verification_commands` and `follow_up_commands` may appear only for actions to run after the agent completes the instruction.

### JSON Output Example

```bash
easyship couriers list --limit 2
```

### Table Output Example

```bash
easyship couriers list --limit 5 --table
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
# Personal access token
EASYSHIP_PERSONAL_ACCESS_TOKEN=your_api_access_token

# Optional: API base URL
EASYSHIP_BASE_URL=https://public-api.easyship.com/2024-09
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### List Couriers and Filter with jq

```bash
easyship couriers list | jq '.[].id'
```

### Export Couriers to JSON File

```bash
easyship couriers list --limit 200 > couriers.json
```

## Models

This CLI uses Pydantic models for type-safe data handling. All commands return strongly-typed models.

### Available Models

| Model | Description | Required Fields |
|-------|-------------|-----------------|
| `Courier` | Courier summary from `GET /couriers` | `id` |
| `CourierDetail` | Courier detail from `GET /couriers/{id}` | `id` |
| `Account` | Authenticated account payload from `GET /account` | none |

### Model Architecture

```
models/
├── __init__.py      # Exports all models
├── base.py          # CLIModel base class
└── item.py          # Courier and account models
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
