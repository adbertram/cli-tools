# AppyPie CLI

A command-line interface for the official [Appy Pie](https://www.appypie.com/).

## Installation

```bash
cd appy-pie
pip install -e .
playwright install chromium
```

## Quick Start

```bash
appy-pie program info
appy-pie auth status
appy-pie cache clear
```

## Commands

### Program (`appy-pie program`)

```bash
appy-pie program info
appy-pie program info --table
```

### Authentication (`appy-pie auth`)

```bash
appy-pie auth login
appy-pie auth login --force
appy-pie auth status
appy-pie auth test
appy-pie auth logout
appy-pie auth profiles list
```

### Cache (`appy-pie cache`)

```bash
appy-pie cache clear
appy-pie cache clear
```

## Notes

- This tool is intentionally minimal for the initial batch.
- It exposes verified program metadata for the official Appy Pie URL.
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
