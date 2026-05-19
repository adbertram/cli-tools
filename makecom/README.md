# Make.com CLI

`makecom` is an import-safe, non-shadowing browser CLI for the official Make.com affiliate program. The command name is `makecom` on purpose so it never collides with `/usr/bin/make`.

## Installation

```bash
cd makecom
pip install -e .
playwright install chromium
```

## Quick Start

```bash
makecom program info
makecom program info --table
makecom auth login
makecom auth status
makecom cache clear
```

## Commands

### Program (`makecom program`)

```bash
makecom program info
makecom program info --table
```

### Authentication (`makecom auth`)

```bash
makecom auth login
makecom auth login --force
makecom auth status
makecom auth status --table
makecom auth test
makecom auth logout
makecom auth profiles list
makecom auth profiles get default
makecom auth profiles create work
makecom auth profiles set-default work
makecom auth profiles delete work --force
```

### Cache (`makecom cache`)

```bash
makecom cache clear
```

## Output Formats

- Default output is JSON.
- Use `--table` on supported commands for tabular output.

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Render supported commands as a table |
| `--profile` | `-p` | Use a named authentication profile |
| `--force` | `-F` | Re-authenticate or delete a profile without confirmation |
| `--version` | `-v` | Show version and exit |

## Configuration

The scaffold stores runtime settings in `.env`:

```bash
IS_DEFAULT_PROFILE=1
BASE_URL=https://www.make.com/en/affiliate
HEADLESS=true
AUTH_COOKIE_NAMES=session.*,auth,token,sid
AUTH_TIMEOUT=60
AUTH_POLL_INTERVAL=2
CACHE_ENABLED=true
CACHE_TTL=3600
```

Browser profile data and auth state are stored under `~/.local/share/cli-tools/makecom/.profiles/`.

## Verified Metadata Surface

`makecom program info` returns the current tool metadata for the assigned Airtable research record:

- Product label: `Make.com`
- Record ID: `recnmtpz60wEicTlx`
- Airtable status: `Researched`
- Program URL: `https://www.make.com/en/affiliate`
- Docs URL: `https://help.make.com/affiliate-program`
- CLI type: `browser`
- Auth type: `browser_session`

## Requirements

- Python 3.9+
- `playwright` browsers installed locally
- A Make account if you want to authenticate browser sessions
