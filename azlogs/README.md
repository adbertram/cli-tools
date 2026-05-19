# Azlogs CLI

Download, parse, and analyze Azure Web App logs via the [Kudu REST API](https://learn.microsoft.com/en-us/azure/app-service/resources-kudu).

## Installation

```bash
cd azlogs
pip install -e .
```

After installation, the `azlogs` command will be available in your terminal.

## Prerequisites

- **Azure CLI** (`az`) installed and authenticated (`az login`)
- Access to the target Azure Web App's publishing credentials

## Quick Start

```bash
# Download logs directly (pass app + resource group inline)
azlogs --app mywebapp --resource-group myrg packages download

# Or configure once via auth login, then omit --app/--resource-group
azlogs auth login --app mywebapp --resource-group myrg
azlogs packages download

# List downloaded packages
azlogs packages list --table

# View log entries (filter for errors)
azlogs entries list 2026-02-10_09-40-16 --filter "level:eq:ERROR" --table

# Generate HTML report
azlogs report generate 2026-02-10_09-40-16 --open
```

## Global Options

| Option | Short | Description |
|--------|-------|-------------|
| `--app` | `-a` | Azure Web App name (overrides .env) |
| `--resource-group` | `-g` | Azure Resource Group (overrides .env) |
| `--version` | `-v` | Show version and exit |

These can be passed before any subcommand. Values are also read from `AZLOGS_APP_NAME` and `AZLOGS_RESOURCE_GROUP` environment variables or the `.env` file.

## Commands

### Authentication

```bash
# Configure app name and resource group (verifies az CLI auth)
azlogs auth login
azlogs auth login --app mywebapp --resource-group myrg

# Check configuration and az CLI status
azlogs auth status
azlogs auth status --table

# Clear stored configuration
azlogs auth logout

# Force re-configure
azlogs auth login --force
```

### Packages

```bash
# Download fresh logs from Azure (auto-parses + generates report)
azlogs packages download

# List all downloaded packages
azlogs packages list
azlogs packages list --table
azlogs packages list --limit 5
azlogs packages list --filter "has_merged:true"
azlogs packages list --properties "name,entry_count,created"

# Get details of a specific package
azlogs packages get 2026-02-10_09-40-16
azlogs packages get 2026-02-10_09-40-16 --table

# Re-parse an existing package
azlogs packages parse 2026-02-10_09-40-16
azlogs packages parse 2026-02-10_09-40-16 --format csv

# Validate merged output completeness
azlogs packages validate 2026-02-10_09-40-16

# Delete a package
azlogs packages delete 2026-02-10_09-40-16
azlogs packages delete 2026-02-10_09-40-16 --yes
```

### Entries

```bash
# List log entries from a package
azlogs entries list 2026-02-10_09-40-16
azlogs entries list 2026-02-10_09-40-16 --table --limit 20

# Filter entries
azlogs entries list 2026-02-10_09-40-16 --filter "level:eq:ERROR"
azlogs entries list 2026-02-10_09-40-16 --filter "entity:eq:app_log"
azlogs entries list 2026-02-10_09-40-16 --filter "service:ilike:%automation%"
azlogs entries list 2026-02-10_09-40-16 --filter "level:in:ERROR|WARNING"

# Select specific fields
azlogs entries list 2026-02-10_09-40-16 --properties "timestamp,level,service,message"

# Get a specific entry
azlogs entries get 2026-02-10_09-40-16 "LogFiles/ciem.log" 42

# Pipe to jq for processing
azlogs entries list 2026-02-10_09-40-16 --filter "level:eq:ERROR" | jq '.[].message'
```

### Report

```bash
# Generate HTML report
azlogs report generate 2026-02-10_09-40-16

# Generate and open in browser
azlogs report generate 2026-02-10_09-40-16 --open
```

## Filter Syntax

All `list` commands support `--filter` / `-f` with this syntax:

```
field:operator:value
```

| Operator | Meaning | Example |
|----------|---------|---------|
| `eq` | Equals (default) | `level:ERROR` or `level:eq:ERROR` |
| `ne` | Not equals | `level:ne:DEBUG` |
| `gt` | Greater than | `timestamp:gt:2026-02-10T00:00:00` |
| `gte` | Greater or equal | `line_number:gte:100` |
| `lt` | Less than | `line_number:lt:50` |
| `lte` | Less or equal | `entry_count:lte:1000` |
| `in` | In list | `level:in:ERROR\|WARNING` |
| `nin` | Not in list | `entity:nin:kudu_trace\|scm_sidecar` |
| `like` | Contains (case-sensitive) | `message:like:%exception%` |
| `ilike` | Contains (case-insensitive) | `service:ilike:%automation%` |

Multiple `--filter` flags use OR logic between groups, AND within comma-separated values.

## Entity Types

| Entity | Description | Source |
|--------|-------------|--------|
| `platform_orchestrator` | Platform Docker orchestrator | `*_docker.log` |
| `app_container` | Application container | `*_default_docker.log` |
| `scm_sidecar` | SCM/Kudu sidecar container | `*_default_scm_docker.log` |
| `app_log` | Application log | `ciem.log` |
| `kudu_trace` | Kudu trace logs | `kudu/trace/*.txt` |

## Log Levels

`ERROR`, `WARNING`, `INFO`, `DEBUG`, `UNKNOWN`

## Output Formats

- **JSON** (default): Machine-readable output for scripting
- **Table** (`--table`/`-t`): Human-readable formatted table

JSON to stdout enables clean piping: `azlogs entries list PKG | jq '.[]'`

## Configuration

Credentials stored in `.env` file:

```bash
AZLOGS_APP_NAME=mywebapp
AZLOGS_RESOURCE_GROUP=myrg
# AZLOGS_DATA_DIR=/custom/path  # Optional
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/configuration error |
| 130 | User interrupted (Ctrl+C) |

## Models

| Model | Description | Required Fields |
|-------|-------------|-----------------|
| `LogEntry` | Parsed log entry | `timestamp`, `entity`, `service`, `level`, `message`, `source_file`, `line_number` |
| `LogPackage` | Downloaded log package | `name`, `path`, `created` |
| `LogPackageDetail` | Package with file breakdown | `name`, `path`, `created` |
| `LogFile` | Classified log file | `path`, `entity` |
| `ValidationResult` | Validation outcome | `is_valid` |

## Requirements

- Python 3.9+
- Azure CLI (`az`) installed and authenticated
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests
  - pydantic

## License

MIT

## Cache

```bash
azlogs cache status
azlogs cache clear
```
