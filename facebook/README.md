# Facebook CLI

## DESCRIPTION

The `facebook` CLI wraps playwright with standardized cli-tools behavior.

Use it when you need the underlying command exposed through cli-tools JSON/table conventions for agents, automation, or terminal workflows.

## Prerequisites

This CLI wraps the `playwright` command-line tool. You must install it first:

```bash
# Install playwright CLI
pip install playwright-cli
```

## Installation

```bash
cd facebook
./install.sh
```

After installation, the `facebook` command will be available in your terminal.

## Quick Start

```bash
# Check if browser session is active
facebook auth status

# Login (opens headed browser)
facebook auth login

# Browse marketplace listings
facebook marketplace list

# Search for items
facebook marketplace list --query "LEGO"

# List Messenger conversations
facebook messenger list

# Send a message
facebook messenger send 123456789 --text "Hello!"

# Read posts from a group
facebook groups posts list 123456789
facebook groups posts list 2318028917 --limit 25 --full-threads
```

## How It Works

This CLI is a **wrapper** around the `playwright` command-line tool:

- **Auth commands** manage the playwright browser session (shared across features)
- **Marketplace commands** use playwright to navigate Facebook Marketplace, capture page snapshots, and parse listing data
- **Messenger commands** use playwright to navigate Facebook Messenger, parse conversations and messages, and send messages
- **Groups commands** use playwright to navigate Facebook Groups and extract post data from the feed
- **Configuration** is minimal - stored in `.env`

## Commands

### Auth

Manage browser authentication sessions.

```bash
# Login via headed browser
facebook auth login
facebook auth login --force  # Re-authenticate
facebook auth login --force --profile work  # Uses USERNAME/PASSWORD from that profile

# Check authentication status
facebook auth status
facebook auth status --table

# Test authentication
facebook auth test
facebook auth test --verbose

# Logout (close browser session)
facebook auth logout
facebook auth logout --force  # Skip confirmation
```

`facebook auth login --force --profile <name>` requires `USERNAME` and
`PASSWORD` in that auth profile. The CLI submits those credentials into the
Facebook login form and fails loudly on checkpoint, two-step, or captcha
screens instead of falling back to manual browser login.

### Marketplace

Search and browse Facebook Marketplace listings.

```bash
# Browse "Today's picks" (default location)
facebook marketplace list
facebook marketplace list --location chicago

# Search by keyword
facebook marketplace list --query "LEGO"
facebook marketplace list --query "couch" --min-price 50 --max-price 500

# Output formatting
facebook marketplace list --table
facebook marketplace list --limit 20
facebook marketplace list --properties title,price
facebook marketplace list --filter "price:gt:100"

# Get specific listing
facebook marketplace get 123456789
facebook marketplace get 123456789 --table
facebook marketplace get 123456789 --properties title,price,location
```

### Messenger

Facebook Messenger conversations and messages.

```bash
# List conversations
facebook messenger list
facebook messenger list --table --limit 10
facebook messenger list --filter "name:contains:John"
facebook messenger list --properties id,name

# Get conversation with messages
facebook messenger get 123456789
facebook messenger get 123456789 --table
facebook messenger get 123456789 --limit 20

# Send a message
facebook messenger send 123456789 --text "Hello!"
facebook messenger send 123456789 -m "Thanks for your message"

# List message requests
facebook messenger requests
facebook messenger requests --table
```

### Groups

Read posts from Facebook Groups, list joined groups, create posts, comment, and reply.

```bash
# List all groups you've joined
facebook groups list
facebook groups list --table --limit 50

# List posts from a group (by ID or name)
facebook groups posts list 123456789
facebook groups posts list my-group-name

# Output formatting
facebook groups posts list 123456789 --table --limit 10
facebook groups posts list 2318028917 --limit 25 --full-threads
facebook groups posts list 123456789 --properties post_id,author,text
facebook groups posts list 123456789 --filter "author:contains:John"

# Get a specific post
facebook groups posts get https://www.facebook.com/groups/123/posts/456
facebook groups posts get 123/posts/456
facebook groups posts get 123/posts/456 --table

# Create a post in a group
facebook groups posts create 123456789 --text "Hello everyone!"
facebook groups posts create 123456789 -m "Looking for advice on shipping"

# Comment on a post
facebook groups posts comment https://www.facebook.com/groups/123/posts/456 --text "Great post!"
facebook groups posts comment 123/posts/456 -m "Thanks for sharing"

# Reply to a comment (by 1-based comment index)
facebook groups posts reply https://www.facebook.com/groups/123/posts/456 --comment-index 1 --text "Good point!"
facebook groups posts reply 123/posts/456 -c 2 -m "I agree"
```

### Groups Smoke Test

Run the batched groups smoke test to reuse one authenticated browser session for auth, joined groups, group post listing, and post get:

```bash
~/.local/share/uv/tools/facebook-cli/bin/python3 scripts/smoke_groups.py --group-id 2318028917
```

### Groups Get Instrumentation

Measure end-to-end process timing for `facebook groups get`, including CLI startup, the browser credential gate, page load, extraction, and JSON output:

```bash
~/.local/share/uv/tools/facebook-cli/bin/python3 scripts/instrument_groups_get.py GROUP_ID --iterations 3 --output data/group-get-timings.json
```

### Groups Posts Instrumentation

Measure end-to-end process timing for `facebook groups posts list`, including CLI startup, authenticated group-page fetch, GraphQL feed fetch, extraction, and JSON output:

```bash
~/.local/share/uv/tools/facebook-cli/bin/python3 scripts/instrument_groups_posts_list.py GROUP_ID --limit 3 --iterations 3 --output data/group-posts-timings.json
```

`facebook groups posts list` returns the latest 20 posts by default and accepts
`--limit` values from 1 to 25. Add `--full-threads` to fetch the thread
permalink, full body text, image URLs, and nested comments/replies for each
returned post in a single command invocation.

### Profiles

Manage authentication profiles for multiple accounts.

```bash
# List all profiles
facebook auth profiles list

# Create a new profile
facebook auth profiles create work

# Select active profile
facebook auth profiles select work

# Delete a profile
facebook auth profiles delete work
```

### Cache

Manage the local data cache.

```bash
# View cache status
facebook cache status

# Clear all cached data
facebook cache clear
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping
- **Table** (`--table`): Human-readable formatted table

## Filtering

Use `--filter` for client-side filtering with the format `field:operator:value`:

```bash
# Exact match
facebook marketplace list --filter "location:eq:New York, NY"

# Price range
facebook marketplace list --filter "price:gt:50"

# Contains
facebook marketplace list --filter "title:contains:LEGO"

# Messenger conversations
facebook messenger list --filter "name:contains:John"
```

Supported operators: `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `contains`, `startswith`, `endswith`, `in`, `nin`, `like`, `ilike`, `null`, `notnull`

## Configuration

Non-auth configuration is stored in `~/.local/share/cli-tools/facebook/.env`.
Browser-auth profiles live under
`~/.local/share/cli-tools/facebook/authentication_profiles/<profile>/`.

Example root config:

```bash
# Required: active profile marker
ACTIVE=true

# Base URL
BASE_URL=https://www.facebook.com/marketplace

# Underlying CLI command (defaults to playwright)
CLI_COMMAND=playwright
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/CLI not available error |
| 130 | User interrupted (Ctrl+C) |

## Requirements

- Python 3.9+
- `playwright` CLI installed and in PATH
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - pydantic
  - cli-tools-shared

## License

MIT
