# Microsoft365 CLI

A command-line interface for the official [Microsoft 365](https://www.microsoft.com/en-us/microsoft-365/business/microsoft-365-affiliate-program?ms.officeurl=affiliate).

## Installation

```bash
cd microsoft-365
pip install -e .
playwright install chromium
```

## Quick Start

```bash
microsoft-365 program info
microsoft-365 auth status
microsoft-365 cache clear
```

## Commands

### Program (`microsoft-365 program`)

```bash
microsoft-365 program info
microsoft-365 program info --table
```

### Authentication (`microsoft-365 auth`)

```bash
microsoft-365 auth login
microsoft-365 auth login --force
microsoft-365 auth status
microsoft-365 auth test
microsoft-365 auth logout
microsoft-365 auth profiles list
```

### Cache (`microsoft-365 cache`)

```bash
microsoft-365 cache clear
microsoft-365 cache clear
```

## Notes

- This tool is intentionally minimal for the initial batch.
- It exposes verified program metadata for the official Microsoft 365 URL.
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
