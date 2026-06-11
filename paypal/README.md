# PayPal CLI

## DESCRIPTION

The `paypal` CLI provides a command-line interface for PayPal API.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Installation

```bash
cd <cli-tools-root>/paypal
python3 -m venv venv
source venv/bin/activate
pip install -e .
```

## Quick Start

```bash
# Configure API credentials in .env
cp .env.example .env
# Edit .env with your PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET

# Login (obtains OAuth token)
paypal auth login

# Check authentication status
paypal auth status -t

# List transaction-reporting records for a date range
paypal transactions list --start-date 2026-05-01 --end-date 2026-05-31

# Create a batch payout
paypal payouts create '[{"recipient": "user@example.com", "amount": "10.00"}]'
```

## Commands

### Authentication (`paypal auth`)

```bash
# API login (obtains OAuth token)
paypal auth login

# Check authentication status
paypal auth status
paypal auth status -t

# Logout (clear saved tokens)
paypal auth logout
```

### Profiles (`paypal auth profiles`)

```bash
# List all profiles
paypal auth profiles list -t

# Select active profile
paypal auth profiles select business

# Show active profile
paypal auth profiles get default
```

### Payouts (`paypal payouts`)

```bash
# Create a batch payout
paypal payouts create '[{"recipient": "user@example.com", "amount": "10.00"}]'

# Get payout status
paypal payouts get <payout_batch_id>

# Get payout item details
paypal payouts get-item <payout_item_id>

# Cancel unclaimed payout
paypal payouts cancel <payout_item_id>
```

### Transactions (`paypal transactions`)

```bash
# List business-account transactions for a date range
paypal transactions list --start-date 2026-05-01 --end-date 2026-05-31

# Table output
paypal transactions list --start-date 2026-05-01 --end-date 2026-05-31 --table

# Search for a transaction ID within a date range
paypal transactions get TXN12345678901234 --start-date 2026-05-01 --end-date 2026-05-31

# Long ranges are chunked into 31-day API windows automatically
paypal transactions list --start-date 2026-04-01 --end-date 2026-05-31 --limit 100

# Select only specific fields in JSON output
paypal transactions list \
  --start-date 2026-05-01 \
  --end-date 2026-05-31 \
  --properties transaction_info.transaction_id,transaction_info.transaction_initiation_date,transaction_info.transaction_amount.value

# Include non-balance-affecting records
paypal transactions list --start-date 2026-05-01 --end-date 2026-05-31 --all-records
```

Date handling:
- `YYYY-MM-DD` `--start-date` values are normalized to `T00:00:00Z`.
- `YYYY-MM-DD` `--end-date` values are normalized to `T23:59:59Z`.
- Datetimes with an offset are converted to UTC.
- Naive datetimes are interpreted as UTC.
- Date ranges longer than 31 days are split into consecutive 31-day windows before calling PayPal's Transaction Search API.

### Orders (`paypal orders`)

Not yet implemented via API.

### Labels (`paypal labels`)

Not yet implemented via API.

### Account (`paypal account`)

Not yet implemented via API.

## Output Formats

### JSON (default)
```bash
paypal payouts get <id>
paypal transactions list --start-date 2026-05-01 --end-date 2026-05-31
```

### Table
```bash
paypal payouts get <id> -t
paypal transactions list --start-date 2026-05-01 --end-date 2026-05-31 -t
```

## Configuration

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `PAYPAL_CLIENT_ID` | PayPal API client ID | |
| `PAYPAL_CLIENT_SECRET` | PayPal API client secret | |
| `PAYPAL_SANDBOX` | Use sandbox environment | `false` |

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | General error |
| `2` | Authentication/credentials error |
| `130` | Interrupted (Ctrl+C) |

## Requirements

- Python 3.9+
- PayPal API credentials (client ID and secret)

## Dependencies

- typer - CLI framework
- python-dotenv - Environment configuration
- requests - HTTP client for API calls

## Additional Commands

### Cache

```bash
paypal cache --help
```
