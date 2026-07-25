# Codex Helper CLI

## DESCRIPTION

Codex Helper exposes local Codex app-server account and rate-limit usage through cli-tools JSON and table output. Use it when automation needs current Codex plan windows, credits, reset times, and per-limit IDs without reading or printing Codex tokens.

## Docs

- Wrapped CLI documentation: https://developers.openai.com/codex

## Prerequisites

This CLI wraps the upstream `codex` command-line tool and uses its existing Codex authentication. It does not read, print, or store Codex tokens.

## Installation

```bash
cd <cli-tools-root>/codex-helper
uv tool install -e . --force --refresh
```

After installation, the `codex-helper` command is available in your terminal.

## Quick Start

```bash
codex-helper usage --json
codex-helper usage --table
```

## How It Works

`codex-helper usage` starts the local Codex app-server with:

```bash
codex -s read-only -a untrusted app-server
```

It sends JSON-RPC requests for `account/read` and `account/rateLimits/read`, then normalizes the response.

## Commands

### Usage

```bash
# JSON output, default
codex-helper usage

# Explicit JSON output for automation contracts
codex-helper usage --json

# Human-readable table output
codex-helper usage --table

# Set app-server timeout
codex-helper usage --timeout 45
```

## Output Formats

- JSON is the default output format.
- `--json` is accepted as an explicit compatibility flag for automation that requires it.
- Add `--table` / `-t` for human-readable table output.

## Configuration

The wrapper stores non-authentication configuration in `~/.local/share/cli-tools/codex-helper/.env`. Do not put reusable credentials in any `.env` file.

Root config variables:

```bash
# Underlying CLI command (defaults to codex)
CLI_COMMAND=codex

# Optional: full path to the wrapped CLI executable
# CLI_PATH=
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Client/configuration error |
| 130 | User interrupted |

## Examples

### Read Main Window Usage

```bash
codex-helper usage --json | jq '.limits[] | select(.limit_id == "codex") | .primary'
```

### Show Separate Limit IDs

```bash
codex-helper usage --json | jq '.limits[].limit_id'
```

## Output Contract

`codex-helper usage --json` emits one JSON object:

```json
{
  "account": {"email": "user@example.com", "plan_type": "pro"},
  "limits": [
    {
      "limit_id": "codex",
      "limit_name": null,
      "plan_type": "pro",
      "primary": {
        "used_percent": 13,
        "left_percent": 87,
        "window_duration_mins": 300,
        "resets_at": 1783350186,
        "resets_at_local": "2026-07-06T10:03:06-05:00"
      },
      "secondary": {
        "used_percent": 97,
        "left_percent": 3,
        "window_duration_mins": 10080,
        "resets_at": 1783555281,
        "resets_at_local": "2026-07-08T19:01:21-05:00"
      },
      "rate_limit_reached_type": null
    }
  ],
  "credits": {"has_credits": false, "unlimited": false, "balance": "0"},
  "rate_limit_reset_credits": {"available_count": 0}
}
```

Additional app-server limit IDs returned in `rateLimitsByLimitId`, such as `codex_bengalfox`, appear as additional objects in `limits`.

## Requirements

- Python 3.11+
- `codex` installed and authenticated
- Dependencies installed automatically:
  - typer
  - python-dotenv
  - cli-tools-shared
