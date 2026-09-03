# Atlas Capture CLI

## DESCRIPTION

A browser-automation command-line interface for Atlas Capture, the worker
portal for AI training-data annotation tasks. Use it to authenticate your
worker account and to list and inspect the annotation tasks the site exposes
to it through an authenticated persistent browser session. This CLI is
discovery-only and never applies to a task.

## Scope

This CLI never applies to, accepts, or submits a task — MicroWorker's hard
rule: applying is Adam's decision, made in the conversation that approves the
exact task. `tasks apply` is a refusal stub that always refuses, with or
without `--confirm`.

## Docs

- Website: https://audit.atlascapture.io
- Login flow: passwordless email one-time code (Stytch) behind Cloudflare Turnstile

## Installation

```bash
cd <cli-tools-root>/atlas-capture
uv tool install -e . --force --refresh --python "$(command -v python3)"
```

Browser automation is driven by `browser-harness` (CDP), a transitive
dependency of `cli-tools-shared`. No separate "install browsers" step is
required — the harness manages its own browser binary.

After installation, the `atlas-capture` command will be available in your terminal.

## Authentication

Atlas Capture has **no password**. The account signs in with a 6-digit code
emailed by Stytch (`login@stytch.com`, subject "Your one-time login code for
Atlas"). The login form also runs Cloudflare Turnstile, which only mints its
token in a **headed** browser, so `auth login` must run headed:

```bash
HEADLESS=false atlas-capture auth login --force
```

The login handler fills the email, submits, reads the emailed code back
through the `google` Gmail CLI (profile `adbertram`), and submits it — the code
is never printed. The resulting session lives in the CLI's persistent Chrome
profile, so every later command runs headless with no login.

The login email is stored as the reusable CLI-tools secret
`atlas-capture-email` (a username, not a password):

```bash
printf '%s' 'you@example.com' | <cli-tools-root>/_repo/_secret-manager/secrets.sh set --tool atlas-capture --type email
```

`ATLAS_CAPTURE_EMAIL` overrides the secret for one-off runs.

If an interactive "Verify you are human" checkbox appears and will not clear,
a human must pass it once (headed, by hand); afterwards the saved session
persists for headless runs.

## Quick Start

```bash
# Authenticate (headed; sends an email code and reads it back from Gmail)
HEADLESS=false atlas-capture auth login

# Confirm the session persisted for headless runs
atlas-capture auth status

# List available worker tasks (JSON array; [] today — see below)
atlas-capture tasks list

# Inspect the account's live onboarding/certification state
atlas-capture account show --table
```

## Commands

### Authentication (`atlas-capture auth`)

```bash
# Log in (headed — see Authentication)
HEADLESS=false atlas-capture auth login

# Force re-authentication
HEADLESS=false atlas-capture auth login --force

# Check authentication status (live check; JSON profile schema)
atlas-capture auth status

# Run the configured live auth test
atlas-capture auth test

# Clear the saved session
atlas-capture auth logout
```

### Tasks (`atlas-capture tasks`)

```bash
# List tasks the account can see — JSON array on stdout
atlas-capture tasks list

# Limit, filter, or reshape the output
atlas-capture tasks list --limit 20
atlas-capture tasks list --filter "status:eq:open"
atlas-capture tasks list --properties id,title,url --table

# Get one task's full detail (needs a real task id)
atlas-capture tasks get TASK_ID --table

# Apply is DISABLED — refusal stub (MicroWorker discovery never applies)
atlas-capture tasks apply TASK_ID --confirm   # always refuses, exit 1
```

`tasks list` asks the site for `/tasks` and reports what the account can
actually see. As of 2026-09-03 the account's `/tasks` route redirects to
`/dashboard` (no Tasks nav item), so the command returns `[]` and prints the
reason on stderr. See **Current account state** below.

### Account (`atlas-capture account`)

```bash
# Live user.me facts from the authenticated session
atlas-capture account show
atlas-capture account show --table
```

Outputs the real account record the site returns: id, email, name, country,
role, reviewer tier, onboarding step/completion, GT-probation completion and
certified-role count. Unknown fields stay `null` — nothing is invented.

### Cache (`atlas-capture cache`)

```bash
atlas-capture cache status
atlas-capture cache clear
```

## Output contract

- stdout carries **data only**: JSON for list/get/show, tables only with
  `--table`. stderr carries messages (progress, reasons, errors).
- `tasks list` always prints a JSON array (`[]` when no task surface exists).
- Numbers are finite; unknown values are `null`; nothing is invented.

## Current account state (live evidence, 2026-09-03)

Authenticated account: Adam Bertram (`adbertram@gmail.com`, role USER,
reviewer tier 1).

- Onboarding wizard: complete (`onboardingStep: 4`, `onboardingCompleted: true`)
- GT probation: NOT complete (`gtProbationCompleted: false`); certifications:
  none (`certification.getAll` → `[]`)
- Labeling: the site currently shows a platform-wide **"Temporary Labeling
  Pause"** announcement
- Surge/task eligibility: not eligible (`payment.getSurgeStatus` →
  `userEligibleForAudience: false`)

Because of the certification gap and the pause, no task records are exposed:
`/tasks` redirects to `/dashboard`, `tasks list` → `[]`, and no real task
record has been captured yet — so there is nothing to parse or map (see
`atlas_capture_cli/parsers.py` and the microworker `adapters/atlas_capture.py`
adapter, both of which refuse to guess a schema rather than invent one). The
day tasks appear, capture one real record and implement the mapping.

## Environment

- `.env.example` documents shape only; reusable credentials live in the
  CLI-tools secret manager (never in `.env` files).

## Requirements

- Python 3.11+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - cli-tools-shared (transitively pulls in browser-harness)

## License

MIT
