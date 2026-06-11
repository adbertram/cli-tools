# Hyvor CLI

## DESCRIPTION

The `hyvor` CLI provides a command-line interface for Hyvor API.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Installation

```bash
cd hyvor
pip install -e .
```

After installation, the `hyvor` command will be available in your terminal.

## Quick Start

```bash
# Authenticate with Hyvor
hyvor auth login --api-key YOUR_API_KEY --website-id YOUR_WEBSITE_ID

# List comments
hyvor comments list

# Get a specific comment
hyvor comments get COMMENT_ID

# Reply to a comment
hyvor comments reply COMMENT_ID "Your reply text here"
```

## Commands

### Authentication

```bash
# Login with API key (will prompt for inputs)
hyvor auth login

# Login with API key and website ID
hyvor auth login --api-key YOUR_API_KEY --website-id 12345

# Force re-authentication (clears existing credentials)
hyvor auth login --force

# Check authentication status
hyvor auth status

# Test API connectivity
hyvor auth test

# Clear stored credentials
hyvor auth logout

# Use a named profile
hyvor auth login --profile work
hyvor auth status --profile work
```

### Profiles

```bash
# List all profiles
hyvor auth profiles list

# Create a new profile
hyvor auth profiles create work

# Select active profile
hyvor auth profiles select work

# Delete a profile
hyvor auth profiles delete work

# Use a specific profile with any command
hyvor comments list --profile work
```

### Comments

#### List Comments

```bash
# List all comments (JSON output)
hyvor comments list

# List with table format
hyvor comments list --table

# Limit results
hyvor comments list --limit 10

# Pagination with offset
hyvor comments list --limit 50 --offset 100

# Filter results (if supported)
hyvor comments list --filter "status:eq:approved"

# Select specific fields to display
hyvor comments list --properties "id,body_html,status,created_at"
```

#### Get a Specific Comment

```bash
# Get comment details (JSON output)
hyvor comments get COMMENT_ID

# Get comment with table format
hyvor comments get COMMENT_ID --table

# Get specific fields
hyvor comments get COMMENT_ID --properties "id,body_html,user.name,status"
```

#### Reply to a Comment

```bash
# Reply to a comment
hyvor comments reply COMMENT_ID "This is my reply text"

# Reply and display as table
hyvor comments reply COMMENT_ID "Thanks for your feedback!" --table
```

#### Update a Comment

```bash
# Update comment body
hyvor comments update COMMENT_ID --body "Updated comment text"

# Change comment status
hyvor comments update COMMENT_ID --status "approved"

# Both updates at once
hyvor comments update COMMENT_ID --body "Updated text" --status "approved"
```

#### Delete a Comment

```bash
# Delete a comment (will confirm)
hyvor comments delete COMMENT_ID

# Delete without confirmation
hyvor comments delete COMMENT_ID --confirm
```

#### Mark Comment as Spam

```bash
# Mark a comment as spam
hyvor comments spam COMMENT_ID

# Mark as spam and display result as table
hyvor comments spam COMMENT_ID --table
```

This command updates the comment's status to 'spam', which helps train Hyvor's spam detection system.

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping
- **Table** (`--table`, `-t`): Human-readable table format

### JSON Output Example

```bash
hyvor comments list --limit 2
```

### Table Output Example

```bash
hyvor comments list --limit 5 --table
```

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display results as table instead of JSON |
| `--limit` | `-l` | Maximum number of results (default: 100) |
| `--offset` | `-o` | Pagination offset for list commands |
| `--filter` | `-f` | Filter results (field:op:value) |
| `--properties` | `-p` | Comma-separated fields to include (supports dot-notation like `user.name`) |
| `--confirm` | `-y` | Skip confirmation prompts |
| `--version` | `-v` | Show version and exit |

## Configuration

Authentication profile files live under `~/.local/share/cli-tools/hyvor/authentication_profiles/<profile>/`; non-auth defaults live in `~/.local/share/cli-tools/hyvor/.env`:

```bash
# Required: API Key (create at Console → Settings → API)
HYVOR_API_KEY=your_api_key_here

# Required: Website ID (find at Console → Settings → Website ID)
HYVOR_WEBSITE_ID=12345

# Optional: API base URL (defaults to production)
HYVOR_BASE_URL=https://talk.hyvor.com/api/console/v1
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### List and Filter Comments with jq

```bash
# Get all approved comment IDs
hyvor comments list | jq '.[].id'

# Get comments with specific status
hyvor comments list | jq '.[] | select(.status == "approved")'

# Extract comment body and author
hyvor comments list | jq '.[] | {id, author: .user.name, body: .body_html}'
```

### Export Comments to JSON File

```bash
hyvor comments list --limit 1000 > comments.json
```

### Update Multiple Comments

```bash
# Get all pending comments and change status to approved
hyvor comments list | jq -r '.[] | select(.status == "pending") | .id' | \
  xargs -I {} hyvor comments update {} --status "approved"
```

## Models

This CLI uses Pydantic models for type-safe data handling. All commands return strongly-typed models.

### Available Models

| Model | Description | Required Fields |
|-------|-------------|-----------------|
| `Comment` | Base comment for list commands | `id`, `body_html`, `created_at` |
| `CommentDetail` | Extended comment for get commands | `id`, `body_html`, `created_at` |
| `User` | Comment author information | `id`, `name` |
| `Page` | Website page information | `id`, `title`, `url` |

## Authentication Details

The Hyvor API uses **API Key authentication**. All requests include your API key in the `X-API-KEY` header.

Your **Website ID** is required for all API calls and identifies which website's comments you're managing.

To find your credentials:
1. Go to your Hyvor Talk Console (https://talk.hyvor.com/)
2. API Key: Console → Settings → API → Create API Key
3. Website ID: Console → Settings → Website ID

## Requirements

- Python 3.9+
- Dependencies (installed automatically):
  - typer (CLI framework)
  - python-dotenv (environment configuration)
  - requests (HTTP client)
  - pydantic (data validation)
  - rich (table formatting)

## License

MIT

## Cache

```bash
hyvor cache status
hyvor cache clear
```
