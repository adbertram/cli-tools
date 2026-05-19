# MetaBox CLI

A command-line interface for [MetaBox](https://metabox.io/) using browser automation. Browser CLI for Meta Box product workflows

## Installation

```bash
cd meta-box
pip install -e .

# Install Playwright browsers (required once)
playwright install chromium
```

After installation, the `meta-box` command will be available in your terminal.

## Quick Start

```bash
# Login to MetaBox
meta-box auth login

# Check login status
meta-box auth status

# Search for items
meta-box search query "search terms"

# Get item details
meta-box search item ITEM_ID
```

## Commands

### Authentication (`meta-box auth`)

```bash
# Interactive login (opens browser, auto-monitors for auth)
meta-box auth login

# Force re-authentication (clears existing session)
meta-box auth login --force

# Check authentication status
meta-box auth status

# Test authentication against live browser
meta-box auth test

# Clear stored session
meta-box auth logout
```

### Multiple Profiles

Support for multiple authentication profiles (useful for different accounts):

```bash
# Login with named profile
meta-box auth login --profile work

# Use named profile for status check
meta-box auth status --profile work

# Set default profile via environment variable
export META_BOX_DEFAULT_PROFILE=work
meta-box auth status  # Uses 'work' profile

# Logout specific profile
meta-box auth logout --profile work

# Profiles stored as:
# - profile.json (default profile)
# - profile-work.json (named profile 'work')
# - profile-adam.json (named profile 'adam')
```

### Profiles (`meta-box auth profiles`)

```bash
# List all profiles
meta-box auth profiles list

# Show default profile
meta-box auth profiles get default

# Switch default profile
meta-box auth profiles set-default PROFILE_NAME

# Create a new profile
meta-box auth profiles create PROFILE_NAME
```

### Search (`meta-box search`)

```bash
# Search for items (JSON output)
meta-box search query "search terms"

# Search with table format
meta-box search query "search terms"

# Limit results
meta-box search query "search terms" --limit 10

# Get item details
meta-box search item ITEM_ID
meta-box search item https://example.com/item/123

# List all items
meta-box search list
```

### Cache (`meta-box cache`)

```bash
# Show cache status for the active profile
meta-box cache status

# Clear cached responses for the active profile
meta-box cache clear
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping

## AI Instruction Results

Commands that reach a non-deterministic boundary may return an AI instruction result instead of normal resource data. This is JSON on stdout with `type: "ai_instruction"` and tells the calling AI agent what objective to complete, what context is available, what tools are allowed, and what success means.

The CLI must not call an LLM or include required pre-action command lists. Optional `verification_commands` and `follow_up_commands` may appear only for actions to run after the agent completes the instruction.

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
META_BOX_USERNAME=your_username
META_BOX_PASSWORD=your_password

# Base URL
META_BOX_BASE_URL=https://metabox.io/

# Browser settings (true = invisible, false = visible browser)
META_BOX_HEADLESS=true

# Authentication Configuration
META_BOX_AUTH_COOKIE_NAMES=session.*,auth,token,sid  # Regex patterns for auth cookies
META_BOX_AUTH_SELECTOR=                               # CSS selector indicating authenticated state
META_BOX_AUTH_URL_PATTERN=                            # URL pattern indicating login page
META_BOX_AUTH_TIMEOUT=60                              # Seconds to wait for login
META_BOX_AUTH_POLL_INTERVAL=2                         # Seconds between auth checks
META_BOX_DEFAULT_PROFILE=default                      # Default profile name
```

Browser session data is stored in `.storage/` directory for persistence between commands.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Architecture

This CLI uses shared browser tooling from `cli-tools-shared`:

- **BrowserAutomation**: interactive login, saved Playwright auth state, and rendered DOM interaction
- **BrowserAuthenticatedHttpClient**: direct authenticated HTTP reads from saved browser cookies
- **BrowserAuthState**: validated loading of `auth-state.json` from the active profile
- **Relay/embedded JSON helpers**: parse page payloads locally before launching a browser

### Customizing for Your Site

1. **Update `browser.py`**: Set login/check URLs and auth hooks for your site
2. **Update `client.py`**: Use `_fetch_authenticated_text()` first for read-only commands
3. **Use `_get_page()` only when needed**: Reserve Chromium for rendered DOM interactions and writes
4. **Implement Methods**: Add domain-specific methods (search, list, etc.)
5. **Add Commands**: Create new command files in `commands/` directory

Example browser hook configuration in `browser.py`:

```python
class ExampleBrowser(BrowserAutomation):
    SESSION_NAME = "example"
    LOGIN_URL = "https://example.com/login"
    AUTH_CHECK_URL = "https://example.com/dashboard"
    AUTH_URL_PATTERN = r"/login"
    AUTH_SUCCESS_SELECTOR = ".user-menu"
```

## Browser Automation Notes

- **First run**: Run `playwright install chromium` after pip install
- **Headless mode**: Set `META_BOX_HEADLESS=false` to see the browser (useful for debugging)
- **Session persistence**: Login sessions are saved in `.browser-data/` and reused automatically
- **Rate limiting**: Be respectful of the site's terms of service

## Debugging

To debug browser automation issues:

```bash
# Run with visible browser
export META_BOX_HEADLESS=false
meta-box search query "test"
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
