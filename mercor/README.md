# Mercor CLI

## DESCRIPTION

A browser-automation CLI for Mercor's AI-talent worker app that lists the role opportunities on
the worker Explore surface as strict JSON records. Use it so MicroWorker discovery can treat
Mercor like any other gig site: authenticate once, then read available roles from the
authenticated session headlessly. Mercor's sign-in is passwordless (email magic link), and its
role catalog is only available behind that session.

## Docs

- Website: https://work.mercor.com
- Login: https://work.mercor.com/login
- Role listing data source: `GET https://aws.api.mercor.com/work/listings-explore-page`

## Installation

```bash
cd <cli-tools-root>/mercor
uv tool install -e . --force --refresh --python "$(command -v python3)"
```

Browser automation is driven by `browser-harness` (CDP), a transitive dependency of
`cli-tools-shared`. No separate "install browsers" step is required — the harness manages its
own browser binary.

After installation the `mercor` command is on PATH (`~/.local/bin/mercor`).

## Configuration

Non-authentication configuration lives in `~/.local/share/cli-tools/mercor/.env`:

```bash
BASE_URL=https://work.mercor.com
# The address Mercor mails the passwordless sign-in link to (the account email).
ACCOUNT_EMAIL=you@example.com
# true = invisible browser; false = visible (debug only)
HEADLESS=true
```

`ACCOUNT_EMAIL` is configuration, not a credential — Mercor has no password, API key or token
to store for this account, so nothing here belongs in the CLI-tools secret manager. Reusable
CLI credentials for other tools are governed by `<cli-tools-root>/_repo/_secret-manager/secrets.sh`;
do not put reusable credentials in any `.env` file.

## Authentication

Mercor signs in through Firebase Auth. The login card at `/login` has only an email field and a
**Login** button (plus Google/Okta SSO): submitting the account email mails a one-time sign-in
link from **Mercor <auth@mercor.com>** (subject "Sign in to Mercor"). The CLI reads that link
back through the repo-owned `google` CLI (Gmail profile `adbertram`) and completes sign-in.
The authenticated session is the `token` cookie on `work.mercor.com` plus Firebase's refresh
token in the profile, so later headless runs restore the session automatically.

```bash
# Authenticate (email magic link; requires ACCOUNT_EMAIL and the google CLI)
mercor auth login

# Check authentication status (canonical per-profile JSON)
mercor auth status

# Force a fresh login after the session has expired
mercor auth login --force

# Live round-trip against the listings API (auth test)
mercor auth test
```

### Bot-protection bootstrap (required the first time)

Mercor's login page also runs reCAPTCHA Enterprise and Firebase App Check. A **headless**
Chromium is rejected there (`content-firebaseappcheck.googleapis.com ... 403` →
`AppCheck: Requests throttled due to 403` for ~24h), which blocks `mercor auth login` from
automation until a real-Chrome session exists in the profile. The one-time bootstrap therefore
runs real system Chrome (headed but launched in the background so it does not steal focus)
against the CLI's persistent profile directory:

```bash
PROFILE=~/.local/share/cli-tools/mercor/authentication_profiles/default/browser-data/chromium-profile
/Users/adam/.agents/skills/browser-automation/scripts/launch-cdp-chrome.sh \
  --port 9223 --profile "$PROFILE" --hold     # supervised background Chrome
```

Then drive it over CDP (page-level websocket, since this Chrome build rejects browser-level CDP
context commands) or a normal Chrome window: open https://work.mercor.com/login, enter
`ACCOUNT_EMAIL`, click **Login**, open the emailed magic link, and confirm the app lands on
`https://work.mercor.com/explore`. Kill the supervised Chrome, then re-run `mercor auth status`
— it must report `"authenticated": true` from the saved profile headlessly. From then on
`mercor auth status` and `mercor tasks *` run headlessly with no visible browser.

`mercor auth login` implements the same magic-link flow and raises an actionable error naming
this bootstrap when the App Check wall blocks a headless attempt, rather than pretending a
password would help. The wall's markers ("Requests throttled due to 403" / "appCheck/throttled")
are written to the browser console, not the page, so the CLI also treats a headless submit that
times out with the login card unchanged as the wall and points at this bootstrap (see
`mercor_cli/browser.py`).

## Commands

### Role listings (`mercor tasks`)

The worker Explore surface (`https://work.mercor.com/explore`) renders its role cards from the
internal JSON API `GET https://aws.api.mercor.com/work/listings-explore-page`, authorized by the
session's Firebase ID token. `tasks list` fetches that catalog (one cursorless call, ~400
active public listings at capture time); each record keeps every field the API returns plus the
derived convenience fields `id` (= `listingId`), `title` and `url`.

```bash
# All role listings, JSON (full catalog; default limit 1000)
mercor tasks list

# First 10, as a table
mercor tasks list --limit 10 --table

# Filter on real record fields (e.g. pay frequency or listing type)
mercor tasks list --filter "payRateFrequency:eq:per-task" --limit 5

# Only selected fields
mercor tasks list --properties "id,title,rateMin,rateMax,remainingSlots" --limit 3

# Full record for one listing
mercor tasks get list_AAABoGdJ4CbRDb3Q0LxObpT2

# Single listing, key fields, as JSON
mercor tasks get list_AAABoGdJ4CbRDb3Q0LxObpT2 --properties id,title,location,remainingSlots
```

Example record (`mercor tasks list | head`): every field of the raw listing object is present;
`id`, `title` and `url` are the derived public keys.

```json
{
  "listingId": "list_AAABoGdJ4CbRDb3Q0LxObpT2",
  "id": "list_AAABoGdJ4CbRDb3Q0LxObpT2",
  "title": "Video Evaluation Generalist",
  "status": "active",
  "rateMin": 15.0,
  "rateMax": 20.0,
  "payRateFrequency": "hourly",
  "remainingSlots": 200,
  "url": "https://work.mercor.com/explore?listingId=list_AAABoGdJ4CbRDb3Q0LxObpT2"
}
```

Useful real record fields: `listingId`, `uid`, `title`, `description`, `status`, `listingType`
(`standard`/`evergreen`), `rateMin`, `rateMax`, `payRateFrequency` (`hourly`/`per-task`/
`one-time`/`yearly`), `commitment`, `workArrangement` (`remote`/`hybrid`/`onsite`),
`location`, `eligibleLocation`/`ineligibleLocation`, `remainingSlots`, `referralAmount`,
`hoursPerWeek`, `postedAt`, `createdAt`, `companyName`, `isPrivate`, `disableApplications`.
Mercor publishes no currency code on a listing record — `pay_currency` is therefore always
unknown at the adapter layer; rates are raw numbers whose unit is `payRateFrequency`.

### Apply (dry-run stub — never used)

`mercor tasks apply` performs **no action and never contacts Mercor**. MicroWorker's hard rule
is that discovery never applies: submitting an application is Adam's decision in a live
conversation, so this CLI has no application path at all.

```bash
# Refuses (exit 1) without --confirm
mercor tasks apply list_AAABoGdJ4CbRDb3Q0LxObpT2

# Even with --confirm it only prints the dry-run record (applied: false)
mercor tasks apply list_AAABoGdJ4CbRDb3Q0LxObpT2 --confirm
```

### Authentication (`mercor auth`)

```bash
# Interactive login (magic link; see Authentication above)
mercor auth login

# Force re-authentication
mercor auth login --force

# Check authentication status
mercor auth status

# Live auth round-trip against the listings API
mercor auth test

# Clear saved session/browser state
mercor auth logout
```

### Profiles (`mercor auth profiles`)

```bash
# List all profiles
mercor auth profiles list

# Show a profile
mercor auth profiles get default

# Select the active profile for its auth type
mercor auth profiles select PROFILE_NAME

# Create a profile
mercor auth profiles create PROFILE_NAME

# Delete a profile
mercor auth profiles delete PROFILE_NAME
```

### Cache (`mercor cache`)

```bash
# Clear cached read responses
mercor cache clear

# Bypass the cache for one execution
mercor --no-cache tasks list --limit 5
```

## Output Formats

- JSON is the default output format (`print_json`, strict JSON: finite numbers only, nulls for
  unknown values — nothing is invented).
- Add `--table` / `-t` for human-readable table output (first columns only).

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display data as a table |
| `--limit` | `-l` | Maximum number of results |
| `--filter` | `-f` | Filter results using `field:op:value` syntax |
| `--properties` | `-p` | Restrict output to selected fields |
| `--profile` |  | Authentication profile name |
| `--confirm` |  | Acknowledge the apply stub (it still never applies) |
| `--version` | `-v` | Show version and exit |
| `--no-cache` |  | Bypass cached read responses for this execution |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error (including apply without `--confirm`) |
| 2 | Authentication/credential error |

## Architecture

This CLI uses `cli_tools_shared.auth.BrowserAutomation` with browser-harness-backed Chrome
automation and mirrors the outlier/oneforma CLI structure:

- `browser.py` — declarative auth hooks plus the email-magic-link login handler, tuned to the
  real login DOM (see its module docstring for the live 2026-09-03 evidence).
- `magic_link.py` — reads the one-time Firebase sign-in link out of Gmail via the `google` CLI.
- `client.py` — boots the authenticated profile headlessly to read a fresh session token, then
  GETs the listings API over HTTPS (in-page cross-origin fetches are rejected by the API for
  headless browsers — validated live).
- `parsers.py` — normalizes raw listing records into the public record shape (raw fields kept,
  `id`/`title`/`url` derived).
- `main.py` — the Typer command contract (`tasks list|get|apply`, `auth`, `cache`).

### Session persistence

Browser context persists between commands in the profile data directory
(`~/.local/share/cli-tools/mercor/authentication_profiles/<profile>/browser-data/chromium-profile`):
cookies, localStorage (including the Firebase refresh token) and IndexedDB. Once the CDP
bootstrap above has authenticated once, every later headless run restores the session.

## Test Fixtures

`tests/fixtures/` holds real captures from Adam's authenticated Mercor session
(captured 2026-09-03):

- `listings_explore_page.json` — the first 8 records of the live 402-listing
  `GET aws.api.mercor.com/work/listings-explore-page` response (records untouched).
- `explore_dom_snapshot.html` — the live `/explore` page DOM (documentElement.outerHTML).

Parsers and adapters are validated only against these real records; nothing is guessed.

## Requirements

- Python 3.11+
- Dependencies (installed automatically): typer, python-dotenv, cli-tools-shared
  (transitively pulls in browser-harness)
- The repo-owned `google` CLI (for reading the sign-in email), and the repo-owned
  `browser-automation` skill scripts (for the one-time CDP bootstrap)

## License

MIT
