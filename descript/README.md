# Descript CLI

## DESCRIPTION

The `descript` CLI provides a command-line interface for Descript API.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Prerequisites

- Descript desktop app installed
- Descript running and signed in
- macOS must allow the shell to read the `Descript Safe Storage` keychain item the first time auth runs

## Installation

```bash
cd descript
pip install -e .
```

## Quick Start

```bash
# Authenticate (extracts JWT from the signed-in desktop app)
descript auth login

# List projects
descript projects list

# List compositions in a project
descript compositions list <project-id>

# Monitor network traffic for API discovery
descript monitor start
```

## Commands

### Authentication

```bash
# Login - extracts JWT from the signed-in desktop app
descript auth login
descript auth login --force  # Clear cache and re-authenticate

# Check authentication status
descript auth status
```

### Projects

```bash
# List projects (JSON output)
descript projects list

# Limit results
descript projects list --limit 10

# Table format
descript projects list --table

# Filter by name
descript projects list --filter "name:Cursor"

# Select specific fields
descript projects list -p "name,composition_count"

# Pipe to jq
descript projects list | jq '.[].name'
```

### Compositions

```bash
# List compositions in a project
descript compositions list <project-id>
descript compositions list <project-id> --table

# Get a specific composition
descript compositions get <project-id> <composition-id>

# Filter compositions
descript compositions list <project-id> --filter "name:m1c1"

# List video assets (raw recordings) for export
descript compositions assets <project-id>
descript compositions assets <project-id> --table

# Export a video asset as MP4
descript compositions export <project-id> <asset-id>
descript compositions export <project-id> <asset-id> -o ./output.mp4
descript compositions export <project-id> <asset-id> --fps 60 --width 3840 --height 2160

# Export a full composition through the Descript desktop app
# Local composition renders can take awhile; the CLI waits up to 30 minutes.
descript compositions export <project-id> --composition "Catalog Page" -o ./catalog-page.mp4
```

### Monitor

```bash
# Start background network monitor
descript monitor start

# Start in foreground (Ctrl+C to stop)
descript monitor start --foreground

# Check monitor status
descript monitor status

# View captured traffic
descript monitor tail
descript monitor tail -n 100
descript monitor tail --follow

# Stop monitor
descript monitor stop
```

## Output Formats

All list/get commands support:
- **JSON** (default): `descript projects list`
- **Table**: `descript projects list --table`

## Options Reference

| Option | Short | Description | Commands |
|--------|-------|-------------|----------|
| `--table` | `-t` | Display as table | list, get, status |
| `--limit` | `-l` | Maximum results | list |
| `--filter` | `-f` | Filter results (field:value) | list |
| `--properties` | `-p` | Select fields (comma-separated) | list |
| `--output` | `-o` | Output file path | export |
| `--fps` | | Frames per second (default: 30) | export |
| `--width` | `-W` | Max width (default: 1920) | export |
| `--height` | `-H` | Max height (default: 1080) | export |
| `--format` | | Export format (default: mp4) | export |
| `--force` | `-F` | Force re-authentication | auth login |
| `--version` | `-v` | Show version | global |

## Authentication Architecture

Descript uses the desktop app's Chromium session cookie for authentication. The JWT token:
- Is read from `~/Library/Application Support/Descript/Partitions/descript2/Cookies`
- Is decrypted with the macOS keychain item `Descript Safe Storage` / `Descript Key`
- Expires every 5 minutes (Stytch default)
- Is cached at `~/.descript/token.json` with a 4-minute TTL
- Auto-refreshes from the app when the cache expires

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication error |
| 130 | User interrupted (Ctrl+C) |

## Models

| Model | Description | Fields |
|-------|-------------|--------|
| `Project` | Video project | id, name, drive_id, created_at, composition_count, owner |
| `ProjectDetail` | Project with compositions | All Project fields + compositions, permissions, thumbnail_url |
| `Composition` | Timeline/sequence | id, name, duration, media_type |
| `VideoAsset` | Raw video recording | id, name, created_at, source |
| `ExportPlaylist` | Export download manifest | url, params, end, expiry, fragment_starts |
| `Owner` | Project owner | id, email, first_name, last_name |

## Requirements

- Python 3.9+
- Dependencies: typer, requests, pydantic, websocket-client, python-dotenv, cryptography
