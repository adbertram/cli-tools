# n8n Node

Convert standardized Python CLI tools into n8n community node packages, manage credentials, deploy nodes, and query n8n server logs.

## Installation

```bash
cd n8n-node
pip install -e .
```

## Quick Start

```bash
# Check configuration
n8n-node auth status

# List available CLI tools
n8n-node tools list

# Convert a CLI tool to an n8n node package
n8n-node convert-cli-tool brickowl

# Deploy to the n8n server
n8n-node deploy brickowl

# Test the installed node
n8n-node test brickowl -r orders -o list

# View recent failed executions
n8n-node logs executions --from 2026-02-12 --status error --table
```

## Commands

### Authentication

```bash
# Configure directories
n8n-node auth login --tools-dir ~/cli-tools --output-dir ~/n8n-nodes

# Check configuration status
n8n-node auth status

# Clear configuration
n8n-node auth logout
```

### Tools

```bash
# List available CLI tools
n8n-node tools list
n8n-node tools list --table

# Inspect a CLI tool's metadata
n8n-node tools get brickowl
n8n-node tools get brickowl --table
```

### Convert

```bash
# Convert a CLI tool to an n8n node package
n8n-node convert-cli-tool brickowl
n8n-node convert-cli-tool brickowl --force          # Overwrite existing
n8n-node convert-cli-tool brickowl --output-dir ./out
```

### Nodes

```bash
# List generated node packages
n8n-node nodes list
n8n-node nodes list --table

# List nodes installed on the n8n server
n8n-node nodes list --type community
n8n-node nodes list --type default

# Get details for a generated package
n8n-node nodes get brickowl
```

### Deploy

```bash
# Deploy a node package to the n8n server
n8n-node deploy brickowl
n8n-node deploy brickowl --skip-build
```

### Test

```bash
# Test an installed node on the n8n server
n8n-node test brickowl -r orders -o list
n8n-node test brickowl -p '{"zone":"example.com"}'
n8n-node test brickowl --no-cleanup                  # Keep test workflow
n8n-node test brickowl --timeout 120
```

### Credentials

```bash
# List credentials on the server
n8n-node credentials list
n8n-node credentials list --table

# Create a credential
n8n-node credentials create brickowlApi '{"apiKey":"abc123"}'

# Get credential type schema
n8n-node credentials schema brickowlApi

# Delete a credential
n8n-node credentials delete CREDENTIAL_ID
```

### Logs

Query n8n server logs, execution history, and event data for troubleshooting.

```bash
# Query executions by timeframe
n8n-node logs executions --from 2026-02-12 --table
n8n-node logs executions --from 2026-02-12 --status error --table
n8n-node logs executions --from "2026-02-12T08:00" --to "2026-02-12T09:00"
n8n-node logs executions --workflow-id 17VB4GJjjp0ijgjJ

# Query event log files (audit trail, workflow events, node events)
n8n-node logs events --from 2026-02-12 --type audit --table
n8n-node logs events --from 2026-02-12 --type workflow --table
n8n-node logs events --from 2026-02-12 --name failed

# View application and error logs
n8n-node logs app --lines 100
n8n-node logs errors --lines 50

# Combined troubleshooting dump (all 4 sources)
n8n-node logs all --from 2026-02-12
n8n-node logs all --from "2026-02-12T08:00" --to "2026-02-12T09:00"

# Show current logging configuration
n8n-node logs config

# Set log verbosity (modifies LaunchDaemon plist and restarts n8n)
n8n-node logs set-level debug
n8n-node logs set-level debug --format json --output console,file
n8n-node logs set-level info --no-restart
n8n-node logs set-level error --db-logging
```

#### Logs Data Sources

| Subcommand | Source | Method |
|------------|--------|--------|
| `executions` | Execution history (API) | Paginated API with client-side date filter |
| `events` | Event log files (`n8nEventLog*.log`) | SSH + server-side Python parser |
| `app` | Application stdout (`/var/log/n8n.log`) | SSH tail |
| `errors` | Application stderr (`/var/log/n8n.error.log`) | SSH tail |
| `all` | All 4 sources combined | Structured JSON report |
| `config` | LaunchDaemon plist | SSH plist read |
| `set-level` | LaunchDaemon plist | SSH plist write + launchctl restart |

## Configuration

Settings are stored in `.env`:

```bash
# Path to CLI tools directory (default: ~/Dropbox/GitRepos/cli-tools)
N8N_CONVERTER_CLI_TOOLS_DIR=

# Path for generated n8n node packages (default: ~/Dropbox/GitRepos/n8n-nodes)
N8N_CONVERTER_OUTPUT_DIR=
```

n8n server connection is configured in `~/.claude/skills/n8n/.env`:

```bash
N8N_API_KEY=       # API key (X-N8N-API-KEY header)
N8N_BASE=          # API base URL (e.g., http://100.117.198.37:5678/api/v1)
N8N_EMAIL=         # UI login email (for internal REST API)
N8N_PASSWORD=      # UI login password
N8N_SSH_HOST=      # SSH host for log commands (e.g., adam-server)
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
- SSH access to the n8n server (for `logs` commands)

## License

MIT

## Additional Commands

### Executing

```bash
n8n-node executing --help
```

### Cache

```bash
n8n-node cache --help
```
