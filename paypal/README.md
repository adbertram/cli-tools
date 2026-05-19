# PayPal CLI

Command-line interface for PayPal using the REST API.

## Installation

```bash
cd ~/Dropbox/GitRepos/cli-tools/paypal
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

# Set default profile
paypal auth profiles set-default business

# Show default profile
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
```

### Table
```bash
paypal payouts get <id> -t
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

- typer[all] - CLI framework
- python-dotenv - Environment configuration
- requests - HTTP client for API calls

## Additional Commands

### Cache

```bash
paypal cache --help
```
