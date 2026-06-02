# Things CLI

A command-line interface for Things 3 on macOS. Uses SQLite for fast reads and AppleScript for reliable writes.

## Installation

```bash
cd things
pip install -e .
```

After installation, the `things` command will be available in your terminal.

## Quick Start

```bash
# Check database access
things auth status

# List todos
things todos list

# List today's todos
things todos list --when today

# Create a todo
things todos create "Buy groceries"

# Complete a todo
things todos complete UUID
```

## Commands

### Authentication / Status

Things CLI requires no API key - it reads directly from the SQLite database and writes via AppleScript.

```bash
# Check database access and app status
things auth status

# Verify database access (no-op, just for compatibility)
things auth login

# No credentials to clear
things auth logout
```

**Note:** Write operations use AppleScript, which briefly activates the Things app window.

### Todos

```bash
# List todos (JSON output - default)
things todos list

# List with table format
things todos list --table

# Filter by when: inbox, anytime, someday, today, upcoming
things todos list --when today
things todos list --when anytime

# Filter by status: incomplete, completed
things todos list --status incomplete

# Filter by project or area
things todos list --project PROJECT_UUID
things todos list --area AREA_UUID

# Filter by tag
things todos list --tag "Work"

# Exclude todos tagged with one or more tags (case-sensitive, repeatable, union exclusion)
things todos list --exclude-tag WF
things todos list --exclude-tag WF --exclude-tag Archive
things todos list --tag "Work" --exclude-tag WF  # Work-tagged that are NOT WF-tagged

# Limit results
things todos list --limit 10

# Select specific fields
things todos list --properties "uuid,title,status"

# Get a specific todo
things todos get UUID
things todos get UUID --table

# Search todos by title
things todos search "groceries"
things todos search "meeting" --table

# Create a todo
things todos create "Buy groceries"
things todos create "Review document" --when today
things todos create "Call John" --deadline 2024-12-31
things todos create "Task" --project PROJECT_UUID --tags "work,urgent"
things todos create "Notes task" --notes "Additional details here"

# Complete/uncomplete a todo
things todos complete UUID
things todos uncomplete UUID

# Delete a todo (moves to trash)
things todos delete UUID
things todos delete UUID --yes  # Skip confirmation
```

### Projects

```bash
# List projects
things projects list
things projects list --table

# Filter by area or status
things projects list --area AREA_UUID
things projects list --status incomplete

# Exclude projects tagged with one or more tags (case-sensitive, repeatable, union exclusion)
things projects list --exclude-tag WF
things projects list --exclude-tag WF --exclude-tag Archive

# Get a specific project
things projects get UUID

# Search projects by title
things projects search "home"

# Create a project
things projects create "Home Renovation"
things projects create "Q1 Goals" --area AREA_UUID
things projects create "Backlog Project" --when someday

# Complete a project
things projects complete UUID

# Delete a project (moves to trash)
things projects delete UUID
things projects delete UUID --yes
```

### Areas

```bash
# List areas
things areas list
things areas list --table

# Get a specific area
things areas get UUID

# Search areas by title
things areas search "work"

# Create an area
things areas create "Work"
things areas create "Personal"
```

### Tags

```bash
# List tags
things tags list
things tags list --table

# Get a specific tag
things tags get UUID

# Search tags by title
things tags search "urgent"
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping
- **Table** (`--table`/`-t`): Human-readable table format

### JSON Output Example

```bash
things todos list --limit 2
```

```json
[
  {
    "uuid": "ABC123...",
    "title": "Buy groceries",
    "type": 0,
    "status": 0,
    "start": 1,
    ...
  }
]
```

### Table Output Example

```bash
things todos list --table --limit 5
```

## Options Reference

### Global Options

| Option | Short | Description |
|--------|-------|-------------|
| `--version` | `-v` | Show version and exit |

### Common List Options

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display as table |
| `--limit` | `-l` | Maximum number of results (default: 100) |
| `--filter` | `-f` | Filter results (field:op:value) |
| `--properties` | `-p` | Comma-separated fields to include |

### Todo-Specific Options

| Option | Short | Description |
|--------|-------|-------------|
| `--when` | `-w` | Filter by when: inbox, anytime, someday, today, upcoming |
| `--status` | `-s` | Filter by status: incomplete, completed |
| `--tag` | | Filter by tag title |
| `--exclude-tag` | | Drop items tagged with this tag (case-sensitive, repeatable; union exclusion). Also available on `things projects list`. |
| `--area` | | Filter by area UUID |
| `--project` | | Filter by project UUID |

## Database Location

Things CLI automatically discovers the Things 3 SQLite database at:

```
~/Library/Group Containers/JLMPQHK86H.com.culturedcode.ThingsMac/ThingsData-*/Things Database.thingsdatabase/main.sqlite
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/database access error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### List Todos and Filter with jq

```bash
things todos list | jq '.[].title'
```

### Export Todos to JSON File

```bash
things todos list --limit 200 > todos.json
```

### Get Todo UUIDs for Scripting

```bash
things todos list --properties "uuid" | jq -r '.[].uuid'
```

### Create Multiple Todos

```bash
for task in "Task 1" "Task 2" "Task 3"; do
  things todos create "$task"
done
```

## Models

This CLI uses Pydantic models for type-safe data handling.

### Available Models

| Model | Description |
|-------|-------------|
| `Task` | Todo item (TMTask where type=0) |
| `Project` | Project (TMTask where type=1) |
| `Area` | Area/category (TMArea) |
| `Tag` | Tag with hierarchy (TMTag) |
| `ChecklistItem` | Checklist item within a task |
| `AuthStatus` | Database access status |

### Enums

| Enum | Values |
|------|--------|
| `TaskType` | TODO=0, PROJECT=1, HEADING=2 |
| `TaskStatus` | INCOMPLETE=0, COMPLETED=3 |
| `StartType` | NOT_SET=0 (Inbox), ANYTIME=1, SOMEDAY=2 |

## Requirements

- macOS with Things 3 installed
- Python 3.9+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - pydantic
  - rich

## Limitations

- **Write operations activate Things window** - AppleScript briefly brings Things to foreground
- **Read-only for Tags** - Things 3 manages tag creation through the UI
- **UUIDs only** - no natural language matching for item lookups

## License

MIT
