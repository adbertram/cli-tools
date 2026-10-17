# Crowdgen CLI

## DESCRIPTION

A browser-automation command-line interface for the CrowdGen by Appen worker portal that authenticates as a worker and lists the projects and tasks CrowdGen offers the account. Use this CLI to check the account's available projects from the command line or from an automation run instead of opening the site in a browser by hand.

## Docs

- Worker portal: https://app.crowdgen.com
- Sign-up: https://app.crowdgen.com/apply/signup
- API host (worker frontend): https://api.crowdgen.com

## Live-auth status (2026-09-03)

The `crowdgen` account does not exist yet:

- CrowdGen registration is refused by **Kasada** (kpsdk) for automation-created
  browser sessions on this network: every `POST /api/v1/user/register-new`
  returns `429` with a KPSDK challenge page, even from headed real Chrome over
  CDP with freshly minted `x-kpsdk-ct` / `x-kpsdk-cd` tokens. This is a hard
  anti-bot block for the sign-up flow (no interactive challenge to solve).
- The remaining sign-up steps (mobile number, address/agreements, payout
  method, government-ID check) are **human gates**; login MFA is a TOTP
  authenticator app.
- Until the account exists and logs in once, `crowdgen auth status` reports
  `authenticated: false` and `crowdgen tasks list` cannot run (it raises a
  clear "CrowdGen session required" error).

Once Adam registers manually, completes onboarding and sets up the
authenticator app, run `crowdgen auth login` once, then re-verify with
`crowdgen auth status` and `crowdgen tasks list`.

## Installation

```bash
cd <cli-tools-root>/crowdgen
uv tool install -e . --force --refresh --python "$(command -v python3)"
```

Browser automation is driven by `cli-tools-shared` (browser-harness over CDP);
no separate "install browsers" step is required.

## Quick Start

```bash
# Check authentication state (canonical profile JSON)
crowdgen auth status

# Interactive login — opens the persistent browser; finish any TOTP by hand,
# then press Enter so the session is saved
crowdgen auth login

# Force a fresh login (clears the saved session first)
crowdgen auth login --force

# List worker projects/tasks ([] until the account is shortlisted)
crowdgen tasks list
crowdgen tasks list --table
```

## Commands

### Authentication (`crowdgen auth`)

```bash
crowdgen auth login                 # interactive login (browser session)
crowdgen auth login --force         # clear the saved session and re-login
crowdgen auth status                # profile/auth JSON (stdout, machine-readable)
crowdgen auth test                  # live auth verification
crowdgen auth logout                # clear saved credentials/session
crowdgen auth profiles list         # list auth profiles
crowdgen auth profiles create NAME  # create a named profile
```

CrowdGen login MFA is a TOTP authenticator app. The declarative login hooks in
`crowdgen_cli/browser.py` currently fill username + password
(`#register_email`, `#register_password`, validated against the captured live
login page at `tests/fixtures/login_page.html`). The TOTP step is only
reachable after an account completes onboarding (human gates), so the TOTP
hook constants are intentionally empty; once reachable, capture the TOTP input
selectors live, set `AUTH_LOGIN_TOTP_SELECTOR` / `AUTH_LOGIN_TOTP_SUBMIT_SELECTOR`,
and store the Base32 seed as the `crowdgen-totp-seed` cli-tools secret.

Reusable credentials (username/password/TOTP seed) are stored in the
CLI-tools secret manager under `crowdgen-username`, `crowdgen-password`,
`crowdgen-totp-seed` — never in `.env` files.

### Tasks (`crowdgen tasks`)

```bash
# JSON (default)
crowdgen tasks list
# Table, limit, filter, and field selection
crowdgen tasks list --table
crowdgen tasks list --limit 20
crowdgen tasks list --filter "status:eq:available"
crowdgen tasks list --properties "id,title,url"

# Detail for one listed project/task
crowdgen tasks get <id> --table

# Application is never automated — this is a refusal stub
crowdgen tasks apply <id> --confirm   # always refused
```

`crowdgen tasks list` fetches the frontend's own feed endpoint
`GET https://api.crowdgen.com/api/v1/projects/available` from inside the
authenticated page (endpoint and Bearer-cookie auth model verified from the
deployed bundle `main.b5c37aa5.js`). Because no authenticated capture exists
yet, provably-empty responses return `[]` (the pre-shortlist dashboard) and a
non-empty response whose record shape is unobserved raises a clear error
instead of guessing fields (`crowdgen_cli/parsers.py`). When the first real
record is available, capture it under `tests/fixtures/` and finalize the
parsers, then finalize `microworker_cli/adapters/crowdgen.py`.

## Output Formats

- JSON is the default output format (single JSON document on stdout).
- Add `--table` / `-t` for human-readable table output (Rich).
- All `list` commands support `--filter/-f`, `--limit/-l`, `--properties/-p`.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error / ClientError (including refusal messages) |
| 2 | Not authenticated (`auth status` with no session) |
| 130 | User interrupted (Ctrl+C) |

## Configuration

Non-authentication configuration: `~/.local/share/cli-tools/crowdgen/.env`.
CLI-managed runtime auth state: the active profile's directory under
`~/.local/share/cli-tools/crowdgen/authentication_profiles/`.

Reusable human-supplied credentials are governed by the CLI-tools secret
manager (`<cli-tools-root>/_repo/_secret-manager/secrets.sh`) — see the
`cli-tool-secrets` skill. Do not place reusable credentials in any `.env` file.

```bash
# Optional overrides
BASE_URL=https://app.crowdgen.com
HEADLESS=true            # false = visible browser while debugging
# CACHE_ENABLED=true
# CACHE_TTL=3600
```

## Cache

```bash
crowdgen cache clear                 # clear cached read responses
crowdgen --no-cache tasks list       # bypass the cache for one run
```

## Browser automation notes

- First run: `crowdgen auth login` opens the persistent browser; complete login
  (including TOTP) and press Enter. The session persists in the profile.
- The portal is behind Kasada for unauthenticated API POSTs; the saved
  authenticated session is what this CLI reuses headlessly afterwards.
- Auth indicators, login URLs and selectors are declarative constants in
  `crowdgen_cli/browser.py`, validated against the captured live DOM fixtures.

## Tests

```bash
# Fixture/parser tests (no browser required)
cd <cli-tools-root>/crowdgen
uv run --project . --with pytest python -m pytest tests

# Full cli-tools compliance harness (live-auth dependent parts skip/flag when
# the profile is not authenticated)
<cli-tools-root>/_repo/skills/cli-tool/scripts/test-cli-tool.sh --cli-name crowdgen
```

## License

MIT
