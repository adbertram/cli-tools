# Raptive CLI

## DESCRIPTION

The `raptive` CLI provides a command-line interface for Raptive (browser automation).

Use it when you need repeatable access to raptive workflows that are only available through a signed-in website.

## Installation

```bash
~/Dropbox/GitRepos/cli-tools/_repo/skills/cli-tool/scripts/install-cli-tool.sh raptive
```

Requires Google Chrome installed in `/Applications`.

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

Non-secret configuration lives in `~/.local/share/cli-tools/raptive/.env` (see `.env.example`):

```bash
BASE_URL=https://dashboard.raptive.com
API_BASE_URL=https://publisher-api.raptive.com
SITE_ID=<id from dashboard.raptive.com/sites/{SITE_ID}/dashboard>
HEADLESS=true
# Optional: override the User-Agent (defaults to the installed real Chrome's UA)
# BROWSER_USER_AGENT=
```

Sign in with `raptive auth login`; the browser session lives in the CLI's persistent Chrome profile. No credentials go in `.env`.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Architecture

The Raptive dashboard and its publisher API (`publisher-api.raptive.com`) sit behind
AWS WAF bot verification, and the dashboard signs in through Keycloak. A plain HTTP
client gets an empty `202` WAF challenge (or `403`) even with a valid Bearer token.

So every API call runs **inside the dashboard page** of the CLI's persistent real-Chrome
profile, exactly as the dashboard itself makes it:

1. Open `https://dashboard.raptive.com` headless with the installed real Chrome's
   User-Agent (the default `HeadlessChrome` UA fails the WAF check with "We couldn't
   verify your browser session").
2. Wait for the page's `AwsWafIntegration` (it passes the silent WAF challenge itself).
3. Call `AwsWafIntegration.fetch(url, {headers: {Authorization: 'Bearer ' + localStorage.token}})`,
   which attaches the `x-aws-waf-token` header.

The API caps `page[size]` at 500, so `earnings by-page` and `earnings brand-safety`
page through `page[number]` for larger `--limit` values.

`auth status` / `auth test` run a live, uncached `dateBounds` API call and report
`authenticated: false` whenever it fails, so a saved token alone never counts as signed in.

## Debugging

Set `HEADLESS=false` to watch the dashboard page while a command runs, and use
`--no-cache` to force a live API call.

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
