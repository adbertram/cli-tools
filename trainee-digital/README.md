# trainee-digital CLI

## DESCRIPTION

A browser-automation command-line interface for the trainee-digital data-annotation orders marketplace that lists the open annotation orders on the worker feed and reads full order detail from Adam's existing account. Use this CLI for repeatable, scriptable access to that feed — it only discovers and reports, and never applies to a task.

## Docs

- Website: https://trainee.digital
- Order feed page: https://trainee.digital/orders
- Clerk Account Portal (login): https://accounts.trainee.digital/sign-in

## Installation

```bash
cd <cli-tools-root>/trainee-digital
uv tool install -e . --force --refresh --python "$(command -v python3)"
```

Browser automation is driven by `browser-harness` (CDP), a transitive
dependency of `cli-tools-shared`. No separate "install browsers" step is
required — the harness manages its own browser binary.

After installation the `trainee-digital` command is on PATH.

## Quick Start

```bash
# Configure the account email once (non-secret config)
trainee-digital auth login        # prompts for ACCOUNT_EMAIL on first run

# Authenticate (see Authentication below)
trainee-digital auth login

# Check the session
trainee-digital auth status       # -> {"profiles": [{..., "authenticated": true, ...}]}

# List open orders (JSON array, default)
trainee-digital tasks list

# One order's full detail
trainee-digital tasks get med-seg
```

## Authentication

The account signs in through Clerk with a **6-digit emailed verification
code** — no password is stored for this account. `trainee-digital auth login`
opens the Clerk Account Portal, submits the account email, reads the code back
out of Gmail (through the repo-owned `google` CLI — the mail is from
`notifications@trainee.digital` with subject `<6 digits> is your verification
code`), types it, and saves the resulting `__session` cookie in the CLI's
persistent browser profile. The session persists across runs until it expires
or is signed out.

`ACCOUNT_EMAIL` is non-secret configuration: the address the login code is
mailed to. Set it in `~/.local/share/cli-tools/trainee-digital/.env`:

```bash
ACCOUNT_EMAIL=adbertram@gmail.com
```

`auth login` prompts for it once via `AUTH_CONFIG_PROMPTS` when it is missing.

### Cloudflare bot wall and the one-time CDP bootstrap

`accounts.trainee.digital` (the Clerk portal) sits behind a Cloudflare
"Performing security verification" interstitial that does **not** clear for
headless automation browsers. `trainee.digital` itself and its `/api/*`
endpoints are not walled, so every command after login runs headless against
the saved profile. The one-time login therefore has to happen in real system
Chrome over CDP against the CLI's own profile directory; afterwards the saved
profile authenticates headless (this mirrors the mercor and oneforma CLIs).
When a headless `auth login` meets the wall it stops with the exact profile
path and these instructions.

One-time bootstrap:

```bash
# 1. Launch real system Chrome (backgrounded, no focus steal) on the CLI profile
~/.agents/skills/browser-automation/scripts/launch-cdp-chrome.sh \
  --port 9225 \
  --profile ~/.local/share/cli-tools/trainee-digital/authentication_profiles/default/browser-data/chromium-profile \
  --hold

# 2. In that Chrome, sign in at https://accounts.trainee.digital/sign-in:
#    enter the account email, click Continue, enter the emailed code.
#    (The code arrives from notifications@trainee.digital; read it with
#    `google gmail search "from:notifications@trainee.digital" -l 1 -p id,subject`.)

# 3. Quit that Chrome (Ctrl-C the launcher), then verify the CLI session:
trainee-digital auth status       # authenticated: true
```

An interactive human-verification prompt (Turnstile checkbox, CAPTCHA) on the
portal is a **hard stop**: complete it in the real-Chrome bootstrap only. The
CLI never clicks through or solves one.

## Commands

### Authentication (`trainee-digital auth`)

```bash
# Interactive/automated login (emailed code; see Authentication)
trainee-digital auth login

# Force re-authentication
trainee-digital auth login --force

# Check authentication status (canonical per-profile JSON)
trainee-digital auth status

# Run the configured live auth test (API round-trip against the account)
trainee-digital auth test

# Clear the saved session
trainee-digital auth logout
```

### Profiles (`trainee-digital auth profiles`)

```bash
trainee-digital auth profiles list
trainee-digital auth profiles get default
trainee-digital auth profiles select PROFILE_NAME
trainee-digital auth profiles create PROFILE_NAME
trainee-digital auth profiles delete PROFILE_NAME
```

### Tasks (`trainee-digital tasks`)

```bash
# List the open annotation orders (JSON array; every API field is kept)
trainee-digital tasks list

# Limit the number of rows
trainee-digital tasks list --limit 5

# Filter client-side with field:op:value syntax (e.g. by category)
trainee-digital tasks list --filter "category:eq:Fintech"

# Restrict output fields (dot-notation supported)
trainee-digital tasks list --properties id,title,pay

# Table output
trainee-digital tasks list --table

# Full detail for one order
trainee-digital tasks get med-seg
trainee-digital tasks get med-seg --table

# Apply to an order — ALWAYS REFUSED (MicroWorker never applies)
trainee-digital tasks apply med-seg --confirm
```

The order-feed records come from `GET /api/orders` and carry `id`, `title`,
`category`, `pay`, `unit`, `volume`, `deadline`, `posted`; `tasks get` adds
`totalPay`, `dataset`, `scope`, `guidelines`, `createdAt` when the API fills
them. Records keep every field the API returns plus the derived `url` (the
`/orders` listing page). Pay values are the site's own display strings such as
`"$0.40"` — nothing is invented.

## Output Formats

- JSON is the default output format.
- Add `--table` / `-t` for human-readable table output.

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

Non-authentication configuration lives in
`~/.local/share/cli-tools/trainee-digital/.env`. CLI-managed runtime auth
state lives in the active profile at
`~/.local/share/cli-tools/trainee-digital/authentication_profiles/<profile>/`.
The source repo only carries `.env.example` (shape only).

Reusable CLI credentials that agents or scripts need to store/retrieve are
governed by the user-level `cli-tool` skill's `references/secrets.md`. This
account has **no** reusable credential (no password or token) — the login code
is emailed per session — so nothing is stored in the CLI-tools secret manager.

Do not put reusable credentials in any `.env` file. Store and retrieve them
through `<cli-tools-root>/_repo/_secret-manager/secrets.sh`. `.env` files are
limited to non-secret config and CLI-managed runtime auth state.

Root config variables:

```bash
# Optional: override the default site URL
BASE_URL=https://trainee.digital

# The account email Clerk mails the login code to (required by auth login)
ACCOUNT_EMAIL=adbertram@gmail.com

# Browser settings (true = invisible, false = visible browser)
HEADLESS=true

# Response cache settings
CACHE_ENABLED=true
CACHE_TTL=3600
```

Browser-auth selectors, login URLs, and authenticated-page signals are defined
in `browser.py` as `BrowserAutomation` class constants, validated against the
live site 2026-09-03.

## Cache

```bash
# Clear cached read responses
trainee-digital cache clear

# Bypass the cache for one execution
trainee-digital --no-cache tasks list --limit 10
```

Browser session data (including the Clerk `__session` cookie) is stored in the
active profile's `browser-data/` directory so sessions persist between
commands.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error (including `tasks apply` refusals) |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Architecture

This CLI uses `cli_tools_shared.auth.BrowserAutomation` with browser-harness-
backed Chrome automation:

- **Session persistence**: the Clerk `__session` cookie lives in the CLI's
  persistent Chromium profile (`browser-data/chromium-profile`).
- **Auth check**: `auth status` treats the presence of the `__session` cookie
  on trainee.digital as the live authenticated signal.
- **Data path**: trainee.digital's SPA fetches orders from same-origin JSON
  endpoints authenticated with a short-lived Clerk session token minted via
  the Clerk frontend API. `client.py` reproduces that exact mint-and-fetch
  (`GET /api/orders`, `GET /api/orders/<id>`, `GET /api/me/profile`) from
  inside the authenticated page — no DOM scraping.
- **Email-code login**: `browser.py` owns the sign-in choreography; the code
  is read out of Gmail by `email_code.py` through the repo-owned `google` CLI.

## Live evidence (2026-09-03)

Authenticated as `adbertram@gmail.com` on trainee.digital:

- Worker role: candidate (not yet vetted).
- Account state: `GET /api/me/vetting` → `{"status": "pending", "score": 0,
  "passingScore": 70, "reward": 5, "issuedAt": "2026-08-30"}` — the free
  50-unit quality review is gated on this account (score 0, one attempt).
- Earnings/balance: `GET /api/me/billing` → `{"balance": 5, "vetted": false,
  "canWithdraw": false, "minWithdrawal": 100, ...}` — the $5 signup welcome
  credit is present; passing the review credits another $5 and unlocks the
  paid order feed (per the site's own /orders copy). Withdrawals need a $100
  minimum and cannot be initiated on this account.
- Order feed seen by this logged-in account: the public catalog of six
  illustrative order types at `/orders` (live `GET /api/orders`). The full
  paid feed unlocks after vetting.

Captured response bodies for these endpoints are saved under
`tests/fixtures/` and drive the parser and command tests.

## Requirements

- Python 3.11+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - cli-tools-shared (transitively pulls in browser-harness)
- The repo-owned `google` CLI (for reading the emailed login code at `auth
  login` time only)

## License

MIT
