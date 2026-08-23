# PayPal CLI

## DESCRIPTION

The `paypal` CLI provides a command-line interface for PayPal API.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Installation

```bash
uv tool install -e <cli-tools-root>/paypal --force --refresh
```

## Testing

```bash
uv run --project <cli-tools-root>/paypal --with pytest python -m pytest <cli-tools-root>/paypal/tests
```

## Quick Start

```bash
# Login (obtains OAuth token)
paypal auth login

# Refresh browser-backed BrickLink refund matching
paypal auth login -c browser_session --force

# Check authentication status
paypal auth status -t

# List transaction-reporting records for a date range
paypal transactions list --start-date 2026-05-01 --end-date 2026-05-31

# Create a batch payout
paypal payouts create '[{"recipient": "user@example.com", "amount": "10.00"}]'

# Preview a BrickLink-assisted partial refund without issuing it
paypal refunds from-bricklink 12345678 --amount 4.50 --details "Missing part refund" --dry-run
```

## Commands

### Authentication (`paypal auth`)

```bash
# API login (obtains OAuth token)
paypal auth login

# Browser-session login for unified transactions/refunds
paypal auth login -c browser_session --force

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

### Refunds (`paypal refunds`)

```bash
# Preview a full refund for a PayPal capture
paypal refunds create <capture_id> --dry-run

# Issue a full refund for a PayPal capture
paypal refunds create <capture_id> --yes

# Preview a partial refund
paypal refunds create <capture_id> --amount 4.50 --currency USD --note-to-payer "Missing part refund" --dry-run

# Issue a partial refund using BrickLink order context and PayPal unified transactions
paypal refunds from-bricklink 12345678 --amount 4.50 --details "Missing part refund" --yes

# Use verified BrickLink order JSON when live BrickLink lookup is blocked
paypal refunds from-bricklink 12345678 --order-json order-context.json --amount 4.50 --dry-run
```

Refund safeguards:
- Omit `--amount` for a full refund.
- Use `--dry-run` to print the exact request without calling PayPal.
- Live refunds require `--yes`; without `--yes` or `--dry-run`, the command refuses to run.
- `create` refunds a known PayPal capture through the official PayPal API and requires OAuth credentials.
- `from-bricklink` reads `bricklink order get <order-id>` unless `--order-json` points to a verified BrickLink order JSON file, searches PayPal unified transactions by buyer email/name/date/amount, verifies refundability through PayPal refund details, and requires a saved browser session.
- Refund calls use `PayPal-Request-Id` idempotency keys. Direct refunds can override it with `--idempotency-key`.
- Do not manually issue refunds through PayPal's web refund sheet or use `playwright-cli fill` on PayPal refund amount fields. The web currency input is masked and can preserve or transform existing digits even when automation reports a successful fill. Use `paypal refunds from-bricklink`, which posts the verified refund payload directly through the authenticated PayPal page instead of filling that field.

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

Run `paypal auth login` to configure PayPal API credentials through the CLI-tools auth flow. Run `paypal auth login -c browser_session --force` to refresh the browser session for unified transactions. In Codex, launch browser-session auth with a PTY-backed `exec_command` session (`tty: true`) and send the final Enter with `write_stdin`; do not drive Terminal.app with Computer Use for this prompt. Reusable credentials are owned by the CLI-tools secret manager; do not place client secrets in a source-tree `.env`.

### Config Diagnostics

When inspecting PayPal profile paths from Python, use the installed `paypal` launcher interpreter and the `BaseConfig` methods that actually exist:

```bash
launcher="$(command -v paypal)"
interpreter="$(head -1 "$launcher" | sed 's/^#!//')"
"$interpreter" - <<'PY'
from paypal_cli.config import get_config

config = get_config(profile="default")
print(config.get_profiles_dir())
print(config.get_profile_data_dir())
print(config.storage_dir)
PY
```

Use `get_profiles_dir()` for the authentication profiles root and `get_profile_data_dir()` or `storage_dir` for the active profile. Pass the profile explicitly in direct Python probes. There is no singular `get_profile_dir()` method.

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `CLIENT_ID` | PayPal API client ID stored by auth flow | |
| `CLIENT_SECRET` | PayPal API client secret stored by auth flow | |
| `BASE_URL` | PayPal API base URL | `https://api-m.paypal.com` |

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | General error |
| `2` | Authentication/credentials error |
| `130` | Interrupted (Ctrl+C) |

## Requirements

- Python 3.9+
- PayPal API credentials (client ID and secret) for direct capture refunds and payouts
- PayPal browser session for BrickLink-assisted refunds

## Dependencies

- typer - CLI framework
- python-dotenv - Environment configuration
- requests - HTTP client for API calls

## Additional Commands

### Cache

```bash
paypal cache --help
```
