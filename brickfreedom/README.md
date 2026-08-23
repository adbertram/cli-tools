# Brickfreedom CLI

## DESCRIPTION

The `brickfreedom` CLI provides a command-line interface for Brickfreedom (browser automation).

Use it when you need repeatable access to brickfreedom workflows that are only available through a signed-in website.

## Installation

```bash
cd brickfreedom
pip install -e .

# Install Playwright browsers (required once)
playwright install chromium
```

After installation, the `brickfreedom` command will be available in your terminal.

## Quick Start

```bash
# Login to Brickfreedom
brickfreedom auth login

# Check login status
brickfreedom auth status

# List orders
brickfreedom order list

# List tasks
brickfreedom task list
```

## Commands

### Authentication (`brickfreedom auth`)

```bash
# Interactive login (opens browser)
brickfreedom auth login

# Force re-authentication
brickfreedom auth login --force

# Check authentication status
brickfreedom auth status
brickfreedom auth status

# Test authentication works against browser
brickfreedom auth test
brickfreedom auth test --verbose

# Clear stored session
brickfreedom auth logout
```

### Tasks (`brickfreedom task`)

Manage tasks from the "My Tasks" section on the dashboard.

```bash
# List all tasks
brickfreedom task list
brickfreedom task list

# Filter tasks
brickfreedom task list --filter completed:eq:false

# Create a new task
brickfreedom task create "Ship pending orders"

# Mark a task as complete by index (fragile for scripts -- index shifts when other tasks complete)
brickfreedom task complete 1

# Mark a task as complete by content match (preferred for scripts / agents)
# Re-resolves the current task index right before completing, so prior list-shifting
# completions cannot mark the wrong task. Fails fast with non-zero exit + JSON error
# if zero matches OR multiple matches.
brickfreedom task complete \
    --match-platform bricklink \
    --match-order-id 30823995 \
    --match-item-number 75270-1
# Add --match-quantity to disambiguate when multiple rows match.

# Mark all tasks as complete
brickfreedom task complete --bulk

# Show raw task rows that did not match any known missing-part format
# (useful when the dashboard ships a new task text shape)
brickfreedom task list --type missing-part --debug-unparsed

# Delete a completed task (by index)
brickfreedom task delete 1

# Delete all completed tasks
brickfreedom task delete --completed
```

#### Customer Replacement Part Tasks

Create and manage structured replacement part tasks with the `customer-replacement-part` type. These tasks have a standardized format that can be parsed and filtered.

**Creating a replacement part task:**

```bash
brickfreedom task create --type customer-replacement-part \
    --customer-name "John Doe" \
    --order-id "30176576" \
    --item-no "3024" \
    --item-name "Plate 1 x 1" \
    --color "Light Bluish Gray" \
    --qty 10 \
    --location "I-BB001"
```

**Required options:**
| Option | Description |
|--------|-------------|
| `--customer-name` | Customer name |
| `--order-id` | Marketplace order ID |
| `--item-no` | Part/item number |
| `--item-name` | Part/item name |
| `--color` | Color name |

**Optional:**
| Option | Default | Description |
|--------|---------|-------------|
| `--qty` | 1 | Quantity |
| `--location` | - | Bin location |

**Task format:**
```
[REPLACEMENT] Customer: John Doe | Order: 30176576 | Part: 3024 Plate 1 x 1 | Color: Light Bluish Gray | Qty: 10 | Loc: I-BB001
```

**Filtering replacement part tasks:**

```bash
# List all replacement part tasks (returns parsed JSON)
brickfreedom task list --type customer-replacement-part

# Filter by order ID
brickfreedom task list --type customer-replacement-part --order-id 30176576

# Display as table
brickfreedom task list --type customer-replacement-part
```

**Example JSON output:**
```json
{
  "tasks": [
    {
      "index": 1,
      "completed": false,
      "customerName": "John Doe",
      "orderId": "30176576",
      "itemNo": "3024",
      "itemName": "Plate 1 x 1",
      "color": "Light Bluish Gray",
      "qty": 10,
      "location": "I-BB001",
      "rawText": "[REPLACEMENT] Customer: John Doe | Order: 30176576 | Part: 3024 Plate 1 x 1 | Color: Light Bluish Gray | Qty: 10 | Loc: I-BB001"
    }
  ],
  "count": 1
}
```

### Orders (`brickfreedom order`)

Manage orders from the Brickfreedom orders page.

```bash
# List all orders
brickfreedom order list
brickfreedom order list

# Filter orders by status
brickfreedom order list --status PAID
brickfreedom order list --status PACKED

# Filter by platform
brickfreedom order list --platform bricklink
brickfreedom order list --platform brickowl

# Filter by picked status
brickfreedom order list --picked true
brickfreedom order list --picked false

# Combine filters
brickfreedom order list --status PAID --platform bricklink

# Get a specific order
brickfreedom order get 30070421
brickfreedom order get 30070421

# List processed orders (ready for shipping)
brickfreedom order processed
brickfreedom order processed

# Mark orders as processed
brickfreedom order process 30070421
brickfreedom order process 30070421 30070422 30070423

# Set tracking number for an order
brickfreedom order tracking 30070421 9400111899223847012345

# Post orders (mark as shipped)
brickfreedom order post 30070421
brickfreedom order post 30070421 30070422
```

### Profiles (`brickfreedom auth profiles`)

Manage multiple authentication profiles (e.g., different accounts).

```bash
# List all profiles
brickfreedom auth profiles list

# Create a new profile
brickfreedom auth profiles create staging

# Select active profile
brickfreedom auth profiles select staging

# Delete a profile
brickfreedom auth profiles delete staging
```

### Cache (`brickfreedom cache`)

Manage the response cache. Cached responses speed up repeated commands by avoiding redundant browser/API calls.

```bash
# Clear all cached responses
brickfreedom cache clear
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--limit` | `-l` | Maximum number of results (default: 100) |
| `--filter` | `-f` | Filter results (field:op:value) |
| `--properties` | `-p` | Comma-separated fields to include |
| `--version` | `-v` | Show version and exit |

## Configuration

Configuration is stored in `.env` file:

```bash
# Base URL
BASE_URL=https://brickfreedom.com

# Browser settings (true = invisible, false = visible browser)
HEADLESS=true
```

Browser session data is stored in `authentication_profiles/` directory for persistence between commands.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Order Statuses

| Status | Description |
|--------|-------------|
| `PAID` | Payment received, not yet picked |
| `PENDING` | Awaiting payment |
| `UPDATED` | Order updated by buyer |
| `PROCESSING` | Being processed |
| `PROCESSED` | Picked/packed, ready for postage |
| `PACKED` | Packed and ready to ship |
| `SHIPPED` | Shipped to customer |
| `RECEIVED` | Received by customer |
| `CANCELLED` | Order cancelled |

## Models

This CLI uses Pydantic models for type-safe data handling. All commands return strongly-typed models.

### Available Models

| Model | Description | Key Fields |
|-------|-------------|------------|
| `Task` | Dashboard task | `index`, `text`, `completed` |
| `ReplacementPartTask` | Parsed replacement part task | `index`, `customerName`, `orderId`, `itemNo`, `itemName`, `color`, `qty`, `location` |
| `Order` | Order from orders page | `order_id`, `platform`, `status`, `buyer_name` |
| `ProcessedOrder` | Order ready for postage | `order_id`, `name`, `address`, `tracking_id` |

## Browser Automation Notes

- **First run**: Run `playwright install chromium` after pip install
- **Headless mode**: Set `HEADLESS=false` to see the browser (useful for debugging)
- **Session persistence**: Login sessions are saved in `authentication_profiles/` and reused automatically
- **Rate limiting**: Be respectful of the site's terms of service

## Debugging

To debug browser automation issues:

```bash
# Run with visible browser
export HEADLESS=false
brickfreedom order list
```

## Requirements

- Python 3.9+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - playwright
  - pydantic

## License

MIT
