# Taskerdata CLI

## DESCRIPTION

A browser-automation command-line interface for Taskerdata. TaskerData gig worker portal automation.

Use this CLI when you need repeatable access to Taskerdata workflows that are only available through the website.

## Docs

- Website: https://worker.taskerdata.com


## Installation

```bash
cd <cli-tools-root>/taskerdata
uv tool install -e . --force --refresh
```

Browser automation is driven by `browser-harness` (CDP), a transitive
dependency of `cli-tools-shared`. No separate "install browsers" step is
required — the harness manages its own browser binary.

After installation, the `taskerdata` command will be available in your terminal.

## Quick Start

```bash
# Authenticate with TaskerData
taskerdata auth login

# List open/available tasks
taskerdata tasks list --limit 10 --table

# Get task details
taskerdata tasks get TASK_ID --table

# Preview applying for a task (dry-run, no submission)
taskerdata tasks apply TASK_ID

# Actually submit an application
taskerdata tasks apply TASK_ID --confirm
```

## Commands

### Authentication (`taskerdata auth`)

```bash
# Interactive login
taskerdata auth login

# Force re-authentication
taskerdata auth login --force

# Check authentication status
taskerdata auth status

# Run the configured live auth test
taskerdata auth test

# Clear saved credentials/session
taskerdata auth logout
```

### Profiles (`taskerdata auth profiles`)

```bash
# List all profiles
taskerdata auth profiles list

# Show a profile
taskerdata auth profiles get default

# Select the active profile for its auth type
taskerdata auth profiles select PROFILE_NAME

# Create a profile
taskerdata auth profiles create PROFILE_NAME

# Delete a profile
taskerdata auth profiles delete PROFILE_NAME
```



### Tasks (`taskerdata tasks`)

```bash
# List open/available tasks (JSON output)
taskerdata tasks list

# List with table format
taskerdata tasks list --table

# Limit results
taskerdata tasks list --limit 10

# Filter results
taskerdata tasks list --filter "category:eq:surveys"

# Restrict output fields
taskerdata tasks list --properties "id,title,payout"

# Get full detail for one task
taskerdata tasks get TASK_ID
taskerdata tasks get TASK_ID --table

# Apply for / pick up a task — DRY RUN BY DEFAULT.
# Without --confirm this only reports what would be submitted; it never
# submits or accepts anything on the live site.
taskerdata tasks apply TASK_ID

# Only --confirm actually submits the application
taskerdata tasks apply TASK_ID --confirm

# Save failure artifacts from a --confirm submission attempt
taskerdata tasks apply TASK_ID --confirm --debug-dir /tmp/taskerdata-debug
```

## Output Formats

- JSON is the default output format.
- Add `--table` / `-t` for human-readable table output.

## AI Instruction Results

Commands that reach a non-deterministic boundary may return an AI instruction result instead of normal resource data. This is JSON on stdout with `type: "ai_instruction"` and tells the calling AI agent what objective to complete, what context is available, what tools are allowed, and what success means.

The CLI must not call an LLM or include required pre-action command lists. Optional `verification_commands` and `follow_up_commands` may appear only for actions to run after the agent completes the instruction.

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display data as a table |
| `--limit` | `-l` | Maximum number of results |
| `--filter` | `-f` | Filter results using `field:op:value` syntax |
| `--properties` | `-p` | Restrict output to selected fields |
| `--version` | `-v` | Show version and exit |
| `--no-cache` |  | Bypass cached read responses for this execution |

## Configuration

Non-authentication configuration is stored in `~/.local/share/cli-tools/taskerdata/.env`. CLI-managed runtime auth state is stored in the active profile at `~/.local/share/cli-tools/taskerdata/authentication_profiles/<profile>/.env`. The source repo only carries `.env.example`.

Reusable CLI credentials that agents or scripts need to store/retrieve are governed by the user-level `cli-tool` skill's `references/secrets.md`.

Do not put reusable credentials in any `.env` file. Store and retrieve them through `<cli-tools-root>/_repo/_secret-manager/secrets.sh`. `.env` files are limited to non-secret config and CLI-managed runtime auth state.

Root config variables:

```bash
# Optional: override the default site URL
BASE_URL=https://worker.taskerdata.com

# Browser settings (true = invisible, false = visible browser)
HEADLESS=true

# Optional browser-harness runtime settings
# BROWSER_USER_AGENT=
# BROWSER_WINDOW_SIZE=1440,900

# Response cache settings
CACHE_ENABLED=true
CACHE_TTL=3600
```

Browser-auth selectors, login URLs, and other authenticated-page signals are defined in `browser.py` as `BrowserAutomation` class constants. Validate them against a real page snapshot before shipping.

## Cache

```bash
# Clear cached read responses
taskerdata cache clear

# Bypass the cache for one execution
taskerdata --no-cache tasks list --limit 10
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

1. Update `browser.py` with the real login/authenticated selectors and URLs.
2. Implement the placeholder methods in `client.py`.
3. Normalize extracted page data in `parsers.py` to the documented command output.

### Current Status

`browser.py`'s login automation (`LOGIN_URL`, `AUTH_URL_PATTERN`,
`AUTH_LOGIN_USERNAME_SELECTOR`/`AUTH_LOGIN_PASSWORD_SELECTOR`/
`AUTH_LOGIN_SUBMIT_SELECTOR`) is validated against the real DOM at
`https://blog.taskerdata.com/signin` (a Vuesax/Nuxt form) and does reach the
live `/api/login/signin` endpoint. The saved LastPass credentials for the
TaskerData worker account were rejected by that endpoint
(`wrong_credentials`), so no authenticated session has been reached yet.
`client.py`'s `list_tasks`/`get_task`/`apply_task(confirm=True)` and
`parsers.py`'s normalizers are intentionally left as `NotImplementedError`
stubs until a real authenticated task-board DOM snapshot can be captured —
per this skill's mandatory DOM-validation rule, no selector is guessed.
`apply_task(confirm=False)` (the dry-run path) does not depend on the
unimplemented DOM extraction beyond `get_task`.

## Browser Automation Notes

- **First run**: Run `taskerdata auth login` to launch the persistent browser session and complete login
- **Headless mode**: Set `HEADLESS=false` to watch the browser during debugging
- **Session persistence**: Login sessions are saved under the active profile's browser-data directory
- **Rate limiting**: Be respectful of the site's terms of service

## Debugging

To debug browser automation issues:

```bash
# Run with visible browser
export HEADLESS=false
taskerdata tasks list
```

## Output Contract

Commands return plain JSON records. The planned `tasks` record shape (pending
live DOM validation — see Current Status above) is:

| Field | Description |
|-------|-------------|
| `id` | Stable task identifier from the page |
| `title` | Task title |
| `category` | Task category (e.g. video promotion, image tagging) |
| `payout` | Payout for one approved submission |
| `status` | Task status |

`taskerdata tasks apply` returns:

| Field | Description |
|-------|-------------|
| `task_id` | The task ID passed on the command line |
| `confirm` | Whether `--confirm` was passed |
| `submitted` | Whether the application was actually submitted |
| `preview` | The task record (from `tasks get`) that would be/was applied to |

Capture real DOM data first, then implement `normalize_tasks()` and `normalize_task_detail()` in `parsers.py` to map page data into the documented command output. Add local models only when validation, polymorphism, or serialization removes real complexity.

## Requirements

- Python 3.11+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - cli-tools-shared (transitively pulls in browser-harness)

## License

MIT
