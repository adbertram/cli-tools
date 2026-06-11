# Awin CLI

## DESCRIPTION

The `awin` CLI provides a command-line interface for Awin API.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Installation

```bash
uv tool install -e <cli-tools-root>/awin
```

## Authentication

Awin uses Bearer token authentication. Generate a token at
https://ui.awin.com/awin-api.

```bash
awin auth login
```

You will be prompted for:

1. **Personal access token** — generated at https://ui.awin.com/awin-api
2. **Awin Publisher ID** — the numeric publisher id shown in the Awin UI
   under your account name

```bash
awin auth status
awin auth logout
```

## Commands

### `publishers`

```bash
# List publisher accounts accessible to your token
awin publishers list
awin publishers list --table
awin publishers list --properties "publisherId,accountName"

# Get one publisher account
awin publishers get 12345
```

### `programmes`

```bash
# List joined advertiser programmes
awin programmes list
awin programmes list --relationship joined --table
awin programmes list --relationship notjoined --limit 50

# Override the default publisher id
awin programmes list --publisher-id 12345 --table

# Get one programme
awin programmes get 678
```

### `auth`

```bash
awin auth login
awin auth status
awin auth logout
awin auth profiles list
```

### `cache`

```bash
awin cache stats
awin cache clear
```

## Output

All commands emit JSON to stdout by default. Pass `--table` / `-t` for a
formatted table. Use `--properties` / `-p` for a comma-separated field
selection (supports dot notation).

## Filters

Every `list` command supports `--filter field:op:value` (repeatable).
Awin's API uses equality filters; pass them through with `field:eq:value`.
