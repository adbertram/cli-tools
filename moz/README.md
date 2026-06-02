# Moz CLI

A command-line interface for the [Moz API](https://api.moz.com/api/json/). Interact with Moz

## Installation

```bash
cd moz
pip install -e .
```

After installation, the `moz` command will be available in your terminal.

## Quick Start

```bash
# Authenticate with Moz
moz auth login

# Get keyword metrics
moz keywords get "machine learning"

# Get metrics for multiple keywords
moz keywords list "seo" "python" "ai"

# Get keyword suggestions
moz keywords suggestions "seo" --limit 10
```

## Commands

### Authentication

```bash
# Login with API key
moz auth login
moz auth login --api-key YOUR_API_KEY

# Check authentication status
moz auth status
moz auth status

# Clear stored credentials
moz auth logout
```

### Keywords

```bash
# Get metrics for a single keyword
moz keywords get "machine learning"
moz keywords get "python tutorial"

# Get metrics for multiple keywords
moz keywords list "seo" "python" "ai"
moz keywords list "seo" "python"
moz keywords list "seo" "python" --limit 5
moz keywords list "seo" "python" --filter "volume:gt:1000"
moz keywords list "seo" "python" --properties "keyword,volume,difficulty"

# Get keyword suggestions
moz keywords suggestions "seo"
moz keywords suggestions "python" --limit 20

# Get search intent for a keyword
moz keywords intent "how to learn python"
moz keywords intent "buy laptop"

# Get keywords a URL ranks for
moz keywords ranking "https://example.com/blog/python"
moz keywords ranking "https://example.com" --limit 20
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping

### JSON Output Example

```bash
moz items list --limit 2
```

### Table Output Example

```bash
moz items list --limit 5
```

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--limit` | `-l` | Maximum number of results (default: 50) |
| `--offset` | `-o` | Offset for pagination |
| `--version` | `-v` | Show version and exit |

## Configuration

Authentication profile files live under `~/.local/share/cli-tools/moz/authentication_profiles/<profile>/`; non-auth defaults live in `~/.local/share/cli-tools/moz/.env`:

```bash
# API Key
MOZ_API_KEY=your_api_key

# Or OAuth credentials
MOZ_CLIENT_ID=your_client_id
MOZ_CLIENT_SECRET=your_client_secret

# OAuth tokens (managed automatically after login)
MOZ_ACCESS_TOKEN=<access_token>
MOZ_REFRESH_TOKEN=<refresh_token>
MOZ_TOKEN_EXPIRES_AT=<timestamp>

# Optional: API base URL
MOZ_BASE_URL=https://api.moz.com/api/json/
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
moz items list | jq '.items[].id'
```

### Export Items to JSON File

```bash
moz items list --limit 200 > items.json
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

## Additional Commands

### Cache

```bash
moz cache --help
```
