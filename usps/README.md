# USPS CLI

## DESCRIPTION

The `usps` CLI provides a command-line interface for Usps API.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Installation

```bash
cd usps
pip install -e .
```

After installation, the `usps` command will be available in your terminal.

## Quick Start

```bash
# Authenticate with USPS
usps auth login

# Get tracking info for a package
usps tracking get 9400111899223456789012

# Get tracking for multiple packages
usps tracking list 9400111899223456789012 9400111899223456789013
```

## Commands

### Authentication

```bash
# Login with OAuth credentials
usps auth login
usps auth login --client-id YOUR_ID --client-secret YOUR_SECRET

# Force re-authentication (clears existing credentials)
usps auth login --force

# Check authentication status
usps auth status
usps auth status --table

# Clear stored credentials
usps auth logout
```

### Tracking

```bash
# Get tracking info for a single package (JSON output)
usps tracking get 9400111899223456789012

# Get tracking info with table format
usps tracking get 9400111899223456789012 --table

# Get tracking for multiple packages
usps tracking list 9400111899223456789012 9400111899223456789013

# Read tracking numbers from stdin
echo "9400111899223456789012" | usps tracking list

# Filter results by status
usps tracking list 9400111899223456789012 9400111899223456789013 --filter "status:eq:Delivered"

# Limit results
usps tracking list 9400111899223456789012 9400111899223456789013 --limit 5

# Select specific fields
usps tracking list 9400111899223456789012 --properties "tracking_number,status,expected_delivery"

# Table output for multiple packages
usps tracking list 9400111899223456789012 9400111899223456789013 --table
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping
- **Table** (`--table`/`-t`): Human-readable table format

### JSON Output Example

```bash
usps tracking get 9400111899223456789012
```

```json
{
  "tracking_number": "9400111899223456789012",
  "status": "Delivered",
  "status_category": "Delivered",
  "status_summary": "Your item was delivered...",
  "mail_class": "USPS Ground Advantage",
  "origin": {
    "city": "SEATTLE",
    "state": "WA",
    "zip": "98101",
    "country": "US"
  },
  "destination": {
    "city": "NEW YORK",
    "state": "NY",
    "zip": "10001",
    "country": "US"
  },
  "expected_delivery": "2025-01-20",
  "events": [
    {
      "date": "2025-01-20",
      "time": "14:30:00",
      "city": "NEW YORK",
      "state": "NY",
      "status": "Delivered",
      "description": "Delivered, Front Door/Porch"
    }
  ]
}
```

### Table Output Example

```bash
usps tracking get 9400111899223456789012 --table
```

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display output as table |
| `--limit` | `-l` | Maximum number of results (default: 100) |
| `--filter` | `-f` | Filter: field:op:value (e.g., status:eq:Delivered) |
| `--properties` | `-p` | Comma-separated list of fields to include |
| `--force` | `-F` | Force re-authentication (auth login only) |
| `--version` | `-v` | Show version and exit |

### Filter Operators

| Operator | Description | Example |
|----------|-------------|---------|
| `eq` | Equals | `status:eq:Delivered` |
| `ne` | Not equals | `status:ne:In Transit` |
| `contains` | Contains text | `mail_class:contains:Ground` |

## Configuration

Authentication profile files live under `~/.local/share/cli-tools/usps/authentication_profiles/<profile>/`; non-auth defaults live in `~/.local/share/cli-tools/usps/.env`:

```bash
# OAuth credentials (required)
USPS_CLIENT_ID=your_client_id
USPS_CLIENT_SECRET=your_client_secret

# OAuth tokens (managed automatically after login)
USPS_ACCESS_TOKEN=<access_token>
USPS_TOKEN_EXPIRES_AT=<timestamp>
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### Get Tracking Status and Extract with jq

```bash
usps tracking get 9400111899223456789012 | jq '.status'
```

### Export Tracking Events

```bash
usps tracking get 9400111899223456789012 | jq '.events'
```

### Check Delivery Status for Multiple Packages

```bash
usps tracking list $(cat tracking_numbers.txt) --properties "tracking_number,status" --table
```

## Models

This CLI uses Pydantic models for type-safe data handling. All commands return strongly-typed models.

### Available Models

| Model | Description | Required Fields |
|-------|-------------|-----------------|
| `TrackingInfo` | Complete tracking information | `tracking_number`, `status` |
| `TrackingEvent` | Individual tracking event | `date`, `status` |
| `Address` | Origin/destination address | (all optional) |

### Model Fields

**TrackingInfo:**
- `tracking_number` (str): USPS tracking number
- `status` (str): Current status
- `status_category` (str): Status category
- `status_summary` (str): Status description
- `mail_class` (str): Mail class (e.g., "USPS Ground Advantage")
- `mail_type` (str): Package type
- `origin` (Address): Origin address
- `destination` (Address): Destination address
- `mailing_date` (str): Date mailed
- `expected_delivery` (str): Expected delivery date
- `delivery_window` (str): Delivery time window
- `services` (list): List of services
- `events` (list): List of tracking events

## Requirements

- Python 3.9+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests
  - pydantic

## License

MIT

## Additional Commands

### Cache

```bash
usps cache --help
```
