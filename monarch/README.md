# Monarch CLI

A command-line interface for [Monarch Money](https://monarchmoney.com) personal finance.

## Installation

```bash
cd monarch
pip install -e .
```

## Quick Start

```bash
# Configure credentials
monarch auth login

# Check authentication status
monarch auth status

# List accounts
monarch accounts list

# List recent transactions
monarch transactions list --days 30
```

## Authentication

Monarch uses email/password authentication with optional MFA:

```bash
# Interactive login
monarch auth login

# Check status
monarch auth status

# Clear session
monarch auth logout

# Or configure via .env file:
USERNAME=your-email@example.com
PASSWORD=your-password
MFA_SECRET=your-totp-secret  # Optional
```

### Profiles

```bash
monarch auth profiles list                   # List all profiles
monarch auth profiles create staging         # Create a new profile
monarch auth profiles select staging    # Select active profile
monarch auth profiles get staging            # Get profile details
monarch auth profiles delete staging         # Delete a profile
```

## Commands

### Accounts
```bash
monarch accounts list                    # List all accounts
monarch accounts list            # Table format
monarch accounts get <id>                # Get account details
monarch accounts history <id>            # Balance history
monarch accounts holdings <id>           # Securities (brokerage)
monarch accounts sync                    # Trigger refresh
```

### Transactions
```bash
monarch transactions list                # List transactions
monarch transactions list --days 30      # Last 30 days
monarch transactions list --start 2024-01-01 --end 2024-01-31
monarch transactions list --account ACC_ID
monarch transactions list --filter "amount:gte:100"        # Filter by amount
monarch transactions list --filter "category:Groceries"    # Filter by category
monarch transactions list --filter "merchant:ilike:%amazon%"  # Search merchant
monarch transactions list --needs-review                   # Only "Needs Review" rows
monarch transactions list --reviewed                       # Only already-reviewed rows
monarch transactions get <id>            # Transaction details
monarch transactions recurring           # Recurring transactions
monarch transactions update <id> --merchant "Amazon"       # Assign merchant
monarch transactions update <id> --category CAT_ID         # Change category
monarch transactions update <id> --amount 50.00            # Update amount
monarch transactions update <id> --date 2024-01-15         # Change date
monarch transactions update <id> --notes "My note"         # Add notes
monarch transactions update <id> --notes ""                # Clear notes
monarch transactions update <id> --goal GOAL_ID            # Assign goal
monarch transactions update <id> --hide-from-reports       # Hide from reports
monarch transactions update <id> --needs-review            # Mark needs review
```

#### Transaction Filtering

Use `--filter` with `field:op:value` syntax:

| Operator | Meaning | Example |
|----------|---------|---------|
| `eq` | Equals (default) | `category:Groceries` |
| `ne` | Not equals | `category:ne:Transfers` |
| `gt` | Greater than | `amount:gt:100` |
| `gte` | Greater or equal | `amount:gte:50` |
| `lt` | Less than | `amount:lt:-100` |
| `lte` | Less or equal | `amount:lte:-50` |
| `in` | In list | `category:in:Groceries\|Dining` |
| `like` | Contains (case-sensitive) | `merchant:like:%Amazon%` |
| `ilike` | Contains (case-insensitive) | `merchant:ilike:%amazon%` |
| `null` | Is null | `notes:null` |
| `notnull` | Is not null | `notes:notnull` |

Multiple conditions (AND): `--filter "amount:lt:-50,category:Shopping"`

### Budgets
```bash
monarch budgets list                     # List budgets
monarch budgets list --month 2024-01     # Specific month
```

### Categories & Tags
```bash
monarch categories list                  # All categories
monarch category-groups list             # List category groups
monarch category-groups get <id>         # Get category group details
monarch tags list                        # All tags
```

### Merchants
```bash
monarch merchants list                   # List all merchants (sorted by name)
monarch merchants list --filter "name:ilike:%amazon%"
monarch merchants get <id>               # Get merchant details
```

### Cashflow
```bash
monarch cashflow summary                 # Income/expense/savings
monarch cashflow list                    # Detailed by period
```

### Institutions
```bash
monarch institutions list                # Linked banks
```

### Transaction Rules
Full CRUD for Monarch transaction rules (automatic categorization, tagging, merchant
renaming, etc). Rules are matched against merchant text, amount, category, or account,
and apply one or more actions when a transaction matches.

```bash
monarch rules list --table               # List all rules
monarch rules get <rule-id>              # Get one rule's full detail
monarch rules create \
    --merchant contains:amazon \
    --set-category <category-id>         # Create: merchant->category rule
monarch rules create \
    --amount gt:1000 --expense \
    --set-category <category-id>         # Create: large-expense rule
monarch rules update <rule-id> \
    --set-category <new-category-id>     # Update fields you pass
monarch rules delete <rule-id> --force   # Delete a rule
```

Criterion forms:
- Merchant: `--merchant "operator:value"` (e.g., `contains:amazon`, `equals:Whole Foods`). Repeatable.
- Amount: `--amount "operator:value"` (e.g., `eq:115.32`, `gt:20`) or `--amount "between:lower:upper"`. Use `--expense` or `--income` to scope.
- Categories / accounts to filter on: `--category-id <id>` / `--account-id <id>`. Repeatable.

Action flags:
- `--set-category <category-id>` – assign category
- `--set-merchant <merchant-id>` – assign merchant
- `--add-tag <tag-id>` – add tag (repeatable)
- `--apply-to-existing` – also apply retroactively to existing transactions
- `--use-original-statement` – match merchant criteria against the original bank statement

## Output Formats

- **JSON** (default): For scripting and piping

## Environment Variables

| Variable | Description |
|----------|-------------|
| `USERNAME` | Monarch Money email |
| `PASSWORD` | Monarch Money password |
| `MFA_SECRET` | TOTP secret for automatic MFA |
| `ACTIVE` | Set to `true` for the active profile within its auth type |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication error |
| 130 | User interrupted |

## Requirements

- Python 3.9+
- monarchmoney>=0.1.15

## License

MIT

## Additional Commands

### Cache

```bash
monarch cache --help
```
