# Descript CLI

## DESCRIPTION

The `descript` CLI provides a command-line interface for Descript API.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Prerequisites

- Node.js 24 or newer
- Official Descript API CLI package is auto-provisioned on first use under
  `~/.local/share/cli-tools/descript/platform-cli/` (or
  `$XDG_DATA_HOME/cli-tools/descript/platform-cli/`)

Desktop-only export helpers still require:
- Descript desktop app installed
- Descript running and signed in
- macOS must allow the shell to read the `Descript Safe Storage` keychain item when raw/local export helpers need the desktop session

## Installation

```bash
cd descript
pip install -e .
```

## Quick Start

```bash
# Authenticate the official Descript API CLI
descript auth login

# Or use the official config command directly
descript config set api-key

# List projects through the official API CLI
descript projects list

# List compositions from the official project summary
descript compositions list <project-id>

# Import media and run Underlord through the official CLI
descript import --name "My Project" --media "https://example.com/video.mp4"
descript import --name "Shared Project" --media ./voiceover.wav --folder Pluralsight --team-access edit
descript agent --project-id <project-id> --prompt "Remove filler words and add Studio Sound"

# Monitor network traffic for API discovery
descript monitor start
```

## Commands

### Authentication

```bash
# Login - prompts the official descript-api CLI to save an API key
descript auth login

# Check authentication status
descript auth status

# Official configuration commands are also available
descript config list
descript config get api-key
descript config validate
```

### Official Descript API CLI

The root command surface exposes the official `descript-api` commands:
if `descript-api` is not already on `PATH`, the wrapper installs
`@descript/platform-cli@latest` into the Descript CLI user data directory and
uses that binary.

```bash
descript import --name "My Project" --media "https://example.com/video.mp4"
descript agent --project-id <project-id> --prompt "Add Studio Sound"
descript job-status <job-id>
descript list-jobs --json
descript job-cancel <job-id>
descript list-projects --json
descript get-project <project-id> --json
descript list-folders --json
descript publish --project-id <project-id> --composition-id <composition-id>
descript export-transcript --project-id <project-id> --format markdown
descript update
```

Folder imports require `--team-access edit`, `--team-access comment`, or
`--team-access view`; the Descript API rejects folder imports without drive
member access.

### Projects

```bash
# List projects via the official Descript API CLI (JSON output)
descript projects list

# Limit results
descript projects list --limit 10

# Table format
descript projects list --table

# Filter by name
descript projects list --name Cursor

# Select specific fields
descript projects list -p "id,name"

# Get full project IDs for follow-up commands
descript projects list --name BrickBuddy --properties id,name

# Pipe to jq
descript projects list | jq '.[].name'
```

### Compositions

```bash
# List compositions from the official project summary
descript compositions list <project-id>
descript compositions list <project-id> --table

# Get a specific composition
descript compositions get <project-id> <composition-id>

# Filter compositions
descript compositions list <project-id> --filter "name:m1c1"

# Show full IDs for compositions currently visible in Descript
descript compositions active
descript compositions active --project-id <project-id>

# List media files from the official project summary
descript compositions assets <project-id>
descript compositions assets <project-id> --table

# Export a video asset as MP4
descript compositions export <project-id> <asset-id>
descript compositions export <project-id> <asset-id> -o ./output.mp4
descript compositions export <project-id> <asset-id> --fps 60 --width 3840 --height 2160

# Export a full composition through the Descript desktop app
# Requires two macOS privacy grants for the responsible host app of the
# calling process. From Claude desktop that is the embedded Claude Code runtime
# bundle (~/Library/Application Support/Claude/claude-code/<version>/claude.app),
# listed as lowercase "claude" — distinct from the capital-C "Claude" entry.
# From shells it is Terminal/iTerm. The grants:
# Accessibility (probed by the CLI, which fails fast before triggering the
# export) and Full Disk Access — both under System Settings > Privacy & Security.
# The CLI brings Descript frontmost before clicking Export (the native save
# sheet only appears when Descript is the frontmost app).
# If the project is not open, the CLI auto-opens it via the
# descript://project/<project-id> deep link and waits up to 60 seconds
# for the project page before proceeding.
# Local composition renders can take awhile; the CLI waits up to 30 minutes
# and verifies the exported file is nontrivial and stable before success.
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

Use JSON output when copying IDs into follow-up commands. Table output is for
visual inspection and can shorten long UUID cells when several columns are
shown.

## Options Reference

| Option | Short | Description | Commands |
|--------|-------|-------------|----------|
| `--table` | `-t` | Display as table | list, get, status |
| `--limit` | `-l` | Maximum results | list |
| `--filter` | `-f` | Filter results (field:value) | list |
| `--properties` | `-p` | Select fields (comma-separated) | list |
| `--folder` | | Folder path for a new project | import |
| `--team-access` | | Drive member access for folder imports (`edit`, `comment`, `view`) | import |
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
