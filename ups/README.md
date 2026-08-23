# UPS CLI

## DESCRIPTION

The `ups` CLI provides a command-line interface for the UPS Pickup API. Use it to authenticate with UPS OAuth client credentials, schedule package pickups, and inspect pending pickup status from agents, automation, or terminal workflows.

## Docs

- API documentation: https://github.com/UPS-API/api-documentation/blob/main/Pickup.yaml
- UPS Pickup docs: https://developer.ups.com/tag/Pickup?loc=en_US
- Production API base URL: https://onlinetools.ups.com/api

## Installation

```bash
cd <cli-tools-root>/ups
uv tool install -e . --force --refresh
```

After installation, the `ups` command is available globally.

## Quick Start

```bash
# Authenticate with UPS Developer Portal OAuth credentials
ups auth login

# Preview the request without scheduling
ups pickup schedule --dry-run

# Schedule the next pickup using configured defaults
ups pickup schedule

# List pending pickups
ups pickup list --table
```

## Commands

### Authentication (`ups auth`)

```bash
# Configure Client ID and Client Secret, then request an access token
ups auth login

# Force a new access token while preserving Client ID and Client Secret
ups auth login --force

# Check authentication with a live UPS OAuth token request
ups auth status
ups auth status --table

# Clear saved credentials and runtime auth state
ups auth logout
```

Reusable Client ID and Client Secret values are stored through the CLI-tools secret manager by the shared auth layer. Do not place reusable credentials in `.env` files.

### Profiles (`ups auth profiles`)

```bash
ups auth profiles list
ups auth profiles get default
ups auth profiles select PROFILE_NAME
ups auth profiles create PROFILE_NAME
ups auth profiles delete PROFILE_NAME
```

### Pickup (`ups pickup`)

```bash
# Schedule using configured defaults
ups pickup schedule

# Preview the exact UPS API request without authentication or mutation
ups pickup schedule --dry-run

# Override package count, weight, and ready window
ups pickup schedule --packages 3 --weight 8.5 --ready-time 15:30 --close-time 18:00

# Schedule for a specific date
ups pickup schedule --date 2026-07-03

# Provide address/account values explicitly instead of using config defaults
ups pickup schedule \
  --account 123456 \
  --company "Geek Life" \
  --contact "Adam" \
  --street "123 Main St" \
  --city "Austin" \
  --state TX \
  --postal 78701 \
  --phone 5555555555

# List pending pickups for the configured account
ups pickup list
ups pickup list --table

# Filter or restrict fields
ups pickup list --filter "status_message:ilike:%processing%" --properties "prn,service_date,status_message"

# Get one pending pickup by PRN
ups pickup get 2930O2BER9R --table
```

`ups pickup schedule` uses `POST /pickupcreation/{version}/pickup`. `ups pickup list` and `ups pickup get` use pending pickup status from `GET /shipments/{version}/pickup/{pickuptype}`.

## Output Formats

- JSON is the default output format.
- Add `--table` / `-t` for human-readable table output.

### JSON Output Example

```bash
ups pickup schedule --dry-run
```

```json
{
  "dry_run": true,
  "method": "POST",
  "endpoint": "/pickupcreation/v2409/pickup",
  "payload": {
    "PickupCreationRequest": {
      "RatePickupIndicator": "N"
    }
  }
}
```

### Table Output Example

```bash
ups pickup list --table
```

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display data as a table |
| `--limit` | `-l` | Maximum rows for `pickup list` |
| `--filter` | `-f` | Filter list results using `field:op:value` syntax |
| `--properties` | `-p` | Restrict output to selected fields |
| `--account` | `-a` | UPS account number |
| `--date` | `-d` | Pickup date, `YYYY-MM-DD` or `YYYYMMDD` |
| `--packages` | `-n` | Number of packages |
| `--weight` | `-w` | Total shipment weight |
| `--dry-run` |  | Print the pickup request without scheduling |
| `--version` | `-v` | Show CLI version and exit |
| `--no-cache` |  | Bypass cached read responses |

## Configuration

Non-authentication configuration lives in `~/.local/share/cli-tools/ups/.env`. CLI-managed runtime auth state lives in `~/.local/share/cli-tools/ups/authentication_profiles/<profile>/.env`. The source repo only carries `.env.example`.

Root config variables:

```bash
BASE_URL=https://onlinetools.ups.com/api
TOKEN_BASE_URL=https://onlinetools.ups.com
UPS_API_VERSION=v2409
UPS_TRANSACTION_SRC=cli-tools

UPS_ACCOUNT_NUMBER=
UPS_ACCOUNT_COUNTRY=US
UPS_DEFAULT_COMPANY=Geek Life
UPS_DEFAULT_CONTACT=Adam
UPS_DEFAULT_STREET=
UPS_DEFAULT_CITY=
UPS_DEFAULT_STATE=
UPS_DEFAULT_POSTAL=
UPS_DEFAULT_COUNTRY=US
UPS_DEFAULT_PHONE=
UPS_DEFAULT_RESIDENTIAL=false
UPS_DEFAULT_PICKUP_POINT=FRONT
UPS_DEFAULT_SERVICE_CODE=003
UPS_DEFAULT_CONTAINER_CODE=01
UPS_DEFAULT_DESTINATION_COUNTRY=US
UPS_DEFAULT_PAYMENT_METHOD=01
UPS_DEFAULT_WEIGHT=1
UPS_DEFAULT_WEIGHT_UNIT=LBS
```

Authentication profile variables are written by the CLI:

```bash
ACTIVE=true
CLIENT_ID=secret://ups-client-id
CLIENT_SECRET=secret://ups-client-secret
ACCESS_TOKEN=secret://ups-access-token
TOKEN_EXPIRES_AT=1780000000.0
```

Reusable raw credentials belong in the CLI-tools secret manager, not in `.env` files.

## Cache

```bash
ups cache clear
ups --no-cache pickup list
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Client/config/authentication error |
| 130 | User interrupted |

## Examples

### Schedule the Next Pickup

```bash
ups pickup schedule --packages 4 --weight 12 --special-instruction "Packages at front door"
```

### Export Pending Pickups

```bash
ups pickup list --properties "prn,service_date,status_message" > pending-ups-pickups.json
```

## Output Contract

Schedule commands preserve all fields returned by UPS under `PickupCreationResponse` and add convenience fields such as `prn`, `status_code`, `status_description`, and `rate_status_description`.

Pending pickup commands preserve each UPS `PendingStatus` record and add convenience fields such as `prn`, `service_date`, `status_message`, `pickup_type`, `contact_name`, and `reference_number`.

## Requirements

- Python 3.11+
- Dependencies installed automatically:
  - typer
  - python-dotenv
  - requests
  - cli-tools-shared

## License

MIT
