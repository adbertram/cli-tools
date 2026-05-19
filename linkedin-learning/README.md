# LinkedinLearning CLI

A command-line interface for the official [LinkedIn Learning](https://learning.linkedin.com/affiliate-program).

## Installation

```bash
cd linkedin-learning
pip install -e .
playwright install chromium
```

## Quick Start

```bash
linkedin-learning program info
linkedin-learning auth status
linkedin-learning cache clear
```

## Commands

### Program (`linkedin-learning program`)

```bash
linkedin-learning program info
linkedin-learning program info --table
```

### Authentication (`linkedin-learning auth`)

```bash
linkedin-learning auth login
linkedin-learning auth login --force
linkedin-learning auth status
linkedin-learning auth test
linkedin-learning auth logout
linkedin-learning auth profiles list
```

### Cache (`linkedin-learning cache`)

```bash
linkedin-learning cache clear
linkedin-learning cache clear
```

## Notes

- This tool is intentionally minimal for the initial batch.
- It exposes verified program metadata for the official LinkedIn Learning URL.
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
