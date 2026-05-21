# Raptive CLI

A command-line interface for [Raptive](https://dashboard.raptive.com) using browser automation. Interact with Raptive

## Installation

```bash
cd raptive
pip install -e .

# Install Playwright browsers (required once)
playwright install chromium
```

After installation, the `raptive` command will be available in your terminal.

## Quick Start

```bash
# Login to Raptive
raptive auth login

# Check login status
raptive auth status

# Get dashboard summary
raptive dashboard summary --period last30d

# View earnings overview
raptive earnings overview --period last7d

# View traffic sources
raptive traffic sources

# Enable shell completion (copy the completion script to your shell config)
raptive --install-completion
```

## Commands

### Authentication (`raptive auth`)

```bash
# Interactive login (opens browser)
raptive auth login

# Check authentication status
raptive auth status
raptive auth status

# Clear stored session
raptive auth logout

# Save credentials for automated login (if supported)
raptive auth set-credentials -u myusername -p mypassword
```

### Dashboard (`raptive dashboard`)

```bash
# Get dashboard summary for a period
raptive dashboard summary --period last30d
raptive dashboard summary --period last7d

# Get date bounds for available data
raptive dashboard dates
```

### Earnings (`raptive earnings`)

```bash
# Get daily earnings overview
raptive earnings overview --period last7d
raptive earnings overview --start 2025-12-01 --end 2025-12-31

# Get earnings by device type
raptive earnings by-device

# Get earnings by page
raptive earnings by-page --period last30d
raptive earnings by-page --limit 50

# Get earnings by traffic source
raptive earnings by-traffic-source --period last7d

# Get earnings by country
raptive earnings by-country --period last7d

# Get earnings by category
raptive earnings by-category --period last7d

# Get brand safety assessments
raptive earnings brand-safety
raptive earnings brand-safety --limit 50

# Get ad network earnings
raptive earnings sources
```

### Traffic (`raptive traffic`)

```bash
# Get traffic breakdown by source
raptive traffic sources

# Get traffic breakdown by device
raptive traffic by-device
```

### Cache (`raptive cache`)

```bash
# Clear cached API responses
raptive cache clear
```

### Profiles (`raptive auth profiles`)

```bash
# List all authentication profiles
raptive auth profiles list

# Create a new profile
raptive auth profiles create staging

# Set a profile as default
raptive auth profiles select staging

# Get profile details
raptive auth profiles get default

# Delete a profile
raptive auth profiles delete staging
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--limit` | `-l` | Maximum number of results (default: 50) |
| `--yes` | `-y` | Skip confirmation prompts |
| `--version` | `-v` | Show version and exit |

## Configuration

Configuration is stored in `.env` file:

```bash
# Login credentials (optional - for automated login if supported)
RAPTIVE_USERNAME=your_username
RAPTIVE_PASSWORD=your_password

# Base URL
RAPTIVE_BASE_URL=https://dashboard.raptive.com

# Browser settings (true = invisible, false = visible browser)
RAPTIVE_HEADLESS=true
```

Browser session data is stored in `.browser-data/` directory for persistence between commands.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Architecture

This CLI uses the **BrowserAutomationService** - a generic browser automation layer that provides:

- **Session Persistence**: Browser context persists between commands (cookies, localStorage)
- **Interactive Login**: Opens browser for manual login, saves session automatically
- **Form Automation**: Fill forms, click buttons, select dropdowns
- **Data Extraction**: Extract tables, lists, and custom data from pages
- **Pagination**: Handle "Load More" buttons and multi-page results
- **Retry Logic**: Automatic retries with exponential backoff

### Customizing for Your Site

1. **Update `client.py`**: Configure `BROWSER_CONFIG` with your site's URLs and selectors
2. **Implement Methods**: Add domain-specific methods (search, list, etc.)
3. **Add Commands**: Create new command files in `commands/` directory

Example site configuration in `client.py`:

```python
BROWSER_CONFIG = BrowserConfig(
    base_url="https://example.com",
    login_url="/login",
    login_check_url="/dashboard",
    login_indicators=["/login", "/signin"],
    logged_in_selector=".user-menu",
    username_selector="input[name='email']",
    password_selector="input[name='password']",
    submit_selector="button[type='submit']",
)
```

## Browser Automation Notes

- **First run**: Run `playwright install chromium` after pip install
- **Headless mode**: Set `RAPTIVE_HEADLESS=false` to see the browser (useful for debugging)
- **Session persistence**: Login sessions are saved in `.browser-data/` and reused automatically
- **Rate limiting**: Be respectful of the site's terms of service

## Debugging

To debug browser automation issues:

```bash
# Run with visible browser
export RAPTIVE_HEADLESS=false
raptive search query "test"
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

class AuctionStatus(str, Enum):
    ACTIVE = "active"
    ENDED = "ended"
    PENDING = "pending"

class AuctionItem(CLIModel):
    # Required fields - no default value
    id: str
    title: str

    # Optional fields with defaults
    status: AuctionStatus = AuctionStatus.ACTIVE
    current_bid: Optional[float] = None
    url: Optional[str] = None
```

2. Export from `models/__init__.py`
3. Return models from `client.py` scraping methods

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
