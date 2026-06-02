# Asana CLI

Command-line interface for the Asana API - manage projects, tasks, custom fields, and more.

## Installation

The CLI is installed in a virtual environment and accessible globally via symlink.

```bash
cd <cli-tools-root>/asana

# Install in virtual environment
python3 -m venv venv
source venv/bin/activate
pip install -e .
deactivate

# Create symlink for global access
ln -sf <cli-tools-root>/asana/venv/bin/asana ~/.local/bin/asana
```

## Quick Start

```bash
# Configure authentication (get PAT from https://app.asana.com/0/my-apps)
asana auth login --pat YOUR_PAT --workspace YOUR_WORKSPACE_ID

# Check authentication status
asana auth status

# Get current user
asana users get me

# List projects
asana projects list --workspace YOUR_WORKSPACE_ID

# List tasks in a project
asana tasks list --project PROJECT_ID

# Get custom fields for a project
asana custom-fields list --project PROJECT_ID
```

## Commands

### Authentication

```bash
# Configure authentication
asana auth login
asana auth login --pat YOUR_PAT
asana auth login --pat YOUR_PAT --workspace WORKSPACE_ID

# Check status
asana auth status
asana auth status

# Clear credentials
asana auth logout
```

### Cache

```bash
# Inspect cached responses
asana cache status

# Clear cached responses
asana cache clear
```

### Workspaces

```bash
# List all workspaces
asana workspaces list
asana workspaces list

# Get workspace details
asana workspaces get WORKSPACE_ID
asana workspaces get WORKSPACE_ID
```

### Projects

```bash
# List projects in workspace
asana projects list --workspace WORKSPACE_ID
asana projects list

# Get project details
asana projects get PROJECT_ID
asana projects get PROJECT_ID
```

### Tasks

```bash
# List tasks by project or by assignee in a workspace
asana tasks list --project PROJECT_ID
asana tasks list --assignee USER_ID
asana tasks list --assignee me
asana tasks list --workspace WORKSPACE_ID
asana tasks list --project PROJECT_ID
asana tasks list --project PROJECT_ID --limit 50
asana tasks list --project PROJECT_ID --filter "completed:false"

# Search tasks with wildcards
asana tasks search "*keyword*" --project PROJECT_ID
asana tasks search "*bug*" --workspace WORKSPACE_ID
asana tasks search "Fix *" --project PROJECT_ID
asana tasks search "*issue*" --limit 10

# Get task details
asana tasks get TASK_ID
asana tasks get TASK_ID

# Create task
asana tasks create "Task name" --project PROJECT_ID
asana tasks create "Task name" --project PROJECT_ID --assignee me
asana tasks create "Task name" --project PROJECT_ID --notes "Task notes" --due 2024-12-31

# Update task
asana tasks update TASK_ID --name "New name"
asana tasks update TASK_ID --notes "Updated notes"
asana tasks update TASK_ID --assignee USER_ID
asana tasks update TASK_ID --completed true

# Mark task complete
asana tasks complete TASK_ID
```

### Custom Fields

```bash
# List custom fields for a project
asana custom-fields list --project PROJECT_ID
asana custom-fields list --project PROJECT_ID

# Get custom field details with enum options
asana custom-fields get FIELD_ID
asana custom-fields get FIELD_ID
```

### Users

```bash
# List users in workspace
asana users list
asana users list --workspace WORKSPACE_ID
asana users list

# Get user details
asana users get me
asana users get USER_ID
asana users get me
```

### Sections

```bash
# List sections in a project
asana sections list --project PROJECT_ID
asana sections list --project PROJECT_ID

# Get section details
asana sections get SECTION_ID
asana sections get SECTION_ID
```

## Output Formats

All commands support two output formats:

### JSON (default)
Clean JSON output to stdout, perfect for piping to `jq` or other tools:

```bash
asana users get me | jq '.email'
asana projects list | jq '.[].name'
```

Human-readable table format:

```bash
asana projects list
asana tasks list --project PROJECT_ID
```

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--version` | `-v` | Show version and exit |
| `--help` |  | Show help message |
| `--workspace` | `-w` | Workspace ID (for applicable commands) |
| `--project` | `-p` | Project ID (for applicable commands) |

## Configuration

The CLI uses environment variables from the `.env` file in the CLI directory.

### Required Variables

```bash
# Personal Access Token (required)
ASANA_PAT=your_personal_access_token

# Default workspace ID (optional but recommended)
ASANA_WORKSPACE_ID=your_workspace_id
```

### Getting Your Credentials

1. **Personal Access Token**:
   - Visit https://app.asana.com/0/my-apps
   - Click "Create new token"
   - Give it a name and copy the token
   - Run `asana auth login --pat YOUR_TOKEN`

2. **Workspace ID**:
   - Run `asana workspaces list` to see your workspace IDs
   - Add to `.env` file or use `--workspace` flag

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | General error |
| `2` | Authentication error |
| `130` | Interrupted (Ctrl+C) |

## Examples

### List all tasks assigned to you

```bash
asana tasks list --assignee me
```

### Get project custom fields and their enum options

```bash
# List all custom fields
asana custom-fields list --project PROJECT_ID

# Get specific field with enum values
asana custom-fields get FIELD_ID
```

### Create a task with multiple options

```bash
asana tasks create "Review documentation" \
  --project 1212341350620933 \
  --assignee me \
  --notes "Check for accuracy and completeness" \
  --due 2024-12-31
```

### Find your user ID

```bash
asana users get me | jq -r '.gid'
```

### List projects and get first project ID

```bash
asana projects list --workspace YOUR_WORKSPACE_ID | jq -r '.[0].gid'
```

## API Reference

This CLI uses the Asana REST API v1.0. For complete API documentation, see:
https://developers.asana.com/docs

## Requirements

- Python 3.9+
- Dependencies:
  - `typer>=0.9.0`
  - `python-dotenv>=1.0.0`
  - `requests>=2.31.0`

## Development

```bash
# Activate virtual environment
source venv/bin/activate

# Install in editable mode
pip install -e .

# Run tests
pytest

# Install shell completion
asana --install-completion
```

## Notes

- All list commands return arrays of objects
- All get commands return single objects
- The API uses `gid` (global ID) as the identifier field
- Dates should be in `YYYY-MM-DD` format
