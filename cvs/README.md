# Cvs CLI

A command-line interface for the [Cvs API](https://www.cvs.com). CLI interface for CVS Health -- prescriptions, orders, and refills

## Installation

```bash
cd cvs
pip install -e .
```

After installation, the `cvs` command will be available in your terminal.

## Quick Start

```bash
# Authenticate with Cvs
cvs auth login

# List items
cvs items list

# Get a specific item
cvs items get ITEM_ID
```

## Commands

### Authentication

```bash
# Login with API key
cvs auth login
cvs auth login --api-key YOUR_API_KEY

# Check authentication status
cvs auth status
cvs auth status

# Clear stored credentials
cvs auth logout
```

### Items

```bash
# List all items (JSON output)
cvs items list

# List items with table format
cvs items list

# Limit results
cvs items list --limit 10

# Get a specific item
cvs items get ITEM_ID
cvs items get ITEM_ID
```

### Cache

```bash
# Clear cached data
cvs cache clear

# Show cache status
cvs cache status
```

### Profiles

```bash
# List all profiles
cvs auth profiles list

# Select active profile
cvs auth profiles select PROFILE_NAME

# Create a new profile
cvs auth profiles create PROFILE_NAME

# Delete a profile
cvs auth profiles delete PROFILE_NAME
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping

### JSON Output Example

```bash
cvs items list --limit 2
```

### Table Output Example

```bash
cvs items list --limit 5
```

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--limit` | `-l` | Maximum number of results (default: 50) |
| `--offset` | `-o` | Offset for pagination |
| `--version` | `-v` | Show version and exit |

## Configuration

Authentication profile files live under `~/.local/share/cli-tools/cvs/authentication_profiles/<profile>/`; non-auth defaults live in `~/.local/share/cli-tools/cvs/.env`:

```bash
# API Key
CVS_API_KEY=your_api_key

# Or OAuth credentials
CVS_CLIENT_ID=your_client_id
CVS_CLIENT_SECRET=your_client_secret

# OAuth tokens (managed automatically after login)
CVS_ACCESS_TOKEN=<access_token>
CVS_REFRESH_TOKEN=<refresh_token>
CVS_TOKEN_EXPIRES_AT=<timestamp>

# Optional: API base URL
CVS_BASE_URL=https://www.cvs.com
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
cvs items list | jq '.items[].id'
```

### Export Items to JSON File

```bash
cvs items list --limit 200 > items.json
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
