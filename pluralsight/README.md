# Pluralsight CLI

A command-line interface for the official [Pluralsight](https://www.pluralsight.com/affiliate).

## Installation

```bash
cd pluralsight
pip install -e .
playwright install chromium
```

## Quick Start

```bash
pluralsight program info
pluralsight auth status
pluralsight cache clear
```

## Commands

### Program (`pluralsight program`)

```bash
pluralsight program info
pluralsight program info --table
```

### Authentication (`pluralsight auth`)

```bash
pluralsight auth login
pluralsight auth login --force
pluralsight auth status
pluralsight auth test
pluralsight auth logout
pluralsight auth profiles list
```

### Cache (`pluralsight cache`)

```bash
pluralsight cache clear
pluralsight cache clear
```

## Notes

- This tool is intentionally minimal for the initial batch.
- It exposes verified program metadata for the official Pluralsight URL.
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
