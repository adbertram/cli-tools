# {{Name}} CLI

A command-line interface for [{{Name}}]({{base_url}}) using browser automation. {{description}}

## Installation

```bash
cd {{name}}
pip install -e .
```

Browser automation is driven by `browser-harness` (CDP), a transitive
dependency of `cli-tools-shared`. No separate "install browsers" step is
required — the harness manages its own browser binary.

After installation, the `{{name}}` command will be available in your terminal.

## Quick Start

```bash
# Login to {{Name}}
{{name}} auth login

# Check login status
{{name}} auth status

# Search for items
{{name}} search query "search terms"

# Get item details
{{name}} search item ITEM_ID
```

## Commands

### Authentication (`{{name}} auth`)

```bash
# Interactive login (opens browser, auto-monitors for auth)
{{name}} auth login

# Force re-authentication (clears existing session)
{{name}} auth login --force

# Check authentication status
{{name}} auth status

# Test authentication against live browser
{{name}} auth test

# Clear stored session
{{name}} auth logout
```

### Multiple Profiles

Support for multiple authentication profiles (useful for different accounts):

```bash
# Login with named profile
{{name}} auth login --profile work

# Use named profile for status check
{{name}} auth status --profile work

# Set default profile via environment variable
export {{NAME}}_DEFAULT_PROFILE=work
{{name}} auth status  # Uses 'work' profile

# Logout specific profile
{{name}} auth logout --profile work

# Profiles stored as:
# - profile.json (default profile)
# - profile-work.json (named profile 'work')
# - profile-adam.json (named profile 'adam')
```

### Profiles (`{{name}} auth profiles`)

```bash
# List all profiles
{{name}} auth profiles list

# Show a profile
{{name}} auth profiles get default

# Switch default profile
{{name}} auth profiles set-default PROFILE_NAME

# Create a new profile
{{name}} auth profiles create PROFILE_NAME
```

### Search (`{{name}} search`)

```bash
# Search for items (JSON output)
{{name}} search query "search terms"

# Search with table format
{{name}} search query "search terms"

# Limit results
{{name}} search query "search terms" --limit 10

# Get item details
{{name}} search item ITEM_ID
{{name}} search item https://example.com/item/123

# List all items
{{name}} search list
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

Non-authentication configuration is stored in `~/.local/share/cli-tools/{{name}}/.env`. Authentication data is stored in the active profile at `~/.local/share/cli-tools/{{name}}/authentication_profiles/<profile>/.env`. The source repo only carries `.env.example`.

Reusable CLI credentials that agents or scripts need to store/retrieve are governed by the user-level `cli-tool` skill's `references/secrets.md`.

Root config variables:

```bash
# Base URL
{{NAME}}_BASE_URL={{base_url}}

# Browser settings (true = invisible, false = visible browser)
{{NAME}}_HEADLESS=true
```

Authentication profile variables:

```bash
# Login credentials (optional - for automated login if supported)
{{NAME}}_USERNAME=your_username
{{NAME}}_PASSWORD=your_password

# Authentication Configuration
{{NAME}}_AUTH_COOKIE_NAMES=session.*,auth,token,sid  # Regex patterns for auth cookies
{{NAME}}_AUTH_SELECTOR=                               # CSS selector indicating authenticated state
{{NAME}}_AUTH_URL_PATTERN=                            # URL pattern indicating login page
{{NAME}}_AUTH_TIMEOUT=60                              # Seconds to wait for login
{{NAME}}_AUTH_POLL_INTERVAL=2                         # Seconds between auth checks
{{NAME}}_DEFAULT_PROFILE=default                      # Default profile name
```

Browser session data is stored in the profile data directory for persistence between commands.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Architecture

This CLI uses `cli_tools_shared.auth.BrowserAutomation` with browser-harness-backed Chrome automation:

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

- **First run**: Run `{{name}} auth login` to launch the persistent browser session and complete login
- **Headless mode**: Set `{{NAME}}_HEADLESS=false` to see the browser (useful for debugging)
- **Session persistence**: Login sessions are saved in `.browser-data/` and reused automatically
- **Rate limiting**: Be respectful of the site's terms of service

## Debugging

To debug browser automation issues:

```bash
# Run with visible browser
export {{NAME}}_HEADLESS=false
{{name}} search query "test"
```

## Output Contract

Commands return plain JSON records. The default item record shape is:

| Field | Description |
|-------|-------------|
| `id` | Stable item identifier from the page |
| `name` | Item display name |
| `status` | Item status |

Capture real DOM data first, then update `normalize_items()` and `normalize_item_detail()` in `parsers.py` to map page data into the documented command output. Add local models only when validation, polymorphism, or serialization removes real complexity.

## Requirements

- Python 3.9+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - cli-tools-shared (transitively pulls in browser-harness)

## License

MIT
