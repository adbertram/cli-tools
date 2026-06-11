# Podio CLI

## DESCRIPTION

The `podio` CLI provides a command-line interface for Podio API using pypodio2.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Features

- **Hierarchical command structure** - Organized by resource type (items, apps, tasks, spaces, comments, files, webhooks, conversations, webforms)
- **JSON output** - Perfect for scripting and automation
- **Environment-based authentication** - Secure credential management via .env
- **Comprehensive coverage** - Support for items, apps, tasks, spaces, comments, files, webhooks, and conversations
- **File management** - Upload, attach, download, and copy files
- **Webhook support** - Create, manage, and validate webhooks including field-level webhooks
- **Conversation management** - Direct messages, object conversations, search, and events
- **App field management** - Add, update, delete, and export application fields
- **Stdin/stdout support** - Easy integration with bash pipelines

## Installation

### Recommended: uv tool (global CLI)

```bash
cd <cli-tools-root>/podio
uv tool install -e . --force --refresh
```

This installs an isolated uv tool environment and exposes the `podio` executable on your `PATH`.

### Local development

```bash
cd <cli-tools-root>/podio
UV_PROJECT_ENVIRONMENT=~/.cache/uv/project-envs/podio-dev uv sync
UV_PROJECT_ENVIRONMENT=~/.cache/uv/project-envs/podio-dev uv run python -m pytest
```

Use this flow when contributing changes; remember to run `pytest` from the activated environment before submitting a PR.

## Authentication

Podio CLI supports multiple authentication methods. Choose the one that best fits your use case:

### 1. Client-Side Token Authentication (Simplest + Auto-Refresh)

Use an existing access token directly with automatic token refresh. Best for testing, automation, and AI agents.

```bash
# Direct token authentication with auto-refresh
PODIO_ACCESS_TOKEN=your_access_token
PODIO_REFRESH_TOKEN=your_refresh_token
PODIO_CLIENT_ID=your_client_id  # Required for auto-refresh
PODIO_CLIENT_SECRET=your_client_secret  # Required for auto-refresh
```

**Getting a token:**
```bash
# Generate authorization URL
podio auth url --flow client --redirect-uri http://localhost

# Visit the URL, authorize, and parse the callback
podio auth parse-callback "http://localhost#access_token=TOKEN&refresh_token=REFRESH"
```

**Automatic Token Refresh:**
- When the access token expires (after 8 hours), the CLI automatically refreshes it
- Uses the refresh token to get a new access token
- Retries failed requests automatically after refresh
- No manual intervention needed!

**Reference:** [Podio Client-Side Authentication](https://developers.podio.com/authentication/client_side)

### 2. Server-Side Authorization Code Flow (Most Secure)

OAuth 2.0 authorization code flow. Best for web applications that act on behalf of users.

```bash
# OAuth Client Credentials (required)
PODIO_CLIENT_ID=your_client_id
PODIO_CLIENT_SECRET=your_client_secret

# Authorization Code Flow
PODIO_AUTHORIZATION_CODE=received_code
PODIO_REDIRECT_URI=https://your-app.com/callback
```

**Getting an authorization code:**
```bash
# Generate authorization URL
podio auth url --flow server --redirect-uri https://your-app.com/callback

# Visit the URL, authorize, and parse the callback
podio auth parse-callback "https://your-app.com/callback?code=AUTHORIZATION_CODE"
```

**Reference:** [Podio Server-Side Authentication](https://developers.podio.com/authentication/server_side)

### 3. Username & Password Flow (For Personal Scripts)

Direct username/password authentication. Best for personal automation scripts.

```bash
# OAuth Client Credentials (required)
PODIO_CLIENT_ID=your_client_id
PODIO_CLIENT_SECRET=your_client_secret

# User Authentication
PODIO_USERNAME=your_email@example.com
PODIO_PASSWORD=your_password
```

### 4. App Authentication (Single App Access)

Authenticate as a specific app. Best for automation limited to one app.

```bash
# OAuth Client Credentials (required)
PODIO_CLIENT_ID=your_client_id
PODIO_CLIENT_SECRET=your_client_secret

# App Authentication
PODIO_APP_ID=your_app_id
PODIO_APP_TOKEN=your_app_token
```

### Optional: Default IDs

Set default organization and workspace IDs to avoid specifying them in every command:

```bash
PODIO_ORGANIZATION_ID=your_default_org_id
PODIO_WORKSPACE_ID=your_default_space_id
```

### Getting OAuth Credentials

1. Log in to Podio at https://podio.com
2. Go to Account Settings → API Keys (https://podio.com/settings/api)
3. Create a new OAuth client or use an existing one
4. Copy the Client ID and Client Secret to your `.env` file

### Authentication Command Reference

```bash
# Check authentication status (exit code 2 if not authenticated)
podio auth status

# Initiate OAuth login flow
podio auth login [--type client|server]

# Logout and clear credentials
podio auth logout [--force]

# Save tokens to .env file
podio auth save <access_token> <refresh_token>

# Generate OAuth authorization URL
podio auth url [--type client|server]

# Parse callback URL to extract tokens/codes
podio auth parse-callback "<callback_url>"

# Manually refresh access token
podio auth refresh
```

**Examples:**
```bash
# Check if authenticated
podio auth status

# Start client-side OAuth flow
podio auth login --type client

# Logout (with confirmation)
podio auth logout

# Force logout without confirmation
podio auth logout --force

# Save tokens after manual authentication
podio auth save abc123_access_token xyz789_refresh_token
```

## Profiles

Manage multiple Podio accounts or configurations with profiles.

```bash
# List all profiles
podio auth profiles list

# Create a new profile
podio auth profiles create staging

# Set a profile as default
podio auth profiles select staging

# Use a specific profile with any command
podio auth login --profile staging
podio auth status --profile staging

# Delete a profile
podio auth profiles delete staging
```

## Rate Limiting & Retries

All Podio API calls are wrapped with exponential backoff. The CLI retries 429 rate-limit responses as well as 5xx server errors by default (5 attempts, 2s → 60s backoff, jitter enabled). Tune the behavior via environment variables in your `.env`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `PODIO_RETRY_MAX_ATTEMPTS` | `5` | Total retry attempts (0 disables retries) |
| `PODIO_RETRY_BASE_DELAY` | `2.0` | Initial delay in seconds |
| `PODIO_RETRY_MAX_DELAY` | `60.0` | Maximum delay cap in seconds |
| `PODIO_RETRY_EXPONENTIAL_BASE` | `2.0` | Growth factor between retries (must be >1) |
| `PODIO_RETRY_JITTER` | `true` | Randomize delays to avoid thundering herds |
| `PODIO_RETRY_ON_RATE_LIMIT` | `true` | Disable only if you want 429s to fail immediately |

Invalid values raise an error during CLI startup so you know the configuration is safe before any write operations run.

## Usage

### General Syntax

```bash
podio <resource> <action> [arguments] [options]
```

### Available Commands

```bash
podio --help                    # Show all available commands
podio <resource> --help         # Show help for specific resource
podio <resource> <action> --help # Show help for specific action
```

## Command Reference

### Organization Commands

Manage Podio organizations.

```bash
# List all organizations you're a member of
podio org list
```

**Examples:**
```bash
# List all organizations (includes org_id and spaces)
podio org list
```

**Finding your Organization ID and Space ID:**

Run `podio org list` to see all your organizations with their `org_id` values and associated spaces with `space_id` values. You can then add these to your `.env` file as `PODIO_ORGANIZATION_ID` and `PODIO_WORKSPACE_ID`.

### App Commands

Manage Podio applications.

```bash
# Get application details
podio app get <app_id> [--fields] [--include-deleted]

# List all apps in a space
podio app list [--space-id <space_id>] [--limit 100] [--properties "field1,field2"]  # Uses PODIO_WORKSPACE_ID if not provided

# Create a new app
podio app create <space_id> --json-file app.json

# Get all items from an app
podio app items <app_id> [--limit 30] [--offset 0]

# Activate an app
podio app activate <app_id>

# Deactivate an app
podio app deactivate <app_id>

# Export app to Excel
podio app export <app_id> [--output file.xlsx] [--format xlsx|xls] [--limit N]

# Manage app fields
podio app field list <app_id>
podio app field get <app_id> <field_id>
podio app field add <app_id> --json-file field.json
podio app field update <app_id> <field_id> --json-file field.json
podio app field delete <app_id> <field_id>
```

**Examples:**
```bash
# Get details of app 30529466
podio app get 30529466

# Get only field schema for an app
podio app get 30529466 --fields
podio app get 30529466 --fields

# List all apps in space 10479826
podio app list --space-id 10479826
podio app list -s 10479826  # Short form

# List all apps in default workspace (uses PODIO_WORKSPACE_ID)
podio app list

# Get first 100 items from an app
podio app items 30529466 --limit 100

# Export app to Excel file
podio app export 30529466
podio app export 30529466 --output my_export.xlsx
podio app export 30529466 --format xls --limit 1000

# List all fields in an app
podio app field list 30529466

# Get a specific field
podio app field get 30529466 274720804

# Add a new field to an app
podio app field add 30529466 --json-file new_field.json

# Delete a field
podio app field delete 30529466 274720804

# Update a field (e.g., add category option)
podio app field update 30529466 274720804 --json-file updated_field.json
```

**Field Update Data Format:**

When updating a field, use `settings` at the root level (NOT nested under `config`):

```json
{
  "label": "Status",
  "settings": {
    "options": [
      {"id": 1, "status": "active", "text": "Option 1", "color": "DCEBD8"},
      {"id": 2, "status": "active", "text": "Option 2", "color": "FF7373"},
      {"status": "active", "text": "New Option", "color": "FFD700"}
    ],
    "multiple": false,
    "display": "inline"
  }
}
```

**Important:** Include existing options with their `id` values to preserve them. New options should omit the `id` field.

### Item Commands

Manage Podio items (create, read, update, delete).

```bash
# Get a single item
podio item get <item_id> [--basic]

# Get item by external ID
podio item get --external-id <id> --app-id <app_id>

# List/filter items in an app
podio item list <app_id> [--filter '{"status": "active"}'] [--limit 100] [--properties "field1,field2"] [--sort-by field] [--desc]

# Create a new item
podio item create <app_id> [--json-file file.json] [--silent] [--no-hook]

# Update an item
podio item update <item_id> [--json-file file.json] [--silent] [--no-hook]

# Delete an item
podio item delete <item_id> [--silent] [--no-hook]

# Get item field values (v2 API - clean format)
podio item values <item_id>

# Get a specific field value
podio item field-value <item_id> <field_id_or_external_id>
```

**Examples:**
```bash
# Get item with basic info
podio item get 12345 --basic

# Get item by external ID
podio item get --external-id my-custom-id --app-id 30543397

# List active items
podio item list 30529466 --filter '{"status": "active"}' --limit 50

# List items with specific properties
podio item list 30529466 --properties "item_id,title,status"

# Create item from JSON file
podio item create 30529466 --json-file new_article.json

# Create item from stdin (pipe)
echo '{"fields": [{"external_id": "title", "values": [{"value": "Test"}]}]}' | podio item create 30529466

# Update item silently (no notifications)
podio item update 12345 --json-file update.json --silent

# Delete item without triggering webhooks
podio item delete 12345 --no-hook

# Get all field values for an item (v2 API)
podio item values 12345
podio item values 12345

# Get a specific field value by field ID or external_id
podio item field-value 12345 274720804
podio item field-value 12345 potential-writer
podio item field-value 12345 status
```

**Item Data Format:**

For create/update operations, use this JSON structure:

```json
{
  "fields": [
    {
      "external_id": "title",
      "values": [{"value": "Item Title"}]
    },
    {
      "external_id": "status",
      "values": [{"value": "active"}]
    }
  ]
}
```

### Comment Commands

Manage comments on Podio objects (items, statuses, etc.).

```bash
# Add a comment to an item
podio comment create item <item_id> --text "Your comment text"

# List all comments on an object
podio comment list item <item_id> [--limit 100] [--offset 0]

# Get a specific comment
podio comment get <comment_id>

# Update a comment
podio comment update <comment_id> --text "Updated comment text"

# Delete a comment
podio comment delete <comment_id> [--no-hook]
```

**Examples:**
```bash
# Add a simple comment
podio comment create item 12345 --text "Great work!"

# Add a comment silently (no notifications)
podio comment create item 12345 --text "Internal note" --silent

# Add a comment from JSON file (for complex comments with attachments)
podio comment create item 12345 --json-file comment.json

# List recent comments
podio comment list item 12345 --limit 10

# Update a comment (for typo corrections)
podio comment update 98765 --text "Corrected spelling"

# Delete a comment without triggering webhooks
podio comment delete 98765 --no-hook
```

**Comment Data Format (for JSON files):**

```json
{
  "value": "Comment text",
  "external_id": "Optional external ID",
  "file_ids": [123, 456],
  "embed_id": 789,
  "embed_url": "https://example.com"
}
```

### Task Commands

Manage Podio tasks.

```bash
# Get a task
podio task get <task_id>

# Create a task
podio task create [--json-file file.json] [--text "description"] [--ref-type item] [--ref-id 12345] [--due-date 2025-01-15] [--private]

# Update a task
podio task update <task_id> [--json-file file.json] [--text "new text"] [--due-date 2025-01-20]

# Complete a task
podio task complete <task_id>

# Delete a task
podio task delete <task_id>

# Task labels
podio task list-labels
podio task create-label <text> [--color <hex_or_name>]
podio task update-labels <task_id> --labels <comma_separated_ids_or_names>
podio task delete-label <label_id>
```

**Examples:**
```bash
# Create task from command-line options
podio task create --text "Follow up with client" --ref-type item --ref-id 12345 --due-date 2025-01-15

# Create task from JSON file
podio task create --json-file task.json

# Create task from stdin
cat task.json | podio task create

# Complete a task
podio task complete 99999

# Update task text
podio task update 99999 --text "Updated description"

# List all task labels
podio task list-labels
podio task list-labels

# Create a new label
podio task create-label "High Priority"
podio task create-label "Urgent" --color red
podio task create-label "Review" --color "#FF5733"

# Update labels on a task
podio task update-labels 12345 --labels "123,456"
podio task update-labels 12345 --labels "High Priority,Urgent"

# Delete a label
podio task delete-label 12345
```

**Task Data Format:**

```json
{
  "text": "Task description",
  "description": "Detailed description",
  "due_date": "2025-01-15",
  "private": false,
  "ref_type": "item",
  "ref_id": 12345
}
```

### File Commands

Upload, attach, and manage files in Podio.

```bash
# Upload a file to Podio (returns file_id)
podio file upload <file_path> [--filename "custom_name.docx"]

# Attach a file to an object (item, task, comment, status, space)
podio file attach <file_id> <ref_type> <ref_id>

# Get file metadata
podio file get <file_id>

# Download a file
podio file download <file_id> [--output ./local-file.docx]

# Copy a file (creates new file_id)
podio file copy <file_id>
```

**Examples:**
```bash
# Upload a document
podio file upload ~/Documents/report.docx
# Returns: {"file_id": 2412642794, "name": "report.docx", ...}

# Upload with custom filename
podio file upload ~/Documents/draft.docx --filename "Final Report.docx"

# Attach file to an item
podio file attach 2412642794 item 12345

# Attach file to a task
podio file attach 2412642794 task 67890

# Attach file to a comment
podio file attach 2412642794 comment 11111

# Get file metadata
podio file get 2412642794

# Download file to current directory (uses original filename)
podio file download 2412642794

# Download file to specific path
podio file download 2412642794 --output ./downloads/my-report.docx

# Copy a file (useful for attaching same file to multiple objects)
podio file copy 2412642794
```

**Valid Reference Types for Attach:**
- `item` - Attach to a Podio item
- `task` - Attach to a task
- `comment` - Attach to a comment
- `status` - Attach to a status update
- `space` - Attach to a workspace

### Space Commands

Manage Podio spaces (workspaces).

```bash
# Get space details
podio space get [--space-id <space_id>]  # Uses PODIO_WORKSPACE_ID if not provided

# List all spaces in an organization
podio space list [--org-id <org_id>]  # Uses PODIO_ORGANIZATION_ID if not provided

# Find space by URL
podio space find-by-url <space_url>
```

**Examples:**
```bash
# Get space details
podio space get --space-id 10479826
podio space get -s 10479826  # Short form

# Get default workspace details (uses PODIO_WORKSPACE_ID)
podio space get

# List all spaces in organization
podio space list --org-id 3747840
podio space list -o 3747840  # Short form

# List all spaces in default organization (uses PODIO_ORGANIZATION_ID)
podio space list

# Find space by URL
podio space find-by-url https://podio.com/ata-learning-llc/progress-content-management
```

### Webhook Commands

Manage webhooks for Podio objects (items, apps, spaces).

```bash
# Create a webhook for an object
podio webhook create <ref_type> <ref_id> <url>

# List webhooks for an object
podio webhook list <ref_type> <ref_id>

# Request verification for a webhook
podio webhook verify <hook_id>

# Validate a webhook with verification code
podio webhook validate <hook_id> <code>

# Update a webhook URL
podio webhook update <hook_id> <url>

# Delete a webhook
podio webhook delete <hook_id>

# Field-level webhooks (fires only when specific field changes)
podio webhook create-field <app_id> <field_id> <url>
podio webhook list-field <app_id> <field_id>
podio webhook update-field <hook_id> <url>
```

**Examples:**
```bash
# Create a webhook for an app
podio webhook create app 30529466 https://myserver.com/webhook

# List all webhooks on an item
podio webhook list item 12345

# Create a field-level webhook
podio webhook create-field 30529466 274720804 https://myserver.com/field-webhook

# Request webhook verification
podio webhook verify 98765

# Validate with the code sent to your webhook URL
podio webhook validate 98765 abc123

# Update webhook URL
podio webhook update 98765 https://newserver.com/webhook

# Delete a webhook
podio webhook delete 98765
```

**Valid Reference Types:**
- `app` - Application-level webhooks
- `item` - Item-level webhooks
- `space` - Space-level webhooks

### Conversation Commands

Manage Podio conversations (direct messages and object-based discussions).

```bash
# List all conversations
podio conversation list [--limit 100] [--filter "field:value"] [--properties "field1,field2"]

# Get a specific conversation
podio conversation get <conversation_id>

# Create a new conversation (direct)
podio conversation create --subject "Topic" --text "Message" --participants "user1,user2"

# Create a conversation on an object
podio conversation create --ref-type item --ref-id 12345 --subject "Topic" --text "Message"

# Reply to a conversation
podio conversation reply <conversation_id> --text "Reply message"

# Add participants to a conversation
podio conversation participant add <conversation_id> --users "user1,user2"

# Mark conversation as read/unread
podio conversation mark-read <conversation_id>
podio conversation mark-unread <conversation_id>

# Star/unstar a conversation
podio conversation star <conversation_id>
podio conversation unstar <conversation_id>

# Leave a conversation
podio conversation leave <conversation_id>

# Search conversations
podio conversation search --text "search query"

# Get conversation events (messages)
podio conversation events <conversation_id> [--limit 100]

# Object-based conversations
podio conversation on-object <ref_type> <ref_id>
```

**Examples:**
```bash
# List recent conversations
podio conversation list --limit 10

# Get a specific conversation with all messages
podio conversation get 12345678

# Start a new direct conversation
podio conversation create --subject "Project Update" --text "Here's the status..." --participants "123,456"

# Create a conversation on an item
podio conversation create --ref-type item --ref-id 12345 --subject "Question" --text "Need help with this"

# Reply to a conversation
podio conversation reply 12345678 --text "Thanks for the update!"

# Add participants
podio conversation participant add 12345678 --users "789,012"

# Search for conversations
podio conversation search --text "budget"

# Get all conversations on an item
podio conversation on-object item 12345

# Star an important conversation
podio conversation star 12345678

# Mark conversation as read
podio conversation mark-read 12345678
```

### Webform Commands

Manage Podio webforms (public forms for item creation).

```bash
# List all webforms for an app
podio webform list <app_id>

# Get a specific webform
podio webform get <form_id>

# Submit data to a webform via HTTP POST (like a browser)
podio webform submit <webform_url> --json-file data.json
```

**Examples:**
```bash
# List webforms for an app
podio webform list 30529466
podio webform list 30529466

# Get webform details
podio webform get 2581518
podio webform get 2581518

# Submit to a webform using the public URL
echo '{"title": "My Title", "requested-description": "Description text"}' | podio webform submit "https://podio.com/webforms/30560419/2584779"

# Submit from a JSON file
podio webform submit "https://podio.com/webforms/30560419/2584779" -f data.json
```

**Submit Data Format:**

Use field external_id as keys (matches the webform field names):
```json
{
  "title": "My Title",
  "requested-description": "Some description text",
  "category": "Option 1"
}
```

**Note:** The submit command POSTs directly to the public webform URL, exactly like a browser would. No Podio authentication is required - it uses the public webform endpoint with CSRF token handling.

## Automation Examples

### Scripting with JSON Output

All commands output JSON by default, making them perfect for automation:

```bash
# Get all apps and extract their IDs
podio app list 10479826 | jq '.[].app_id'

# Count items in an app
podio item filter 30529466 | jq '.total'

# Get all active items
podio item filter 30529466 --filters '{"status": "active"}' > active_items.json

# Process items in a loop
for item_id in $(podio item filter 30529466 | jq -r '.items[].item_id'); do
  podio item get $item_id
done
```

### Batch Operations

```bash
# Create multiple items from individual JSON files
for file in items/*.json; do
  podio item create 30529466 --json-file "$file"
done

# Update multiple items
cat item_updates.json | while read update; do
  echo "$update" | podio item update 12345
done
```

### Exit Codes

The CLI uses standard exit codes for automation:

- `0` - Success
- `1` - General error (API error, not found, etc.)
- `2` - Authentication error
- `130` - Interrupted (Ctrl+C)

```bash
# Check if command succeeded
if podio item get 12345 > /dev/null 2>&1; then
  echo "Item exists"
else
  echo "Item not found or error occurred"
fi
```

## Output Format

All commands output JSON to stdout, while status messages and errors go to stderr. This keeps stdout clean for piping:

```bash
# Success message goes to stderr, JSON to stdout
podio item create 30529466 --json-file item.json
# stderr: ✓ Item created successfully
# stdout: {"item_id": 12345, ...}

# Pipe JSON output without seeing status messages
podio app list 10479826 | jq '.[].name'
```

## Error Handling

The CLI provides clear error messages:

```bash
# Authentication error
Error: Authentication failed. Please check your credentials in .env file.

# Resource not found
Error: Resource not found.

# Invalid request
Error: Invalid request: Field 'title' is required

# Rate limit
Error: Rate limit exceeded. Please try again later.
```

## Advanced Usage

### Global Options

```bash
# Show version
podio --version

# Install shell completion
podio --install-completion

# Show completion for current shell
podio --show-completion
```

### Shell Completion

Enable auto-completion for your shell:

```bash
# Bash
podio --install-completion bash

# Zsh
podio --install-completion zsh

# Fish
podio --install-completion fish
```

### Configuration

Create a `.env` file at `~/.podio/.env` with your credentials:

```bash
mkdir -p ~/.podio
nano ~/.podio/.env  # Or use your preferred editor
```

The CLI automatically loads credentials from `.env` in this order:
1. `~/.podio/.env` (recommended global configuration)
2. Current directory (for local testing/overrides)
3. Parent directory (for local testing/overrides)

You can also set environment variables directly:

```bash
export PODIO_CLIENT_ID=your_id
export PODIO_CLIENT_SECRET=your_secret
export PODIO_USERNAME=your_email
export PODIO_PASSWORD=your_password

podio app list 10479826
```

## Development

### Project Structure

```
pypodio-cli/
├── podio_cli/
│   ├── __init__.py
│   ├── main.py              # Entry point
│   ├── config.py            # Configuration management
│   ├── client.py            # Podio client wrapper
│   ├── output.py            # Output formatting
│   └── commands/            # Command modules
│       ├── __init__.py
│       ├── app.py           # Application commands
│       ├── item.py          # Item commands
│       ├── task.py          # Task commands
│       ├── space.py         # Space commands
│       ├── org.py           # Organization commands
│       ├── auth.py          # Authentication commands
│       ├── comment.py       # Comment commands
│       ├── file.py          # File upload/attach commands
│       ├── webhook.py       # Webhook management
│       ├── conversation.py  # Conversation/messaging commands
│       └── webform.py       # Webform management
├── tests/
├── pyproject.toml
└── README.md
```

### Running Tests

```bash
# Install development dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run with coverage
pytest --cov=podio_cli
```

### Adding New Commands

To add a new command module:

1. Create a new file in `podio_cli/commands/`
2. Define a Typer app and commands
3. Import and register in `main.py`

Example:

```python
# podio_cli/commands/myresource.py
import typer
from ..client import get_client
from ..output import print_json, handle_api_error, format_response

app = typer.Typer(help="Manage my resource")

@app.command("get")
def get_resource(resource_id: int):
    """Get a resource by ID."""
    try:
        client = get_client()
        result = client.MyResource.find(resource_id=resource_id)
        print_json(format_response(result))
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)
```

Then register in `main.py`:

```python
from .commands import myresource
app.add_typer(myresource.app, name="myresource", help="Manage my resource")
```

## Dependencies

- **typer** - CLI framework with rich formatting
- **pypodio2** - Podio API wrapper
- **python-dotenv** - Environment variable management

## License

MIT License

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## Support

For issues and questions:
- Check the [Podio API documentation](https://developers.podio.com/)
- Review pypodio2 documentation
- Open an issue on GitHub

## Changelog

### v0.1.1 (2025-12-30)

- Fixed `--version` flag to work standalone without requiring a command
- Added comprehensive documentation for all commands
- Documented webhook commands (create, list, verify, validate, update, delete, field-level webhooks)
- Documented conversation commands (list, get, create, reply, search, events, object conversations)
- Documented app export and field management commands
- Documented item values, field-value, and get-by-external-id commands
- Documented task label commands (list-labels, create-label, update-labels, delete-label)

### v0.1.0 (2025-11-04)

- Initial release
- Support for items, apps, tasks, and spaces
- JSON output format
- Environment-based authentication
- Comprehensive command-line options
- Shell completion support

## Additional Commands

### Cache

```bash
podio cache --help
```
