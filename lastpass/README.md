# LastPass CLI

## DESCRIPTION

The `lastpass` CLI wraps lpass with standardized cli-tools behavior.

Use it when you need the underlying command exposed through cli-tools JSON/table conventions for agents, automation, or terminal workflows.

## Prerequisites

This CLI wraps the `lpass` command-line tool. Install it first:

```bash
# macOS
brew install lastpass-cli

# Debian/Ubuntu
sudo apt install lastpass-cli

# Fedora
sudo dnf install lastpass-cli
```

## Quick Start

```bash
# Check if lpass is installed and you're logged in
lastpass auth status

# Login to LastPass
lastpass auth login --email you@example.com

# List vault entries
lastpass items list

# Get a specific entry
lastpass items get github.com

# Copy password to clipboard
lastpass items password github.com --clip
```

## Commands

### Authentication

```bash
# Login (prompts for master password)
lastpass auth login --email you@example.com
lastpass auth login -e you@example.com

# Check status
lastpass auth status
lastpass auth status

# Sync vault with server
lastpass auth sync

# Logout
lastpass auth logout
lastpass auth logout --force
```

### Vault Entries

```bash
# List all entries
lastpass items list
lastpass items list

# List entries in a folder
lastpass items list Work
lastpass items list "Work/Servers"

# Filter entries
lastpass items list --filter "name:like:%github%"

# Filter by LastPass category/note type
lastpass items list --category "Payment Cards" --table
lastpass items list --category "Credit Card" --table

# Get entry details (password masked by default)
lastpass items get github.com
lastpass items get github.com

# Get entry with password visible
lastpass items get github.com --show-password

# Get just the password
lastpass items password github.com

# Copy password to clipboard
lastpass items password github.com --clip

# Get just the username
lastpass items username github.com
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting

### JSON Output Example

```bash
lastpass items list | jq '.[0]'
# {
#   "id": "1234567890123456789",
#   "name": "GitHub",
#   "group": "Work",
#   "full_path": "Work/GitHub"
# }
```

### Scripting Examples

```bash
# Get password for a site
PASSWORD=$(lastpass items password github.com)

# List all entries as JSON
lastpass items list > vault_backup.json

# Find entries with "github" in name
lastpass items list --filter "name:ilike:%github%"

# Find saved payment cards without printing card numbers
lastpass items list --category "Payment Cards" --table
```

### Profiles

```bash
# List all profiles
lastpass auth profiles list

# Create a new profile
lastpass auth profiles create work

# Set a profile as default
lastpass auth profiles select work

# Delete a profile
lastpass auth profiles delete work --force
```

## How It Works

This CLI wraps the `lpass` CLI:

- **`auth` commands** delegate to `lpass login`, `lpass logout`, `lpass status`
- **`items` commands** call `lpass ls` and `lpass show`, parse output to JSON/table
- **Credentials** are handled entirely by lpass (stored in system keychain)

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Not authenticated / CLI not available |
| 130 | User interrupted (Ctrl+C) |

## Requirements

- Python 3.9+
- `lpass` CLI installed and in PATH
- Dependencies (installed automatically):
  - typer
  - python-dotenv

## License

MIT

## Additional Commands

### Cache

```bash
lastpass cache --help
```
