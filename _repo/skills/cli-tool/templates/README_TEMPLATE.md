# {ToolName} CLI

A command-line interface for [{ServiceName}]({service_url}). {Brief description of what users can do with this CLI}.

## Installation

```bash
# Clone and install
cd {toolname}
pip install -e .
```

After installation, the `{toolname}` command will be available in your terminal.

## Quick Start

```bash
# {Description of first common action}
{toolname} {command} {subcommand} {args}

# {Description of second common action}
{toolname} {command} {subcommand} {args}

# Login to your account (if authentication required)
{toolname} auth login
```

## Commands

### Authentication

{Description of authentication requirements - when it's needed, what it enables.}

```bash
# Login with prompts
{toolname} auth login

# Login with credentials
{toolname} auth login -u your@email.com -p yourpassword

# Check authentication status
{toolname} auth status

# Validate token with API
{toolname} auth status --validate

# Logout and clear credentials
{toolname} auth logout
```

### Profiles

Manage configuration profiles for multiple accounts or environments.

```bash
# List all profiles
{toolname} auth profiles list

# Show a profile
{toolname} auth profiles get default

# Switch default profile
{toolname} auth profiles set-default PROFILE_NAME

# Create a new profile
{toolname} auth profiles create PROFILE_NAME
```

### {CommandGroup1}

{Description of what this command group does.}

```bash
# List all {resources}
{toolname} {group} list

# List with table format
{toolname} {group} list

# Get a specific {resource}
{toolname} {group} get {resource_id}

# Create a new {resource}
{toolname} {group} create --name "Example"

# Filter/search {resources}
{toolname} {group} list --filter "criteria"
```

### {CommandGroup2}

{Description of what this command group does.}

```bash
# Example command 1
{toolname} {group2} {subcommand} {args}

# Example command 2
{toolname} {group2} {subcommand} --option value
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping

### JSON Output Example

```bash
{toolname} {group} list --limit 2
```

```json
{
  "total_count": 100,
  "items": [
    {
      "id": "123",
      "name": "Example Item",
      "created_at": "2025-01-15T10:30:00Z"
    }
  ]
}
```

### Table Output Example

```bash
{toolname} {group} list --limit 5
```

```
Found 100 items (showing 5)
ID          Name                    Created
---------------------------------------------
123         Example Item            01/15 10:30
124         Another Item            01/14 09:00
```

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--limit` | `-l` | Maximum number of results (default: varies) |
| `--page` | `-p` | Page number for pagination |
| `--filter` | `-f` | Filter results by criteria |
| `--sort` | `-s` | Sort by field |
| `--desc` | `-d` | Sort in descending order |
| `--yes` | `-y` | Skip confirmation prompts |
| `--all` | `-a` | Include all fields in output |

{Add or remove options as appropriate for your CLI.}

## Configuration

Non-authentication configuration is stored in `~/.local/share/cli-tools/{toolname}/.env`. Authentication data is stored in the active profile at `~/.local/share/cli-tools/{toolname}/authentication_profiles/<profile>/.env`. The source repo only carries `.env.example`.

Reusable CLI credentials that agents or scripts need to store/retrieve are governed by the user-level `cli-tool` skill's `references/secrets.md`.

Root config variables:

```bash
# Optional non-authentication configuration
{TOOLNAME}_BASE_URL=https://api.example.com
```

Authentication profile variables:

```bash
# Required credentials
{TOOLNAME}_API_KEY=your_api_key
{TOOLNAME}_CLIENT_ID=your_client_id
{TOOLNAME}_CLIENT_SECRET=your_client_secret

# OAuth tokens (managed automatically)
{TOOLNAME}_ACCESS_TOKEN=<jwt_token>
{TOOLNAME}_REFRESH_TOKEN=<refresh_token>
{TOOLNAME}_TOKEN_EXPIRES_AT=<timestamp>
```

You can also set these as environment variables directly.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### {Use Case 1 Title}

```bash
{toolname} {command} {subcommand} {args}
```

### {Use Case 2 Title}

```bash
{toolname} {command} {subcommand} --option value
```

### {Use Case 3 Title}

```bash
{toolname} {command} {subcommand} | jq '.items[].id'
```

### Script-Friendly JSON Output

```bash
# Get specific field from results
{toolname} {group} list | jq '.items[].id'

# Process multiple items
{toolname} {group} list | jq -r '.items[] | "\(.id): \(.name)"'
```

## Requirements

- Python 3.9+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests
  - {additional dependencies}

## License

MIT

---

## Template Instructions

When creating a new CLI README:

1. **Replace all placeholders** - Search for `{` and replace with actual values
2. **Add command groups** - Copy the CommandGroup section for each command group in your CLI
3. **Update options table** - Include only options your CLI actually supports
4. **Add real examples** - Replace example commands with actual working commands
5. **Update configuration** - List all environment variables your CLI uses
6. **Add dependencies** - List all packages from pyproject.toml
7. **Remove this section** - Delete this "Template Instructions" section from the final README

### Placeholder Reference

| Placeholder | Example |
|-------------|---------|
| `{ToolName}` | ShopGoodwill |
| `{toolname}` | shopgoodwill |
| `{TOOLNAME}` | SHOPGOODWILL |
| `{ServiceName}` | ShopGoodwill.com |
| `{service_url}` | https://shopgoodwill.com |
| `{CommandGroup1}` | Search |
| `{group}` | search |
| `{resource}` | item |
| `{resource_id}` | 123456789 |
