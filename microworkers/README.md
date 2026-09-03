# Microworkers CLI

## DESCRIPTION

A browser-automation command-line interface for Microworkers (worker side). Use it to list available worker jobs, inspect a job's full requirements, and, with explicit confirmation, submit proof for a job through an authenticated persistent browser session.

## Scope

This CLI is worker-side only. Microworkers also runs a separate campaign-creation tool on `ttv.microworkers.com` for employers, which is out of scope here. Some worker jobs listed by `tasks list` are TTV-branded campaigns whose task-execution page also lives on `ttv.microworkers.com` (reported with `"provider": "ttv"`). `tasks get` still succeeds for these (returning a `note` field explaining the boundary instead of parsed detail), but `tasks apply` refuses them with a clear error, since submitting proof for them requires that separate, out-of-scope system.

## Docs

- Website: https://www.microworkers.com

## Installation

```bash
cd <cli-tools-root>/microworkers
uv tool install -e . --force --refresh
```

Browser automation is driven by `browser-harness` (CDP), a transitive
dependency of `cli-tools-shared`. No separate "install browsers" step is
required — the harness manages its own browser binary.

After installation, the `microworkers` command will be available in your terminal.

## Quick Start

```bash
# Authenticate with Microworkers
microworkers auth login

# List available worker jobs
microworkers tasks list --limit 10 --table

# Get full detail for one job
microworkers tasks get "https://www.microworkers.com/jobs_details.php?Id=..." --table

# Preview (dry-run) applying to a job — does NOT submit anything
microworkers tasks apply "https://www.microworkers.com/jobs_details.php?Id=..." --proof-text "..."

# Actually submit proof and apply (only with --confirm)
microworkers tasks apply "https://www.microworkers.com/jobs_details.php?Id=..." --proof-text "..." --confirm
```

## Commands

### Authentication (`microworkers auth`)

```bash
# Interactive login
microworkers auth login

# Force re-authentication
microworkers auth login --force

# Check authentication status
microworkers auth status

# Run the configured live auth test
microworkers auth test

# Clear saved credentials/session
microworkers auth logout
```

Credentials come from the CLI-tools secret manager (`microworkers-username`,
`microworkers-password`), never from `.env`. `auth login` runs the browser
non-interactively when no TTY is available: it fills the live login form
(`Email`/`Password`/submit) with those secrets and verifies the resulting
session, with no manual browser interaction required.

### Tasks (`microworkers tasks`)

Microworkers lists three distinct worker job systems on `/jobs.php`, reported
via the `provider` field:

| Provider | Detail page | Submit endpoint |
|----------|-------------|------------------|
| `microworkers` | `jobs_details.php?Id=...` | `POST /jobs_i_did_it.php` |
| `hire_group` | `hm_jobs_details.php?Id=...` | `POST /hm_jobs_i_did_it.php` |
| `ttv` | `ttv.microworkers.com/dotask/info/...` | out of scope for this CLI |

```bash
# List available jobs (paginated live from /jobs.php, 100 rows/page)
microworkers tasks list --limit 20 --table

# Filter listed jobs
microworkers tasks list --filter "provider:eq:microworkers" --table

# Select specific fields
microworkers tasks list --properties "title,payment" --limit 5

# Get full detail for one job (task-id is the URL from tasks list's id/url field)
microworkers tasks get "https://www.microworkers.com/jobs_details.php?Id=..." --table

# Preview an application (DEFAULT — no --confirm means nothing is submitted)
microworkers tasks apply "https://www.microworkers.com/jobs_details.php?Id=..." \
  --proof-text "Screenshot attached showing completed task"

# Actually submit proof and apply for the job
microworkers tasks apply "https://www.microworkers.com/jobs_details.php?Id=..." \
  --proof-text "Screenshot attached showing completed task" \
  --proof-file /path/to/screenshot.png \
  --confirm \
  --debug-dir /tmp/microworkers-apply-debug
```

**`tasks apply` is dry-run by default.** Without `--confirm`, it fetches the
live job detail (a read) and reports exactly what would be submitted —
`apply_action`, the proof text/file fields the job requires, and whether the
values you passed satisfy them — without ever POSTing to the site. Only
`--confirm` performs the actual submission.

Microworkers requires phone or payment-method verification on the account
before it will accept a job application. If that verification is missing,
`--confirm` submission fails with the site's own verification-required error,
surfaced as a normal command error — this is expected account state, not a
CLI bug.

Every observed Microworkers job (both `microworkers` and `hire_group`
providers) requires uploading a proof file (`Proof_file` / `Proof_file_N`
form fields). `--confirm` uploads the file passed via `--proof-file` into
each required file-input field using
`cli_tools_shared.browser.driver.BrowserHarnessService.set_input_files`
(a CDP `DOM.setFileInputFiles` wrapper). If a job requires a proof file and
`--proof-file` is omitted, or the path doesn't exist, `--confirm` fails with
a clear error before any browser navigation or submission is attempted.

## Cache

```bash
# Clear cached read responses
microworkers cache clear

# Bypass the cache for one execution
microworkers --no-cache tasks list --limit 10
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
- **Non-interactive login**: `browser.py` declares `AUTH_LOGIN_USERNAME_SELECTOR` / `AUTH_LOGIN_PASSWORD_SELECTOR` / `AUTH_LOGIN_SUBMIT_SELECTOR` plus the matching secret-manager names, so `auth login` fills and submits the real login form using stored credentials with no manual browser interaction
- **Data Extraction**: `client.py` drives `page.evaluate()` against the live DOM (`LIST_JS`, `DETAIL_JS`) to extract job listing rows and job detail fields
- **Pagination**: `tasks list` walks `/jobs.php?page=N` (100 rows/page) until `--limit` is satisfied

### Selector/DOM validation

`browser.py` and `client.py`'s `LIST_JS`/`DETAIL_JS` were validated against
the live, authenticated `microworkers.com` DOM (login form, `/jobs.php`
listing rows, `jobs_details.php` and `hm_jobs_details.php` detail pages) —
see the inline comments dated 2026-09-02 in each file for exactly what was
captured and where.

## Browser Automation Notes

- **First run**: Run `microworkers auth login` to launch the persistent browser session and complete login
- **Headless mode**: Set `HEADLESS=false` to watch the browser during debugging
- **Session persistence**: Login sessions are saved under the active profile's browser-data directory
- **Rate limiting**: Be respectful of the site's terms of service

## Debugging

To debug browser automation issues:

```bash
# Run with visible browser
export HEADLESS=false
microworkers tasks list --limit 5
```

## Output Contract

`tasks list` / `tasks get` return plain JSON task records:

| Field | Description |
|-------|-------------|
| `id` | Task detail URL (also usable as the `task-id` argument for `get`/`apply`) |
| `campaign_id` | Short hex campaign ID (list rows only; matches the "Job ID" shown on the detail page) |
| `title` | Job title |
| `provider` | `microworkers`, `hire_group`, or `ttv` |
| `url` | Task detail URL |
| `payment` | Payment amount, e.g. `"$0.30"` |
| `success_rate_required` | Minimum worker success rate required (list rows only) |
| `ttr_days` | Time To Rate, in days (list rows only) |
| `ttf_minutes` | Time To Finish, in minutes (list rows only) |
| `positions_done` / `positions_total` | Positions filled / total positions (list rows only) |
| `work_summary`, `employer`, `employer_url`, `employer_details`, `country_notice`, `instructions_and_proof` | Detail-page fields (`get` only) |
| `apply_action`, `apply_id_field`, `proof_file_fields`, `proof_text_fields` | Submission-form fields (`get`/`apply` only) |

`tasks apply` returns a result record with `confirmed`, `submitted`, and `message`.

## Requirements

- Python 3.11+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - cli-tools-shared (transitively pulls in browser-harness)

## License

MIT
