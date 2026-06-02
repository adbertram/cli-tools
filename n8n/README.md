# n8n CLI

Manage n8n server - nodes, executions, credentials, data tables, and logs.

## Installation

```bash
cd n8n
pip install -e .
```

## Quick Start

```bash
# Check configuration
n8n auth status

# List available CLI tools for conversion
n8n nodes cli-tools list

# Convert a CLI tool to an n8n node package
n8n nodes create brickowl

# Deploy to the n8n server
n8n nodes deploy brickowl

# Test the installed node
n8n nodes test brickowl -r orders -o list

# View recent failed executions
n8n executions list --from 2026-02-12 --status error --table
```

## Commands

### Authentication

```bash
# Configure API key (interactive prompt)
n8n auth login

# Re-authenticate (clear and re-prompt)
n8n auth login --force

# Login with a specific profile
n8n auth login --profile staging

# Check configuration status
n8n auth status

# Clear configuration
n8n auth logout
```

### Profiles

```bash
# List all profiles
n8n auth profiles list

# Create a new profile
n8n auth profiles create staging

# Select active profile
n8n auth profiles select staging

# Get profile details
n8n auth profiles get default

# Delete a profile
n8n auth profiles delete staging
```

### Nodes

Manage n8n node packages - create, deploy, test, and inspect.

```bash
# List generated node packages
n8n nodes list
n8n nodes list --table

# List nodes installed on the n8n server
n8n nodes list --type community
n8n nodes list --type custom
n8n nodes list --type default

# Get details for a generated package
n8n nodes get brickowl

# Get details for a built-in node from the server
n8n nodes get slack --type default
n8n nodes get slack --type default --table

# Create a node package from a CLI tool
n8n nodes create brickowl
n8n nodes create brickowl --force
n8n nodes create brickowl --output-dir ./out

# Deploy a node package to the n8n server
n8n nodes deploy brickowl
n8n nodes deploy brickowl --skip-build

# Install/remove third-party community packages through n8n itself
n8n nodes install n8n-nodes-mcp
n8n nodes install @chrishdx/n8n-nodes-codex-cli-lm
n8n nodes remove @chrishdx/n8n-nodes-codex-cli-lm

# Test an installed node on the n8n server
n8n nodes test brickowl -r orders -o list
n8n nodes test brickowl -p '{"zone":"example.com"}'
n8n nodes test brickowl --no-cleanup
n8n nodes test brickowl --timeout 120

# List available CLI tools for conversion
n8n nodes cli-tools list
n8n nodes cli-tools list --table

# Inspect a CLI tool's metadata
n8n nodes cli-tools get brickowl
n8n nodes cli-tools get brickowl --table
```

### Workflows

Manage n8n workflows - list, create, update, delete, activate, deactivate, execute, and export.

```bash
# List all workflows
n8n workflows list
n8n workflows list --table
n8n workflows list --active

# Get full workflow details
n8n workflows get WORKFLOW_ID
n8n workflows get WORKFLOW_ID --table

# Create a workflow from JSON file
n8n workflows create workflow.json
n8n workflows create workflow.json --name "My Workflow" --activate

# Update a workflow
n8n workflows update WORKFLOW_ID --file updated.json
n8n workflows update WORKFLOW_ID --name "New Name"
n8n workflows update WORKFLOW_ID --activate
n8n workflows update WORKFLOW_ID --deactivate

# Delete a workflow
n8n workflows delete WORKFLOW_ID
n8n workflows delete WORKFLOW_ID --yes

# Activate / deactivate
n8n workflows activate WORKFLOW_ID
n8n workflows deactivate WORKFLOW_ID

# Execute a workflow on the server (via SSH)
n8n workflows execute WORKFLOW_ID

# Export workflow JSON to file
n8n workflows export WORKFLOW_ID
n8n workflows export WORKFLOW_ID -o backup.json

# Add a node to a workflow
n8n workflows node add WORKFLOW_ID slack -r message -o post --after "Manual Trigger"
n8n workflows node add WORKFLOW_ID airtable --name "Read Records" --params '{"baseId":"app123"}'

# Add a node with a specific credential (by name or ID)
n8n workflows node add WORKFLOW_ID emailReadImap --credential "Example IMAP"
n8n workflows node add WORKFLOW_ID slack --credential 0PN4yGZVOouxl6qa --after "Trigger"

# Insert a node between two existing nodes
n8n workflows node add WORKFLOW_ID slack --between "HTTP Request,Set Fields"

# Connect two existing nodes
n8n workflows node connect WORKFLOW_ID --from "Slack" --to "Set Fields"
n8n workflows node connect WORKFLOW_ID --from "Router" --to "Branch 2" --output-index 1
```

### Credentials

```bash
# List credentials on the server
n8n credentials list
n8n credentials list --table

# Create a credential
n8n credentials create brickowlApi '{"apiKey":"abc123"}'

# Get credential type schema
n8n credentials schema brickowlApi

# Delete a credential
n8n credentials delete CREDENTIAL_ID
```

### Data Tables

Manage n8n's built-in Data Tables (project database).

```bash
# List all data tables
n8n data-tables list
n8n data-tables list --table
n8n data-tables list --filter "name:contains:orders"

# Show columns for a table
n8n data-tables columns TABLE_ID
n8n data-tables columns TABLE_ID --table

# List rows in a table
n8n data-tables rows TABLE_ID
n8n data-tables rows TABLE_ID --table --limit 10
n8n data-tables rows TABLE_ID --filter "status:eq:active"
n8n data-tables rows TABLE_ID --properties "id,name,status"

# Create a new table with columns
n8n data-tables create "Orders" --column "name:string" --column "total:number"
n8n data-tables create "Flags" --column "key:string" --column "enabled:boolean"

# Insert rows (JSON array argument or piped via stdin)
n8n data-tables insert TABLE_ID '[{"name":"test","value":42}]'
echo '[{"name":"test"}]' | n8n data-tables insert TABLE_ID

# Delete a table
n8n data-tables delete TABLE_ID

# Delete specific rows
n8n data-tables delete-rows TABLE_ID --row-id ROW_ID
n8n data-tables delete-rows TABLE_ID --row-id ROW1 --row-id ROW2
```

### Executions

Query workflow execution history and event logs.

```bash
# Query executions by timeframe
n8n executions list --from 2026-02-12 --table
n8n executions list --from 2026-02-12 --status error --table
n8n executions list --from "2026-02-12T08:00" --to "2026-02-12T09:00"
n8n executions list --workflow-id 17VB4GJjjp0ijgjJ

# Query event log files (audit trail, workflow events, node events)
n8n executions events --from 2026-02-12 --type audit --table
n8n executions events --from 2026-02-12 --type workflow --table
n8n executions events --from 2026-02-12 --name failed
```

### Server Logs

Query n8n server application logs and configuration.

```bash
# View application and error logs
n8n server logs app --lines 100
n8n server logs errors --lines 50

# Combined troubleshooting dump (executions + events + app + error logs)
n8n server logs all --from 2026-02-12
n8n server logs all --from "2026-02-12T08:00" --to "2026-02-12T09:00"

# Show current logging configuration
n8n server logs config

# Set log verbosity (modifies LaunchDaemon plist and restarts n8n)
n8n server logs set-level debug
n8n server logs set-level debug --format json --output console,file
n8n server logs set-level info --no-restart
n8n server logs set-level error --db-logging
```

#### Logs Data Sources

| Subcommand | Source | Method |
|------------|--------|--------|
| `app` | Application stdout (`/var/log/n8n.log`) | SSH tail |
| `errors` | Application stderr (`/var/log/n8n.error.log`) | SSH tail |
| `all` | All 4 sources combined | Structured JSON report |
| `config` | LaunchDaemon plist | SSH plist read |
| `set-level` | LaunchDaemon plist | SSH plist write + launchctl restart |

### Server

Manage the n8n server instance - upgrade, restart, and check version.

```bash
# Upgrade to the latest n8n version
n8n server upgrade

# Upgrade to a specific version
n8n server upgrade 2.10.0

# Upgrade without restarting
n8n server upgrade --skip-restart

# Check the current server version
n8n server version

# Restart the n8n server
n8n server restart
```

### Cache

Manage the local response cache used to speed up repeat queries.

```bash
# Remove all cached responses
n8n cache clear
```

## Configuration

Settings are stored in `.env` (managed by `n8n auth login`):

```bash
ACTIVE=true
API_KEY=           # n8n API key (X-N8N-API-KEY header)
BASE_URL=          # API base URL (e.g., http://localhost:5678/api/v1)
EMAIL=             # UI login email (for internal REST API)
PASSWORD=          # UI login password
SSH_HOST=          # SSH host for server commands (e.g., localhost)
                   # Set to "localhost" when running on the n8n server itself (skips SSH)
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Configuration error |
| 130 | User interrupted (Ctrl+C) |

## Requirements

- Python 3.9+
- Dependencies: typer, python-dotenv, pydantic, requests, rich
- SSH access to the n8n server (for `logs`, `executions events`, `deploy`, and `workflows execute` commands), or set `SSH_HOST=localhost` when running directly on the server

## License

MIT
