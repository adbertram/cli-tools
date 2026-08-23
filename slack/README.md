# Slack CLI

## DESCRIPTION

The `slack` CLI provides a command-line interface for Slack API.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Installation

The CLI is already installed and available globally. The `slack` command is ready to use from any directory.

## Quick Start

1. **Authenticate** (opens browser, captures token automatically):
   ```bash
   slack auth login
   ```

2. **Verify**:
   ```bash
   slack auth test
   ```

3. **Use**:
   ```bash
   slack channels list --table
   slack messages send C1234567890 "Hello from CLI!"
   slack notifications summary
   ```

## Commands

### Authentication

```bash
# Authenticate (browser-based)
slack auth login

# Re-authenticate (clear and redo)
slack auth login --force

# Check auth status
slack auth status

# Test credentials
slack auth test
slack auth test --verbose

# Clear credentials
slack auth logout
```

### Profiles

Manage multiple authentication profiles (e.g., different workspaces or accounts).

```bash
# List all profiles
slack auth profiles list

# Create a new profile
slack auth profiles create <name>

# Get profile details
slack auth profiles get <name>

# Select the active profile
slack auth profiles select <name>

# Delete a profile
slack auth profiles delete <name>
```

### Channels

```bash
# List channels
slack channels list --table
slack channels list --types public_channel --limit 50
slack channels list --filter "is_private:eq:true"
slack channels list --filter "name:ilike:%general%" --properties "id,name,num_members"
slack channels list --unread --table

# Get channel info
slack channels get C1234567890

# Create a channel
slack channels create my-new-channel
slack channels create my-private-channel --private

# Join / leave / archive
slack channels join C1234567890
slack channels leave C1234567890
slack channels archive C1234567890

# List members
slack channels members C1234567890 --table
slack channels members C1234567890 --resolve --table
slack channels members C1234567890 --resolve --filter "is_bot:eq:false"
```

### Messages

```bash
# Send a message
slack messages send C1234567890 "Hello, World!"
slack messages send C1234567890 "Reply" --thread-ts 1234567890.123456

# List messages
slack messages list C1234567890 --table
slack messages list C1234567890 --limit 50
slack messages list C1234567890 --filter "user:eq:U1234567890"

# Get a specific message
slack messages get C1234567890 1234567890.123456

# List thread replies
slack messages threads C1234567890 1234567890.123456

# List mentions
slack messages mentions --table

# Search messages
slack messages search "hello world"
slack messages search "error" --count 50

# Delete a message
slack messages delete C1234567890 1234567890.123456
```

### Direct Messages

```bash
# List DM conversations
slack dm list --table
slack dm list --unread
slack dm list --limit 20 --filter "is_open:eq:true"

# Get DM conversation
slack dm get U1234567890

# Send a DM (by user ID, email, or @username)
slack dm send U1234567890 "Hello!"
slack dm send user@example.com "Hello via email!"
slack dm send @john.doe "Hey John!"

# Read DM history
slack dm read U1234567890
slack dm read user@example.com --limit 20

# Reply in a thread
slack dm send @john.doe "Thread reply" --thread-ts 1234567890.123456
```

### Users

```bash
# List users
slack users list --table
slack users list --limit 50
slack users list --filter "is_admin:eq:true"
slack users list --include-deleted --properties "id,name,deleted"

# Get user info
slack users get U1234567890

# Set your status
slack users set-status "In a meeting" --emoji :calendar:
slack users set-status "Away" --emoji :palm_tree:

# Set your profile photo
slack users set-photo ./avatar.png
```

### Files

```bash
# List files
slack files list --table
slack files list --channel C1234567890
slack files list --user U1234567890 --limit 50
slack files list --types images
slack files list --filter "filetype:eq:pdf"
slack files list --filter "size:gt:1000000" --properties "id,name,size,filetype"

# Get file info
slack files get F1234567890

# Upload a file
slack files upload document.pdf --channels C1234567890
slack files upload image.png --channels C1234567890 --title "Screenshot"

# Download a file
slack files download F1234567890
slack files download F1234567890 --output ./downloads/report.pdf

# Delete a file
slack files delete F1234567890
```

### Notifications

```bash
# List all notifications (unread DMs, mentions, threads, saved items)
slack notifications list --table
slack notifications list --no-threads --table
slack notifications list --limit 20 --filter "type:eq:dm"

# Quick notification counts
slack notifications counts --table

# Badge count summary
slack notifications summary
```

### Canvases

```bash
# List canvases
slack canvas list --table
slack canvas list --limit 50

# List canvases in a specific channel
slack canvas list C1234567890

# Get canvas content
slack canvas get F1234567890
slack canvas get F1234567890 --section-types h1,h2
slack canvas get F1234567890 --contains "Project"
```

### Bookmarks

```bash
# List bookmarks in a channel
slack bookmarks list C1234567890 --table

# Get a specific bookmark
slack bookmarks get C1234567890 Bk123ABC4DEF
```

### Pinned Items

```bash
# List pinned items in a channel
slack pins list C1234567890 --table

# Get a specific pinned item
slack pins get C1234567890 1234567890.123456
```

### Reminders

> **Note:** Slack replaced Reminders with "Save it for Later" in 2023. The `reminders.list` API is deprecated. You can still create reminders via CLI, but must view them in Slack's "Later" sidebar. See [Slack's changelog](https://docs.slack.dev/changelog/2023-07-its-later-already-for-stars-and-reminders) for details.

```bash
# List saved items
slack reminders list

# Create a reminder for a message
slack reminders new C1234567890 1234567890.123456
slack reminders new C1234567890 1234567890.123456 --due "30 min"

# Mark a reminder as complete
slack reminders complete Rm12345678

# Delete a reminder
slack reminders delete Rm12345678
```

### Cache

```bash
# Clear all cached responses
slack cache clear
```

Use `--no-cache` on any command to bypass the cache for a single request.

## Output Formats

All list commands support `--table` (`-t`) for tabular output. Default output is JSON.

```bash
# JSON (default)
slack channels list

# Table
slack channels list --table
```

### Filtering & Field Selection

List commands support client-side filtering and field projection:

```bash
# Filter with field:operator:value
slack channels list --filter "name:ilike:%general%"
slack users list --filter "is_admin:eq:true"
slack files list --filter "size:gt:1000000"

# Select specific fields
slack channels list --properties "id,name,num_members"
slack users list --properties "id,name,is_admin" --table

# Combine
slack channels list --filter "is_private:eq:false" --properties "id,name" --limit 10 --table
```

Supported operators: `eq`, `neq`, `gt`, `gte`, `lt`, `lte`, `like`, `ilike`, `in`.

## Configuration

### Environment Variables

Credentials are stored per-profile in `.env` files at `<cli-tools-root>/slack/profiles/<name>/.env`:

```bash
ACCESS_TOKEN=xoxc-your-token-here
REFRESH_TOKEN=
BASE_URL=https://slack.com/api
CLIENT_ID=your_client_id
CLIENT_SECRET=your_client_secret
ACTIVE=true
```

### Required OAuth Scopes

When creating your Slack app, add these Bot Token Scopes under "OAuth & Permissions":

| Category | Scopes |
|----------|--------|
| Channels | `channels:read`, `channels:history`, `channels:write`, `channels:manage`, `groups:read`, `groups:history`, `groups:write` |
| Messaging | `chat:write`, `chat:write.public` |
| Direct Messages | `im:read`, `im:write`, `im:history` |
| Users | `users:read`, `users:read.email`, `users.profile:read`, `users.profile:write` |
| Files | `files:read`, `files:write` |
| Search | `search:read` |
| Reminders | `reminders:read`, `reminders:write` |
| Canvases | `canvases:read` |
| Bookmarks | `bookmarks:read` |
| Pins | `pins:read` |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Requirements

- Python 3.9+
- Dependencies (installed automatically): typer, python-dotenv, requests

## License

MIT
