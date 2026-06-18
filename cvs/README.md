# cvs CLI

## DESCRIPTION

The `cvs` CLI is a command-line interface for CVS Health pharmacy — prescriptions, orders, and refill eligibility across all linked family members. Use it for scriptable, JSON-first access from agents, automation, or terminal workflows. Authentication is a real browser login that the CLI then reuses for read-only commands.

## Installation

Installed as an isolated uv tool; the `cvs` command is on your PATH.

## Authentication

```bash
# Log in. Opens a NORMAL Chrome window (no automation attached, so CVS's bot
# detection does not block it). Log in by hand — finish any OTP/CAPTCHA — until
# your account/prescriptions page is visible, then return to the terminal and
# press Enter to capture the session.
cvs auth login

# Check auth status (performs a live round-trip — reflects ground truth, not
# just on-disk state). Exit 0 if authenticated, 2 if not.
cvs auth status
cvs auth status --table

# Verify the session can actually reach the CVS API.
cvs auth test

# Clear the stored session and credentials.
cvs auth logout
```

Do not pass `--force` for a routine re-login: a plain `cvs auth login` re-uses
the existing profile (preserving the device-trust cookies that help you pass
CVS's risk check) and re-opens the browser automatically when the saved session
is no longer valid.

### Profiles

```bash
cvs auth profiles list            # list profiles (--table, --filter, --limit)
cvs auth profiles get default     # show one profile
cvs auth profiles create NAME     # new profile
cvs auth profiles select NAME     # set the active profile
cvs auth profiles delete NAME [--force]
```

## Commands

### Prescriptions

```bash
cvs prescriptions list                              # JSON
cvs prescriptions list --table                      # table
cvs prescriptions list --limit 10
cvs prescriptions list --filter isRefillable:eq:true
cvs prescriptions list --properties id,drugInfo.drug.name
cvs prescriptions get RX_ID
```

### Orders

```bash
cvs orders list [--table] [--limit N] [--filter F] [--properties P]
cvs orders get ORDER_ID
```

### Refills

```bash
cvs refills check [--table] [--limit N] [--filter F] [--properties P]
```

### Auto Refills

```bash
cvs auto-refills start RX_ID --yes
cvs auto-refills stop RX_ID --yes
```

### Cache

```bash
cvs cache clear     # remove cached responses
```

## Options Reference

| Option | Short | Applies to | Description |
|--------|-------|------------|-------------|
| `--table` | `-t` | list/get/status | Human-readable table instead of JSON |
| `--limit` | `-l` | list/check | Max results (`0`/negative = no limit) |
| `--filter` | `-f` | list/check | `field:op:value` (e.g. `isRefillable:eq:true`, dotted paths supported) |
| `--properties` | `-p` | list/check | Comma-separated fields to include |
| `--no-cache` | | global | Bypass the response cache |
| `--version` | `-v` | global | Show version and exit |

## Output

- **JSON** (default): machine-readable, pipe to `jq`.
- **Table** (`--table`): human-readable.

Malformed records in a CVS response are skipped (with a warning on stderr) so a
single bad record never aborts an entire `list`.

```bash
cvs prescriptions list | jq '.[] | {id, drug: .drugInfo.drug.name}'
cvs refills check --table
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error (e.g. not found, unexpected response) |
| 2 | Authentication/credential error — run `cvs auth login` |
| 130 | Interrupted (Ctrl+C) |

## Notes

- Read-only commands open a headless browser to read the live session, then call
  the CVS experience API. `auth login` is the only command that opens a visible
  browser.
- Credentials/session live under
  `~/.local/share/cli-tools/cvs/authentication_profiles/<profile>/`.
