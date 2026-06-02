# MindMeister CLI

A command-line interface for the [MindMeister API](https://developers.mindmeister.com/docs) - manage mind maps from the terminal.

## Installation

```bash
cd mindmeister
pip install -e .
```

After installation, the `mindmeister` command will be available in your terminal.

## Quick Start

```bash
# Get your Personal Access Token at: https://www.mindmeister.com/api

# Authenticate with MindMeister
mindmeister auth login

# Check authentication status
mindmeister auth status

# List all mind maps
mindmeister maps list

# Get a specific map with all ideas/nodes
mindmeister maps get MAP_ID
```

## Commands

### Authentication

```bash
# Login with Personal Access Token
mindmeister auth login
mindmeister auth login --token YOUR_TOKEN
mindmeister auth login --force  # Re-authenticate

# Check authentication status
mindmeister auth status
mindmeister auth status --table

# Clear stored credentials
mindmeister auth logout
```

### Maps

```bash
# List all mind maps
mindmeister maps list
mindmeister maps list --table
mindmeister maps list --limit 10
mindmeister maps list --properties "id,title,modified"

# Get a specific map (includes all ideas/nodes)
mindmeister maps get MAP_ID
mindmeister maps get MAP_ID --table
mindmeister maps get MAP_ID --properties "id,title,node_count"

# Create a new empty map
mindmeister maps create --title "My New Map"
mindmeister maps create -T "Project Planning"

# Update map metadata
mindmeister maps update MAP_ID --title "Updated Title"
mindmeister maps update MAP_ID --description "New description"
mindmeister maps update MAP_ID -T "New Title" -d "New description"

# Duplicate a map
mindmeister maps duplicate MAP_ID

# Delete a map
mindmeister maps delete MAP_ID
mindmeister maps delete MAP_ID --force  # Skip confirmation

# Export map (get download URLs)
mindmeister maps export MAP_ID
mindmeister maps export MAP_ID --table
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping
- **Table** (`--table`/`-t`): Human-readable table format

### JSON Output Example

```bash
mindmeister maps list --limit 2
```

```json
[
  {
    "id": "123456",
    "title": "Project Ideas",
    "revision": "5",
    "modified": "2025-01-15 10:30:00"
  },
  {
    "id": "789012",
    "title": "Meeting Notes",
    "revision": "3",
    "modified": "2025-01-14 14:00:00"
  }
]
```

### Table Output Example

```bash
mindmeister maps list --limit 5 --table
```

```
ID       Title            Modified              Rev
123456   Project Ideas    2025-01-15 10:30:00   5
789012   Meeting Notes    2025-01-14 14:00:00   3
```

## Options Reference

### Global Options

| Option | Short | Description |
|--------|-------|-------------|
| `--version` | `-v` | Show version and exit |
| `--help` | | Show command help |

### List Command Options

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display as table |
| `--limit` | `-l` | Maximum number of results (default: 100) |
| `--filter` | `-f` | Filter results (field:op:value) |
| `--properties` | `-p` | Comma-separated fields to include |

### Get Command Options

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display summary as table |
| `--properties` | `-p` | Comma-separated fields to include |

### Auth Login Options

| Option | Short | Description |
|--------|-------|-------------|
| `--token` | `-t` | Personal Access Token |
| `--force` | `-F` | Clear existing and re-authenticate |

## Configuration

Authentication profile files live under `~/.local/share/cli-tools/mindmeister/authentication_profiles/<profile>/`; non-auth defaults live in `~/.local/share/cli-tools/mindmeister/.env`:

```bash
# Personal Access Token (get at https://www.mindmeister.com/api)
MINDMEISTER_ACCESS_TOKEN=your_personal_access_token

# Optional: API base URL (default shown)
MINDMEISTER_BASE_URL=https://www.mindmeister.com/services/rest/oauth2
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### List Maps and Extract IDs with jq

```bash
mindmeister maps list | jq '.[].id'
```

### Get Map Title and Node Count

```bash
mindmeister maps get 123456 --properties "title,node_count"
```

### Export All Maps to JSON File

```bash
mindmeister maps list --limit 200 > maps.json
```

### Create and Delete a Test Map

```bash
# Create a map and capture the ID
NEW_ID=$(mindmeister maps create -T "Test Map" | jq -r '.id')

# Delete the map
mindmeister maps delete $NEW_ID --force
```

## Models

This CLI uses Pydantic models for type-safe data handling. All commands return strongly-typed models.

### Available Models

| Model | Description | Required Fields |
|-------|-------------|-----------------|
| `Map` | Basic map metadata for list commands | `id`, `title` |
| `MapDetail` | Full map with ideas for get commands | `id`, `title` |
| `Idea` | Individual node within a map | `id` |
| `ExportUrls` | Export URLs for different formats | - |

### Model Architecture

```
models/
├── __init__.py      # Exports all models
├── base.py          # CLIModel base class
└── item.py          # Map, MapDetail, Idea, ExportUrls models
```

## API Reference

This CLI uses the MindMeister v1 API with OAuth2 authentication.

| API Method | CLI Command |
|------------|-------------|
| `mm.maps.getList` | `maps list` |
| `mm.maps.getMap` | `maps get` |
| `mm.maps.add` | `maps create` |
| `mm.maps.setMetaData` | `maps update` |
| `mm.maps.duplicate` | `maps duplicate` |
| `mm.maps.delete` | `maps delete` |
| `mm.maps.export` | `maps export` |

## Requirements

- Python 3.9+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests
  - pydantic

## License

MIT

## Additional Commands

### Cache

```bash
mindmeister cache --help
```
