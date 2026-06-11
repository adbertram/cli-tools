# Globiflow CLI

## DESCRIPTION

The `globiflow` CLI provides a command-line interface for Globiflow (browser automation).

Use it when you need repeatable access to globiflow workflows that are only available through a signed-in website.

## Installation

```bash
cd globiflow
pip install -e .

# Install Playwright browsers (required once)
playwright install chromium
```

After installation, the `globiflow` command will be available in your terminal.

## Quick Start

```bash
# Login to Globiflow
globiflow auth login

# Check login status
globiflow auth status

# Search for items
globiflow search query "search terms"

# Get item details
globiflow search item ITEM_ID
```

## Commands

### Authentication (`globiflow auth`)

```bash
# Interactive login (opens browser)
globiflow auth login

# Check authentication status
globiflow auth status
globiflow auth status

# Clear stored session
globiflow auth logout
```

### Cache (`globiflow cache`)

```bash
# Show cache status
globiflow cache status

# Clear cached data
globiflow cache clear
```

### Search (`globiflow search`)

```bash
# Search for items (JSON output)
globiflow search query "search terms"

# Search with table format
globiflow search query "search terms"

# Limit results
globiflow search query "search terms" --limit 10

# Get item details
globiflow search item ITEM_ID
globiflow search item https://example.com/item/123

# List all items
globiflow search list
```

### Flows (`globiflow flows`)

```bash
# List all flows
globiflow flows list
globiflow flows list

# Filter flows (client-side)
globiflow flows list --filter "org_name:contains:My Org"
globiflow flows list --filter "enabled:eq:true"

# Limit and select properties
globiflow flows list --limit 10
globiflow flows list --properties "id,name,enabled"

# Get flow details
globiflow flows get FLOW_ID
globiflow flows get FLOW_ID
globiflow flows get FLOW_ID --include-steps

# View flow execution logs
globiflow flows logs FLOW_ID

# Create a new flow
globiflow flows create --app-id 30560419 --trigger C --name "My Flow"
globiflow flows create --app-id 30560419 --trigger U --name "Update Handler" --disabled
globiflow flows create --app-id 30560419 --trigger C --name "With Steps" --steps '[{"action_type": "Custom Variable", "variable_name": "test", "code": "1+1"}]'

# Delete a flow
globiflow flows delete FLOW_ID
globiflow flows delete FLOW_ID --force

# Manage flow steps
globiflow flows steps list FLOW_ID
globiflow flows steps get FLOW_ID STEP_NUMBER
globiflow flows steps add FLOW_ID --action "Add Comment" --comment "Hello world"
globiflow flows steps update FLOW_ID STEP_NUMBER --variable-name "new_name" --code "'expr'"
```

### Triggers (`globiflow triggers`)

```bash
# List all available trigger types
globiflow triggers list
globiflow triggers list

# Filter triggers (client-side)
globiflow triggers list --filter "code:eq:C"
globiflow triggers list --properties "code,name"

# Get trigger details by code
globiflow triggers get C
globiflow triggers get M
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--limit` | `-l` | Maximum number of results (default: 100, client-side) |
| `--filter` | `-f` | Filter results using field:op:value format (client-side) |
| `--properties` | `-p` | Comma-separated list of fields to include in output |
| `--force` | `-F` | Skip confirmation prompts |
| `--version` | `-v` | Show version and exit |

## Configuration

Configuration is stored in `.env` file:

```bash
# Base URL
BASE_URL=https://workflow-automation.podio.com

# Browser settings (true = invisible, false = visible browser)
HEADLESS=true
```

Browser session data is stored in the shared profile data directory for persistence between commands.

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
- **Headless mode**: Set `HEADLESS=false` to see the browser (useful for debugging)
- **Session persistence**: Login sessions are saved in the shared profile data directory and reused automatically
- **Rate limiting**: Be respectful of the site's terms of service

## Debugging

To debug browser automation issues:

```bash
# Run with visible browser
export HEADLESS=false
globiflow search query "test"
```

## Requirements

- Python 3.9+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - playwright

## License

MIT
