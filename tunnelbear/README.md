# TunnelBear CLI

A command-line interface for the official [TunnelBear](https://www.tunnelbear.com/affiliate/).

## Installation

```bash
cd tunnelbear
pip install -e .
playwright install chromium
```

## Quick Start

```bash
tunnelbear program info
tunnelbear auth status
tunnelbear cache clear
```

## Commands

### Program (`tunnelbear program`)

```bash
tunnelbear program info
tunnelbear program info --table
```

### Authentication (`tunnelbear auth`)

```bash
tunnelbear auth login
tunnelbear auth login --force
tunnelbear auth status
tunnelbear auth test
tunnelbear auth logout
tunnelbear auth profiles list
```

### Cache (`tunnelbear cache`)

```bash
tunnelbear cache clear
tunnelbear cache clear
```

## Notes

- This tool is intentionally minimal for the initial batch.
- It exposes verified program metadata for the official TunnelBear URL.
- It keeps browser-session auth scaffolding available for later authenticated browser work.

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

class AuctionItem(CLIModel):
    # Read-only: scraped from page, cannot be changed
    id: str = Field(frozen=True)

    # Regular writable field
    title: str

    # Read-only timestamps
    scraped_at: Optional[str] = Field(default=None, frozen=True)
```

### Model Validation

Models enforce required fields at runtime:

```python
# This will raise ValidationError - missing required 'title'
item = AuctionItem(id="123")

# This works - all required fields provided
item = AuctionItem(id="123", title="Vintage Item")
```

## Requirements

- Python 3.9+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - playwright
  - pydantic

## License

MIT
