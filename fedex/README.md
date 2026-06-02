# Fedex CLI

A command-line interface for the [FedEx Pickup API](https://developer.fedex.com/api/en-us/catalog/pickup/v1/docs.html). Schedule, check availability, and cancel FedEx pickups.

## Installation

```bash
cd fedex
./install.sh
```

After installation, the `fedex` command will be available in your terminal.

## Quick Start

```bash
# Authenticate with FedEx OAuth credentials
fedex auth login

# Check pickup availability
fedex pickup availability

# Schedule a pickup
fedex pickup schedule --account 123456789

# Cancel a pickup
fedex pickup cancel ABC123 --account 123456789 --date 2024-01-15
```

## Commands

### Authentication

```bash
# Login with OAuth client credentials
fedex auth login
fedex auth login --profile work

# Check authentication status
fedex auth status
fedex auth status --table

# Test API connection
fedex auth test

# Refresh OAuth token
fedex auth refresh

# Clear stored credentials
fedex auth logout
```

### Pickup

```bash
# Check pickup availability (uses defaults from .env)
fedex pickup availability
fedex pickup availability --carrier FDXG
fedex pickup availability --street "123 Main St" --city "Columbus" --state OH --postal 43215

# Schedule a pickup
fedex pickup schedule --account 123456789
fedex pickup schedule -a 123456789 --packages 2 --weight 10.5
fedex pickup schedule -a 123456789 --carrier FDXG --residential

# Cancel a pickup
fedex pickup cancel ABC123 --account 123456789 --date 2024-01-15
fedex pickup cancel ABC123 -a 123456789 -d 2024-01-15 --carrier FDXG
```

### Profiles

```bash
# List all profiles
fedex auth profiles list

# Create a new profile
fedex auth profiles create work

# Select active profile
fedex auth profiles select work

# Delete a profile
fedex auth profiles delete old-profile
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping
- **Table** (`--table`/`-t`): Human-readable table format

```bash
# JSON output (default)
fedex pickup availability

# Table output
fedex pickup availability --table
```

## Configuration

Authentication profile files live under `~/.local/share/cli-tools/fedex/authentication_profiles/<profile>/`; non-auth defaults live in `~/.local/share/cli-tools/fedex/.env`:

```bash
# OAuth Credentials
CLIENT_ID=your_client_id
CLIENT_SECRET=your_client_secret

# OAuth tokens (managed automatically after login)
ACCESS_TOKEN=
REFRESH_TOKEN=
TOKEN_EXPIRES_AT=

# API Base URL (optional - defaults to production)
BASE_URL=https://apis.fedex.com

# Default pickup address
DEFAULT_STREET=123 Main St
DEFAULT_CITY=Columbus
DEFAULT_STATE=OH
DEFAULT_POSTAL=43215
DEFAULT_RESIDENTIAL=false
DEFAULT_CARRIER=FDXE
DEFAULT_ACCOUNT=123456789
DEFAULT_PACKAGE_LOCATION=FRONT
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Requirements

- Python 3.9+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests
  - pydantic
  - cli-tools-shared

## License

MIT

## Cache

```bash
fedex cache status
fedex cache clear
```
