# Progress ServiceNow CLI

A command-line interface for the [Progress ServiceNow Employee Center](https://progress1.service-now.com/esc) using browser automation. Manage tickets, view requests, and browse the service catalog.

## Installation

```bash
cd ~/Dropbox/GitRepos/cli-tools/progress-servicenow
./install.sh
```

Or manually:

```bash
pip install -e .
playwright install chromium
```

## Quick Start

```bash
# Login (opens browser for SSO authentication)
progress-servicenow auth login

# Check login status
progress-servicenow auth status

# List your open watchlist tickets
progress-servicenow ticket list --table

# Get ticket details
progress-servicenow ticket get RITM0352332

# Browse the IT catalog
progress-servicenow catalog list --category it --table
```

## Commands

### Authentication (`auth`)

```bash
# Interactive login (opens browser, auto-monitors for auth)
progress-servicenow auth login

# Force re-authentication
progress-servicenow auth login --force

# Check authentication status
progress-servicenow auth status

# Test authentication against live browser
progress-servicenow auth test

# Clear stored session
progress-servicenow auth logout
```

### Tickets (`ticket`)

#### List tickets

```bash
# List watchlist open tickets (default view)
progress-servicenow ticket list

# List with table output
progress-servicenow ticket list --table

# Different views
progress-servicenow ticket list --view open
progress-servicenow ticket list --view closed
progress-servicenow ticket list --view watchlist-open
progress-servicenow ticket list --view watchlist-closed

# Limit results
progress-servicenow ticket list --limit 10

# Filter results
progress-servicenow ticket list --filter "state:eq:Open"

# Select specific fields
progress-servicenow ticket list --properties "number,description,state"
```

#### Get ticket details

```bash
# By RITM number
progress-servicenow ticket get RITM0352332

# By sys_id
progress-servicenow ticket get abc123def456789012345678abcdef01

# Table format
progress-servicenow ticket get RITM0352332 --table

# Include comments/activity
progress-servicenow ticket get RITM0352332 --comments

# Select specific fields
progress-servicenow ticket get RITM0352332 --properties "number,state,assigned_to"
```

#### Post a comment

```bash
progress-servicenow ticket comment RITM0352332 "Please update the status"
```

#### Close a ticket

```bash
progress-servicenow ticket close RITM0352332
```

#### Create a ticket (manual)

```bash
# Opens a headed browser at the ServiceNow home page
progress-servicenow ticket create
```

### Catalog (`catalog`)

#### List catalog items

```bash
# List all catalog items from the home page
progress-servicenow catalog list

# Filter by category
progress-servicenow catalog list --category it
progress-servicenow catalog list --category business-operations
progress-servicenow catalog list --category workplace-operations

# Table format
progress-servicenow catalog list --category it --table

# Filter results
progress-servicenow catalog list --filter "type:eq:Request"

# Select specific fields
progress-servicenow catalog list --properties "name,type,sys_id"
```

#### Get catalog item details

```bash
# By sys_id
progress-servicenow catalog get abc123def456789012345678abcdef01

# Table format
progress-servicenow catalog get abc123... --table

# Select specific fields
progress-servicenow catalog get abc123... --properties "name,type,description"
```

#### Search the catalog

```bash
# Search for items
progress-servicenow catalog search "application access"

# Table format
progress-servicenow catalog search "vpn" --table

# Limit results
progress-servicenow catalog search "password" --limit 5

# Select specific fields
progress-servicenow catalog search "hardware" --properties "name,type"
```

### Profiles (`progress-servicenow auth profiles`)

Manage multiple configuration profiles (e.g., different ServiceNow instances or accounts).

```bash
# List all profiles
progress-servicenow auth profiles list

# Show default profile
progress-servicenow auth profiles get default

# Create a new profile
progress-servicenow auth profiles create myprofile

# Switch default profile
progress-servicenow auth profiles set-default myprofile

# Delete a profile
progress-servicenow auth profiles delete myprofile
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping
- **Table** (`--table`): Human-readable Rich table output

```bash
# JSON output (pipe to jq)
progress-servicenow ticket list | jq '.[].number'

# Table output
progress-servicenow ticket list --table
```

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display as Rich table |
| `--limit` | `-l` | Maximum number of results (default: 100) |
| `--filter` | `-f` | Client-side filter (field:op:value) |
| `--properties` | `-p` | Comma-separated fields to include |
| `--view` | `-V` | Ticket list view (open, closed, watchlist-open, watchlist-closed) |
| `--category` | `-C` | Catalog category filter |
| `--comments` | `-c` | Include comments in ticket detail |
| `--version` | `-v` | Show version and exit |

## Configuration

Configuration is stored in `.env`:

```bash
# Base URL
BASE_URL=https://progress1.service-now.com/esc

# Browser settings (true = headless, false = visible)
HEADLESS=true

# Auth cookie patterns
AUTH_COOKIE_NAMES=session.*,auth,token,sid

# Cache settings
CACHE_ENABLED=true
CACHE_TTL=3600
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Architecture

This CLI uses the `playwright` CLI tool for browser automation with a persistent named session (`progress-servicenow`). The browser runs headless by default and maintains session cookies across commands.

### Key URLs

| Page | URL Pattern |
|------|-------------|
| Home | `?id=ec_pro_home` |
| My Requests | `?id=my_requests` |
| Ticket Detail | `?id=ticket&table=sc_req_item&sys_id=<sys_id>` |
| Catalog Item | `?id=sc_cat_item&sys_id=<sys_id>` |
| Category | `?id=emp_taxonomy_topic&topic_id=<topic_id>` |

### File Structure

```
progress_servicenow_cli/
├── __init__.py          # Package init, version
├── main.py              # Typer app, command registration
├── config.py            # Config (session name, URLs)
├── client.py            # Browser automation client
├── parsers.py           # Snapshot YAML parsers
├── models/
│   ├── __init__.py      # Model exports
│   ├── base.py          # CLIModel base class
│   ├── item.py          # Generic item models (scaffolded)
│   └── ticket.py        # Ticket, TicketDetail, Comment, CatalogItem
└── commands/
    ├── __init__.py
    ├── tickets.py       # ticket list|get|comment|close|create
    └── catalog.py       # catalog list|search
```

## Debugging

```bash
# Run with visible browser
export HEADLESS=false
progress-servicenow ticket list

# Clear cache
progress-servicenow cache clear
```

## Requirements

- Python 3.9+
- playwright CLI (`brew install playwright` or pip)
- Dependencies (installed automatically): typer, python-dotenv, pydantic, cli-tools-shared
