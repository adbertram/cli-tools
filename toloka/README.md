# Toloka CLI

## DESCRIPTION

A browser-automation command-line interface for Toloka. Toloka gig worker portal automation.

Use this CLI when you need repeatable access to Toloka workflows that are only available through the website.

## Docs

- Website: https://www.toloka.site


## Installation

```bash
cd <cli-tools-root>/toloka
uv tool install -e . --force --refresh
```

Browser automation is driven by `browser-harness` (CDP), a transitive
dependency of `cli-tools-shared`. No separate "install browsers" step is
required — the harness manages its own browser binary.

After installation, the `toloka` command will be available in your terminal.

## Live Site Status (2026-09-02)

`https://www.toloka.site` was completely unreachable throughout this CLI's
development: every request, including `/login`, returned a Cloudflare Tunnel
error (1033 / HTTP 530), meaning Cloudflare could not reach the origin server
behind its tunnel at all. This was confirmed with repeated live checks (curl
and a real browser navigation) over several minutes with no recovery -- it is
a genuine site-side outage, not a bot-detection wall or credential problem.

Because of this outage:
- No real DOM was ever observed, so `browser.py`'s selectors are the
  scaffold's generic defaults, **not validated selectors**. See the
  `SELECTOR VALIDATION STATUS` docstring in `toloka_cli/browser.py` for the
  exact re-validation steps once the site recovers.
- `toloka_cli/client.py`'s `list_tasks` / `get_task` raise a clear
  `ClientError` explaining the outage instead of returning fabricated task
  data.
- `tasks apply --confirm` (the actual-submission path) is intentionally
  unimplemented for the same reason -- it raises a clear error rather than
  guess a submit flow that could not be validated.
- `tasks apply` **without** `--confirm` (the dry-run path) does not touch the
  network at all and works today; it was verified directly against
  `toloka_cli/client.py`.

Retry once `https://www.toloka.site/login` is reachable, then complete
`toloka auth login`, capture the real dashboard/task DOM, and fill in the
`TODO`s in `client.py` / `parsers.py` / `browser.py`.

## Quick Start

```bash
# Authenticate with Toloka (opens a browser for login)
toloka auth login

# Check authentication status
toloka auth status

# List open/available tasks for the logged-in worker
toloka tasks list --table

# Get full detail for a specific task
toloka tasks get TASK_ID --table

# Preview an application without submitting anything (default)
toloka tasks apply TASK_ID

# Actually submit the application (NOT YET IMPLEMENTED -- see status above)
toloka tasks apply TASK_ID --confirm
```

## Commands

### Authentication (`toloka auth`)

```bash
# Interactive login
toloka auth login

# Force re-authentication
toloka auth login --force

# Check authentication status
toloka auth status

# Run the configured live auth test
toloka auth test

# Clear saved credentials/session
toloka auth logout
```

### Profiles (`toloka auth profiles`)

```bash
# List all profiles
toloka auth profiles list

# Show a profile
toloka auth profiles get default

# Select the active profile for its auth type
toloka auth profiles select PROFILE_NAME

# Create a profile
toloka auth profiles create PROFILE_NAME

# Delete a profile
toloka auth profiles delete PROFILE_NAME
```



### Tasks (`toloka tasks`)

```bash
# List open/available tasks (JSON output)
toloka tasks list

# List with table format
toloka tasks list --table

# Limit results
toloka tasks list --limit 10

# Filter results
toloka tasks list --filter "status:eq:open"

# Restrict output fields
toloka tasks list --properties "id,title,payout"

# Get full detail for one task
toloka tasks get TASK_ID
toloka tasks get TASK_ID --table

# Preview an application (DRY RUN, default -- sends nothing to toloka.site)
toloka tasks apply TASK_ID

# Actually submit the application (requires --confirm; NOT YET IMPLEMENTED,
# see "Live Site Status" above)
toloka tasks apply TASK_ID --confirm --debug-dir /tmp/toloka-debug
```

`tasks apply` is dry-run by default: without `--confirm` it only reports what
it would submit and never opens a browser or sends a request. Only
`--confirm` attempts a real submission.

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

Non-authentication configuration is stored in `~/.local/share/cli-tools/toloka/.env`. CLI-managed runtime auth state is stored in the active profile at `~/.local/share/cli-tools/toloka/authentication_profiles/<profile>/.env`. The source repo only carries `.env.example`.

Reusable CLI credentials that agents or scripts need to store/retrieve are governed by the user-level `cli-tool` skill's `references/secrets.md`.

Do not put reusable credentials in any `.env` file. Store and retrieve them through `<cli-tools-root>/_repo/_secret-manager/secrets.sh`. `.env` files are limited to non-secret config and CLI-managed runtime auth state.

Root config variables:

```bash
# Optional: override the default site URL
BASE_URL=https://www.toloka.site

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
toloka cache clear

# Bypass the cache for one execution
toloka --no-cache tasks list --limit 10
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

## Browser Automation Notes

- **First run**: Run `toloka auth login` to launch the persistent browser session and complete login
- **Headless mode**: Set `HEADLESS=false` to watch the browser during debugging
- **Session persistence**: Login sessions are saved under the active profile's browser-data directory
- **Rate limiting**: Be respectful of the site's terms of service

## Debugging

To debug browser automation issues:

```bash
# Run with visible browser
export HEADLESS=false
toloka tasks list
```

## Output Contract

`tasks list` / `tasks get` return plain JSON records. The placeholder column
shape (used for `--table` headers until real DOM data is captured) is:

| Field | Description |
|-------|-------------|
| `id` | Stable task identifier from the page |
| `title` | Task title |
| `payout` | Task payout |
| `status` | Task status |

`tasks apply` (dry-run, no `--confirm`) returns:

| Field | Description |
|-------|-------------|
| `task_id` | The task ID passed on the command line |
| `confirm` | Always `false` for the dry-run branch |
| `would_submit` | Always `true` -- this is what would be submitted |
| `submitted` | Always `false` -- nothing was sent |
| `message` | Human-readable description of the pending action |

Capture real DOM data first, then update `normalize_tasks()` and
`normalize_task()` in `parsers.py` to map page data into the documented
command output, and implement the real submission flow in
`TolokaClient.apply_task`'s `confirm=True` branch. Add local models only when
validation, polymorphism, or serialization removes real complexity.

## Requirements

- Python 3.11+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - cli-tools-shared (transitively pulls in browser-harness)

## License

MIT
