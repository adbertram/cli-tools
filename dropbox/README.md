# Dropbox CLI

## DESCRIPTION

The `dropbox` CLI provides a command-line interface for Dropbox API.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Installation

```bash
# Clone and install
cd dropbox
pip install -e .
```

After installation, the `dropbox` command will be available in your terminal.

## Quick Start

```bash
# List files in your Dropbox root
dropbox files ls

# List files with details
dropbox files ls -l /Documents

# Search for files
dropbox files search "report"

# Login to your account
dropbox auth login
```

## Commands

### Authentication

Authentication is required for Dropbox API operations. Create a Dropbox app first, then use the login command.

```bash
# Login (will prompt for app key)
dropbox auth login

# Login with app key
dropbox auth login --app-key YOUR_APP_KEY

# Check authentication status
dropbox auth status

# Check status as table
dropbox auth status

# Logout and clear credentials
dropbox auth logout
```

### Profiles

Manage multiple authentication profiles (e.g., personal vs work accounts).

```bash
# List all profiles
dropbox auth profiles list

# Create a new profile
dropbox auth profiles create work

# Select active profile
dropbox auth profiles select work

# Delete a profile
dropbox auth profiles delete work --force
```

### Files

Manage files and folders in your Dropbox.

```bash
# List files in root
dropbox files ls

# List files in a folder
dropbox files ls /Documents

# List with details (size, modified date)
dropbox files ls -l /Documents

# List recursively
dropbox files ls -R /Projects

# Include deleted files
dropbox files ls --deleted /Archive

# Get file information
dropbox files info /Documents/report.pdf

# Search for files
dropbox files search "report"
dropbox files search "*.pdf" --path /Documents
dropbox files search "project" --max 50

# Download a file
dropbox files get /Documents/report.pdf
dropbox files get /Documents/report.pdf ./local/report.pdf

# Upload a file
dropbox files put ./report.pdf /Documents/report.pdf
dropbox files put ./report.pdf /Documents/
dropbox files put ./report.pdf /Documents/ --overwrite

# Create a folder
dropbox files mkdir /Projects/NewProject

# Delete a file or folder
dropbox files rm /Documents/old-file.txt
dropbox files rm /Temp --force
dropbox files rm /Temp --force --timeout 120

# Move a file or folder
dropbox files mv /Documents/report.pdf /Archive/report.pdf

# Copy a file or folder
dropbox files cp /Projects/template /Projects/new-project
```

### Version History

View and restore previous versions of files.

```bash
# Show version history for a file
dropbox files history /Documents/report.pdf
dropbox files history /Documents/report.pdf --limit 20
dropbox files history /Documents/report.pdf

# Restore a file to a previous version
dropbox files history /Documents/report.pdf  # Get revision ID first
dropbox files restore /Documents/report.pdf --rev abc123def456
dropbox files restore /Documents/report.pdf -r abc123def456 --force
```

### Account

View account information and storage usage.

```bash
# Display account info
dropbox account info
dropbox account info

# Display storage usage
dropbox account usage
dropbox account usage
```

### Desktop Sync

Inspect the local Dropbox desktop sync queue. This reads the local desktop
`nucleus.sqlite3` database in read-only mode and does not require Dropbox API
authentication.

```bash
# Show pending desktop sync queue items
dropbox sync pending

# Show table output
dropbox sync pending --table

# Read a specific desktop DB path
dropbox sync pending --db ~/.dropbox/instance1/sync/nucleus.sqlite3

# Disable heuristic filesystem path candidates
dropbox sync pending --no-resolve-paths
```

### Sharing

Work with shared links and folders.

```bash
# Get info about a shared link
dropbox sharing info "https://www.dropbox.com/scl/fo/..."
dropbox sharing info "https://www.dropbox.com/scl/fo/..."

# List contents of a shared folder
dropbox sharing ls "https://www.dropbox.com/scl/fo/..."
dropbox sharing ls "https://www.dropbox.com/scl/fo/..."
dropbox sharing ls "https://www.dropbox.com/scl/fo/..." --path /subfolder -l

# Download all contents of a shared folder
dropbox sharing download "https://www.dropbox.com/scl/fo/..."
dropbox sharing download "https://www.dropbox.com/scl/fo/..." ./downloads
dropbox sharing download "https://www.dropbox.com/scl/fo/..." --path /subfolder
dropbox sharing download "https://www.dropbox.com/scl/fo/..." --quiet
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping

### JSON Output Example

```bash
dropbox files ls /Documents
```

```json
[
  {
    "name": "report.pdf",
    "path_lower": "/documents/report.pdf",
    "path_display": "/Documents/report.pdf",
    "type": "file",
    "id": "id:abc123",
    "size": 1048576,
    "server_modified": "2025-01-15 10:30:00"
  }
]
```

### Table Output Example

```bash
dropbox files ls -l /Documents
```

```
T  Name         Size      Modified
--  -----------  --------  -------------------
F  report.pdf   1.0 MB    2025-01-15 10:30:00
F  notes.txt    4.2 KB    2025-01-14 09:00:00
D  Archive      -         -
```

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--long` | `-l` | Show detailed file information (ls only) |
| `--recursive` | `-R` | List files recursively |
| `--deleted` | `-d` | Include deleted files |
| `--overwrite` | `-o` | Overwrite existing file on upload |
| `--force` | `-f` | Skip confirmation prompts |
| `--path` | `-p` | Path to search within |
| `--max` | `-m` | Maximum search results |
| `--app-key` | `-k` | Dropbox app key for login |
| `--app-secret` | `-s` | Dropbox app secret for login |
| `--quiet` | `-q` | Suppress progress output |
| `--version` | `-v` | Show version and exit |

## Configuration

Before first use, you need to create a Dropbox app:

1. Go to https://www.dropbox.com/developers/apps
2. Click "Create app"
3. Choose "Scoped access" and "Full Dropbox" access type
4. Name your app and create it
5. Copy the App key (and optionally App secret)

Authentication profile files live under `~/.local/share/cli-tools/dropbox/authentication_profiles/<profile>/`; non-auth defaults live in `~/.local/share/cli-tools/dropbox/.env`:

```bash
# App credentials (required)
CLIENT_ID=your_app_key
CLIENT_SECRET=your_app_secret

# OAuth tokens (managed automatically after login)
ACCESS_TOKEN=<access_token>
REFRESH_TOKEN=<refresh_token>
TOKEN_EXPIRES_AT=<timestamp>

# Account info (populated automatically after login)
ACCOUNT_ID=<account_id>
```

You can also set these as environment variables directly.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### List Files with Details

```bash
dropbox files ls -l /Documents
```

### Download Multiple Files

```bash
# Download all PDFs from a folder
dropbox files search "*.pdf" --path /Documents | jq -r '.[].path_display' | xargs -I {} dropbox files get {}
```

### Upload with Overwrite

```bash
dropbox files put ./updated-report.pdf /Documents/report.pdf --overwrite
```

### Check Storage Usage

```bash
dropbox account usage
```

### Script-Friendly JSON Output

```bash
# Get all file paths
dropbox files ls /Documents | jq -r '.[].path_display'

# Get total size of files
dropbox files ls -l /Documents | jq '[.[] | select(.type == "file") | .size] | add'

# Find large files
dropbox files search "*" | jq '.[] | select(.size > 10000000) | {name, size, path: .path_display}'
```

## Requirements

- Python 3.9+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - dropbox

## License

MIT

## Additional Commands

### Cache

```bash
dropbox cache --help
```
