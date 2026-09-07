# Microworkers CLI

## DESCRIPTION

A browser-automation command-line interface for Microworkers (worker side). Use it to list available worker jobs, inspect a job's full requirements, and, with explicit confirmation, submit proof for a job through an authenticated persistent browser session.

## Scope

This CLI is worker-side only. Microworkers also runs TTV campaign pages on
`ttv.microworkers.com`. TTV jobs listed by `tasks list` are reported with
`"provider": "ttv"`; `tasks get` reads their authenticated pre-accept details
and exact allocation-form metadata. `tasks apply` dry-runs allocation; only
explicit `--confirm` accepts/starts that exact TTV task. TTV proof submission
remains deliberately unsupported.

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

# List submitted Basic-task history and review/payment state
microworkers tasks history --limit 10 --table

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
| `ttv` | `ttv.microworkers.com/dotask/info/...` | `POST /dotask/allocateposition` (accept/start only; no proof submission) |

```bash
# List available jobs (paginated live from /jobs.php, 100 rows/page)
microworkers tasks list --limit 20 --table

# Filter listed jobs
microworkers tasks list --filter "provider:eq:microworkers" --table

# Select specific fields
microworkers tasks list --properties "title,payment" --limit 5

# Read Basic-task submission history; default output is a JSON array
microworkers tasks history --limit 20

# Filter history and select fields
microworkers tasks history \
  --filter "status:eq:Pending Employer review" \
  --properties "id,title,submitted_at,status,payment,payment_status"

# Get full detail for one job (task-id is the URL from tasks list's id/url field)
microworkers tasks get "https://www.microworkers.com/jobs_details.php?Id=..." --table

# Read a TTV job's pre-accept detail and allocation-form metadata (no mutation)
microworkers tasks get "https://ttv.microworkers.com/dotask/info/..._HG"

# Complete a supported read-only work pattern and collect evidence/proof
microworkers tasks work "https://www.microworkers.com/jobs_details.php?Id=..." \
  --artifact-dir /path/to/task-evidence

# Preview an application (DEFAULT — no --confirm means nothing is submitted)
microworkers tasks apply "https://www.microworkers.com/jobs_details.php?Id=..." \
  --proof-text "Screenshot attached showing completed task"

# Preflight a TTV allocation (read-only; does not accept/start)
microworkers tasks apply "https://ttv.microworkers.com/dotask/info/..._HG"

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
`--confirm` performs the provider action: Basic/Hire Group proof submission or
TTV accept/start allocation. Before crossing that mutation
boundary, the CLI binds the request to the exact HTTPS task URL, provider,
task `Id`, POST action, hidden `Id`, and single submit button. If reopening the
task returns Microworkers' authoritative `Worker already submitted this task.`
message or the Basic-task `jobs_user_already_took.php` redirect with `Sorry but
you already submitted this task.`, the command returns
`state: "already_submitted"` without clicking anything.

A confirmed Basic/Hire Group run clicks the submit button at most once. It
never retries a click. Afterward, it reopens the exact task URL and reports
`state: "submitted"` and `submitted: true` only when one of those authoritative
states is present. A timeout, unrecognized redirect, missing marker, or other
failure after the click is reported as an ambiguous outcome with an explicit
**do not retry automatically** instruction; inspect the exact task on
Microworkers first.

For TTV, dry-run returns `state: "ready_to_allocate"`, the exact POST action,
hidden `CampaignId`, and `Accept and Start` label with
`mutation_attempted: false`. Confirm clicks that exact button at most once and
never retries. It reports `state: "allocated"` only when the post-click page is
still on the exact TTV host, the allocation form is gone, and exactly one
campaign-bound task form plus the instruction panel are present. Otherwise it
reports an ambiguous outcome and instructs callers not to retry automatically.
This path allocates work only; it never submits proof.

`tasks history` is read-only. It parses each Basic-history row on `worker.php`,
binds the row's status icon to the legend on that page, and reads the row's
safe task-detail popup endpoint to obtain exact `Task ID`, `Job ID`, `Finished`,
and `Earned` values. The result never exposes or follows the row's remove/delete
link. The task URL is `null` because this history surface does not expose the
original task URL. Unknown values remain `null`; submission alone is never
treated as proof of payment.

### Read-only task work

`tasks work` completes supported public-page instruction patterns without
accepting or submitting the Microworkers task. It always fetches the live task
instructions first, selects an adapter from instruction content rather than a
task ID, and writes page HTML plus structured evidence JSON beneath the
required `--artifact-dir`.

For a pre-allocation TTV URL, `tasks work` saves the visible task detail and
then fails clearly that allocation is required; it never clicks `Accept and
Start`. Post-allocation TTV task/form automation remains fail-closed until its
live DOM is captured and validated. It does not invent selectors or submit
external forms from the pre-accept preview.

Supported patterns:

- TNW article section → click the instructed linked word → collect the former
  product name, final URL, and an exact capability statement from the product
  page.
- Wizardly keyword page → perform the Google search → click exactly one
  organic result for the instructed target host → collect the labeled
  verification code only when the destination proves a Google referrer.
- Inc.com expandable article → open the exact article, click the one visible
  `Expand to continue reading` control, find the instructed Wayfront link in
  the named section, and collect its adjacent former name plus one capability
  stated on the linked product page.
- Bing search-and-visit → issue the exact instructed query, resolve the masked
  domain from one organic result, and prove that destination stayed visible on
  the same URL for 60 seconds.
- Kurt Finney direct page → click its one visible IMDb link, then derive the
  first acting movie and 2013 acting-movie count from unique title IDs.
- AI News article → click the exact `AI romance survey` link in the second
  visible article paragraph, then collect the survey's visible title and its
  single stated U.S.-adult participant count.

The result includes `proof_text`, `evidence`, `artifacts`, `submitted: false`,
and `task_mutation_attempted: false`. The command does not call `tasks apply`,
does not fill Microworkers proof fields, and does not click its submit button.

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
a clear error before any submission is attempted.

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
- **Data Extraction**: `client.py` drives `page.evaluate()` against the live DOM (`LIST_JS`, `DETAIL_JS`, `TTV_DETAIL_JS`) to extract job listing rows and job detail fields
- **Pagination**: `tasks list` walks `/jobs.php?page=N` (100 rows/page) until `--limit` is satisfied

### Selector/DOM validation

`browser.py` and `client.py`'s detail extractors were validated against
the live, authenticated `microworkers.com` DOM (login form, `/jobs.php`
listing rows, `jobs_details.php`, `hm_jobs_details.php`, and six
`ttv.microworkers.com/dotask/info/...` detail pages). See dated inline comments
in each file for what was captured and where.

## Browser Automation Notes

- **First run**: Run `microworkers auth login` to launch the persistent browser session and complete login
- **Headless mode**: Set `HEADLESS=false` to watch the browser during debugging
- **Session persistence**: Login sessions are saved under the active profile's browser-data directory
- **Rate limiting**: Be respectful of the site's terms of service
- **Listing pacing**: `tasks list` walks `/jobs.php` one page at a time and
  pauses a jittered delay between consecutive pages so the listing cadence
  stays inside a human-looking rhythm (Microworkers bans accounts for
  "Auto-refresh / Bot" cadence). The delay is configurable:
  `LIST_PAGE_DELAY_SECONDS` (base seconds, default `4.0`) and
  `LIST_PAGE_DELAY_JITTER` (fractional jitter, default `0.5`; each pause is
  drawn from `base * [1 - jitter, 1 + jitter]`). Pages fetched are bounded by
  the `--limit` value (100 rows/page), never a fixed walk of the full queue.

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
| `apply_action`, `apply_method`, `apply_id_field`, `apply_hidden_fields`, `apply_submit_label`, `proof_file_fields`, `proof_text_fields` | Read-only form metadata (`get`; TTV reports its pre-accept allocation form) and supported Basic/Hire Group submission fields (`apply`) |
| `proof_text`, `evidence`, `artifacts` | Evidence-backed result fields (`work` only) |

`tasks apply` returns a result record with `confirmed`, `submitted`, `state`,
`mutation_attempted`, `post_verified`, and `message`. `state` is `ready` for a
dry run, `already_submitted` for an idempotent preflight result, or `submitted`
only after authoritative post-verification. Ambiguous post-click outcomes are
command errors, never successful result records.

## Requirements

- Python 3.11+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - cli-tools-shared (transitively pulls in browser-harness)

## License

MIT
