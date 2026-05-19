# Thunderbit CLI

A command-line interface for the [Thunderbit API](https://thunderbit.com/docs). This initial surface covers the documented `distill` and `extract` endpoints.

## Installation

```bash
cd thunderbit
pip install -e .
```

After installation, the `thunderbit` command will be available in your terminal.

## Quick Start

```bash
# Authenticate with Thunderbit
thunderbit auth login

# Distill a page to Markdown
thunderbit distill run https://example.com/article

# Extract structured data with a JSON Schema
thunderbit extract run https://example.com/product --schema-file product-schema.json
```

## Commands

### Authentication

```bash
# Login with API key
thunderbit auth login
thunderbit auth login --api-key YOUR_API_KEY

# Check authentication status
thunderbit auth status
thunderbit auth status

# Clear stored credentials
thunderbit auth logout
```

### Profiles

```bash
# List all profiles
thunderbit auth profiles list

# Show default profile
thunderbit auth profiles get default

# Switch default profile
thunderbit auth profiles set-default PROFILE_NAME

# Create a new profile
thunderbit auth profiles create PROFILE_NAME
```

### Cache (`thunderbit cache`)

```bash
# Show cache status
thunderbit cache status

# Clear cached responses
thunderbit cache clear
```

### Distill

```bash
# Distill a page to Markdown-oriented output
thunderbit distill run https://example.com/article

# Distill and show a summary table
thunderbit distill run https://example.com/article --table
```

### Extract

```bash
# Extract structured JSON using a schema file
thunderbit extract run https://example.com/product --schema-file product-schema.json
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping

## AI Instruction Results

Commands that reach a non-deterministic boundary may return an AI instruction result instead of normal resource data. This is JSON on stdout with `type: "ai_instruction"` and tells the calling AI agent what objective to complete, what context is available, what tools are allowed, and what success means.

The CLI must not call an LLM or include required pre-action command lists. Optional `verification_commands` and `follow_up_commands` may appear only for actions to run after the agent completes the instruction.

### JSON Output Example

```bash
thunderbit distill run https://example.com/article
```

### Table Output Example

```bash
thunderbit extract run https://example.com/product --schema-file product-schema.json --table
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
THUNDERBIT_API_KEY=your_api_key

# Or OAuth credentials
THUNDERBIT_CLIENT_ID=your_client_id
THUNDERBIT_CLIENT_SECRET=your_client_secret

# OAuth tokens (managed automatically after login)
THUNDERBIT_ACCESS_TOKEN=<access_token>
THUNDERBIT_REFRESH_TOKEN=<refresh_token>
THUNDERBIT_TOKEN_EXPIRES_AT=<timestamp>

# Optional: API base URL
THUNDERBIT_BASE_URL=https://openapi.thunderbit.com/openapi/v1
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### Pipe Distill Results to jq

```bash
thunderbit distill run https://example.com/article | jq '.metadata'
```

### Export Extract Results to JSON File

```bash
thunderbit extract run https://example.com/product --schema-file product-schema.json > thunderbit-extract.json
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
