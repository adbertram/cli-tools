# Cloudflare CLI

## DESCRIPTION

The `cloudflare` CLI provides a command-line interface for Cloudflare API.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Installation

```bash
cd cloudflare
pip install -e .
```

After installation, the `cloudflare` command will be available in your terminal.

## Quick Start

```bash
# Authenticate with Cloudflare
cloudflare auth login

# List zones
cloudflare zones list

# Purge cache for a zone
cloudflare cache purge ZONE_ID
```

## Commands

### Authentication

```bash
# Login with API token
cloudflare auth login
cloudflare auth login --api-token YOUR_API_TOKEN

# Force re-authentication
cloudflare auth login --force

# Check authentication status
cloudflare auth status
cloudflare auth status

# Clear stored credentials
cloudflare auth logout
```

### Profiles

```bash
# List all profiles
cloudflare auth profiles list
cloudflare auth profiles list --table

# Get a specific profile
cloudflare auth profiles get default

# Filter profiles
cloudflare auth profiles list --filter "active:eq:true"

# Create a new profile
cloudflare auth profiles create staging

# Select active profile
cloudflare auth profiles select staging

# Delete a profile
cloudflare auth profiles delete staging --force
```

### Zones

```bash
# List all zones (JSON output)
cloudflare zones list

# List zones with table format
cloudflare zones list

# Limit results
cloudflare zones list --limit 10

# Filter by status
cloudflare zones list --filter "status:active"

# Select specific properties
cloudflare zones list --properties "id,name,status"

# Get a specific zone
cloudflare zones get ZONE_ID
cloudflare zones get ZONE_ID

# Update zone settings
cloudflare zones update ZONE_ID --security-level high
cloudflare zones update ZONE_ID --security-level under_attack
cloudflare zones update ZONE_ID -s medium
```

**Security Levels:**
- `off` - No security
- `essentially_off` - Challenges only the most grievous offenders
- `low` - Challenges more visitors
- `medium` - Challenges visitors displaying threatening behavior (default)
- `high` - High security level
- `under_attack` - I'm Under Attack mode

### Cache

```bash
# Purge all cache for a zone (prompts for confirmation)
cloudflare cache purge ZONE_ID

# Purge without confirmation
cloudflare cache purge ZONE_ID --force

# Show result as table
cloudflare cache purge ZONE_ID --force
```

### Access Rules

```bash
# List access rules for a zone
cloudflare access-rules list ZONE_ID
cloudflare access-rules list ZONE_ID --table
cloudflare access-rules list ZONE_ID --mode whitelist

# Get a specific rule
cloudflare access-rules get ZONE_ID RULE_ID

# Create a rule
cloudflare access-rules create ZONE_ID --target ip --value 1.2.3.4 --mode block

# Update a rule
cloudflare access-rules update ZONE_ID RULE_ID --mode challenge

# Delete a rule
cloudflare access-rules delete ZONE_ID RULE_ID --force
```

### DNS

#### DNS Zones

```bash
# List zones
cloudflare dns zones list
cloudflare dns zones list --table
cloudflare dns zones list --filter "status:eq:active"

# Get zone details
cloudflare dns zones get ZONE_ID
```

#### DNS Records

```bash
# List records for a zone
cloudflare dns records list ZONE_ID
cloudflare dns records list ZONE_ID --table
cloudflare dns records list ZONE_ID --type TXT
cloudflare dns records list ZONE_ID --filter "type:eq:A"

# Get a specific record
cloudflare dns records get ZONE_ID RECORD_ID

# Create a record
cloudflare dns records create ZONE_ID --type A --name example.com --content 1.2.3.4
cloudflare dns records create ZONE_ID --type TXT --name example.com --content "v=spf1 ..."
cloudflare dns records create ZONE_ID --type MX --name example.com --content mail.example.com --priority 10

# Update a record
cloudflare dns records update ZONE_ID RECORD_ID --content 5.6.7.8

# Delete a record
cloudflare dns records delete ZONE_ID RECORD_ID --force
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping

### JSON Output Example

```bash
cloudflare zones list --limit 2
```

### Table Output Example

```bash
cloudflare zones list --limit 5
```

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--limit` | `-l` | Maximum number of results (default: 50) |
| `--filter` | `-f` | Filter results (field:value) |
| `--properties` | `-p` | Comma-separated fields to display |
| `--security-level` | `-s` | Set zone security level |
| `--force` | `-F` | Skip confirmation prompts |
| `--version` | `-v` | Show version and exit |

## Configuration

Authentication profile files live under `~/.local/share/cli-tools/cloudflare/authentication_profiles/<profile>/`; non-auth defaults live in `~/.local/share/cli-tools/cloudflare/.env`:

```bash
# API Token (recommended)
CLOUDFLARE_API_TOKEN=your_api_token

# Optional: API base URL
CLOUDFLARE_BASE_URL=https://api.cloudflare.com/client/v4
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### List Zones and Filter with jq

```bash
cloudflare zones list | jq '.[].name'
```

### Export Zones to JSON File

```bash
cloudflare zones list --limit 100 > zones.json
```

### Purge Cache for Multiple Zones

```bash
for zone_id in $(cloudflare zones list | jq -r '.[].id'); do
    cloudflare cache purge "$zone_id" --force
done
```

## Models

This CLI uses Pydantic models for type-safe data handling. All commands return strongly-typed models.

### Available Models

| Model | Description | Required Fields |
|-------|-------------|-----------------|
| `Zone` | Cloudflare zone for list commands | `id`, `name`, `status` |
| `ZoneDetail` | Extended zone for get commands | `id`, `name`, `status` |
| `PurgeResult` | Cache purge result | `id` |

## Shell Completion

You can install shell completion (copy and paste appropriate command):

```bash
# Bash
cloudflare --install-completion bash

# Zsh
cloudflare --install-completion zsh

# Fish
cloudflare --install-completion fish
```

## Requirements

- Python 3.9+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests
  - pydantic

## License

MIT
