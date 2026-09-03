# HumanRail CLI

## DESCRIPTION

A browser-automation command-line interface for HumanRail (routehuman.com), a worker gig-task site ("Worker Console"), that authenticates as a worker and lists the tasks currently available in the worker's queue. Use this CLI to check HumanRail's task queue from the command line or from an automation (such as a MicroWorker discovery run) instead of opening the site in a browser by hand.

## Docs

- Website: https://routehuman.com

## Installation

```bash
cd <cli-tools-root>/humanrail
uv tool install -e . --force --refresh
```

Browser automation is driven by `browser-harness` (CDP), a transitive
dependency of `cli-tools-shared`. No separate "install browsers" step is
required — the harness manages its own browser binary.

After installation, the `humanrail` command will be available in your terminal.

## Quick Start

```bash
# Authenticate with HumanRail
humanrail auth login

# List currently available worker tasks
humanrail tasks list --table

# Get full detail for one task
humanrail tasks get TASK_ID --table
```

## Commands

### Authentication (`humanrail auth`)

```bash
# Interactive login
humanrail auth login

# Force re-authentication
humanrail auth login --force

# Check authentication status
humanrail auth status

# Run the configured live auth test
humanrail auth test

# Clear saved credentials/session
humanrail auth logout
```

### Profiles (`humanrail auth profiles`)

```bash
# List all profiles
humanrail auth profiles list

# Show a profile
humanrail auth profiles get default

# Select the active profile for its auth type
humanrail auth profiles select PROFILE_NAME

# Create a profile
humanrail auth profiles create PROFILE_NAME

# Delete a profile
humanrail auth profiles delete PROFILE_NAME
```

### Tasks (`humanrail tasks`)

```bash
# List available worker tasks (JSON output)
humanrail tasks list

# List with table format
humanrail tasks list --table

# Limit results
humanrail tasks list --limit 10

# Filter results
humanrail tasks list --filter "risk_tier:eq:low"

# Restrict output fields
humanrail tasks list --properties "id,payout_sats"

# Get full detail for one task
humanrail tasks get TASK_ID --table
```

Each task record returned by `tasks list` / `tasks get` has these fields
(validated against HumanRail's live frontend bundle 2026-09-02 — a field
HumanRail's API does not return for a given task is `null`, never invented):

| Field | Present in | Description |
|-------|------------|-------------|
| `id` | list, get | Task UUID |
| `url` | list, get | Constructed worker-console URL for the task |
| `type` | list, get | Task type (e.g. `contract_review`) |
| `status` | get | Task status (e.g. `in_progress`, `submitted`, `verified`) |
| `payout_sats` | list, get | Payout in satoshis |
| `risk_tier` | list, get | Risk tier badge shown to the worker |
| `skills_required` | list, get | Skill names required to claim the task |
| `estimated_minutes` | list, get | Estimated time to complete |
| `sla_deadline` | list, get | SLA deadline timestamp |
| `sla_seconds` | list, get | SLA duration in seconds |
| `description` | get | Task description/instructions |
| `payload` | get | Task-type-specific payload/context |
| `verification_feedback` | get | Feedback from a completed verification, if any |
| `verification_earned_sats` | get | Sats earned once verified, if any |

`tasks list` returns whatever HumanRail's own queue currently has open — an
empty list is a legitimate result when the site has no open tasks right now,
not a CLI failure.

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

Non-authentication configuration is stored in `~/.local/share/cli-tools/humanrail/.env`. CLI-managed runtime auth state is stored in the active profile at `~/.local/share/cli-tools/humanrail/authentication_profiles/<profile>/.env`. The source repo only carries `.env.example`.

Reusable CLI credentials that agents or scripts need to store/retrieve are governed by the user-level `cli-tool` skill's `references/secrets.md`. The HumanRail login username/password used for non-interactive `auth login` are stored as `humanrail-username` and `humanrail-password` in the CLI-tools secret manager (sourced from the LastPass "HumanRail" item).

Do not put reusable credentials in any `.env` file. Store and retrieve them through `<cli-tools-root>/_repo/_secret-manager/secrets.sh`. `.env` files are limited to non-secret config and CLI-managed runtime auth state.

Root config variables:

```bash
# Optional: override the default site URL
BASE_URL=https://routehuman.com

# Browser settings (true = invisible, false = visible browser)
HEADLESS=true

# Optional browser-harness runtime settings
# BROWSER_USER_AGENT=
# BROWSER_WINDOW_SIZE=1440,900

# Response cache settings
CACHE_ENABLED=true
CACHE_TTL=3600
```

Browser-auth selectors, login URLs, and other authenticated-page signals are defined in `browser.py` as `BrowserAutomation` class constants, validated against the live site.

## Cache

```bash
# Clear cached read responses
humanrail cache clear

# Bypass the cache for one execution
humanrail --no-cache tasks list --limit 10
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

This CLI uses `cli_tools_shared.auth.BrowserAutomation` with browser-harness-backed Chrome automation. HumanRail is a React SPA whose worker UI is entirely JSON-API-backed (`/api/workers/me/tasks/available`, `/api/workers/me/tasks/<id>`) and authorizes each call with a bearer token the frontend keeps in `localStorage` (`ee_auth_token`) rather than a session cookie. `client.py` calls that same JSON API from inside the authenticated browser page (reproducing the site's own `fetch(..., {headers: {Authorization: 'Bearer <token>'}})` call) instead of scraping rendered HTML, since the site itself never server-renders task data.

- **Session Persistence**: Browser context (including `localStorage`, where the bearer token lives) persists between commands.
- **Non-interactive login**: `auth login` fills the live email/password form and submits it using credentials from the CLI-tools secret manager — no manual browser interaction required.
- **Auth check**: `is_authenticated()` uses the `ee_auth_token` `localStorage` key as the primary signal (see `browser.py`), which is robust to the account's known-buggy `/onboarding` route.

## Known site issue (not a CLI defect)

The account's `/onboarding` route throws a minified React error (`Error #300`) and renders blank on this HumanRail deployment. This does not affect login, the auth token, or any other route (`/dashboard`, `/queue`, `/api/*` all work normally), so `browser.py` deliberately avoids `/onboarding` for its `AUTH_CHECK_URL`.

## Debugging

To debug browser automation issues:

```bash
# Run with visible browser
export HEADLESS=false
humanrail tasks list
```

## Requirements

- Python 3.11+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - cli-tools-shared (transitively pulls in browser-harness)

## License

MIT
