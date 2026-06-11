# Reminders CLI

## DESCRIPTION

The `reminders` CLI provides a command-line interface for macOS Reminders.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Features

- List reminder lists (calendars)
- List reminders with filtering by list, completion status, and limit
- Show detailed reminder information
- Create new reminders with due dates, notes, and priority
- Mark reminders as complete/incomplete
- Delete reminders
- Table and JSON output formats

## Installation

### Prerequisites

- macOS (required - uses EventKit framework)
- Python 3.9 or higher
- PyObjC framework

### Install from source

```bash
# Clone or navigate to the repository
cd <cli-tools-root>/reminders

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On macOS/Linux

# Install package
pip install -e .
```

### Global access

The CLI is automatically available globally via:
- Symlink: `~/.local/bin/reminders`
- PowerShell function (if configured)

## Permissions

On first use, macOS will prompt you to grant Reminders access. You must allow this for the CLI to function.

If access is denied, grant it manually:
1. Open System Settings
2. Go to Privacy & Security > Reminders
3. Enable access for Terminal (or your terminal app)

## Usage

### List reminder lists

```bash
# List all reminder lists
reminders lists list

# Display as table
reminders lists list

# Show specific list details
reminders lists show <list-id>
```

### List reminders

```bash
# List all reminders
reminders list

# Display as table
reminders list

# Filter by list
reminders list --list <list-id>

# Show only incomplete reminders
reminders list --incomplete

# Show only completed reminders
reminders list --completed

# Limit results
reminders list --limit 10

# Combine filters
reminders list --list <list-id> --incomplete
```

### Show reminder details

```bash
reminders show <reminder-id>
```

### Create reminder

```bash
# Simple reminder
reminders create "Buy milk"

# With due date
reminders create "Submit report" --due 2025-01-15

# With due date and time
reminders create "Call dentist" --due "2025-01-15 14:00"

# With notes and priority
reminders create "Review PR" \
  --notes "Check security implications" \
  --priority 1 \
  --due 2025-01-16

# In specific list
reminders create "Vacation planning" --list <list-id>
```

### Priority values

- `0` = No priority
- `1` = High priority
- `5` = Medium priority
- `9` = Low priority

### Complete/uncomplete reminders

```bash
# Mark as complete
reminders complete <reminder-id>

# Mark as incomplete
reminders uncomplete <reminder-id>
```

### Delete reminder

```bash
# Delete with confirmation
reminders delete <reminder-id>

# Delete without confirmation
reminders delete <reminder-id> --yes
```

## Command Reference

### Global Options

- `--version`, `-v` - Show version and exit
- `--help` - Show help message

### Lists Commands

- `lists list` - List all reminder lists

- `lists show <list-id>` - Show list details

### Reminder Commands

- `list` - List reminders
  - `--list <id>`, `-l` - Filter by list ID
  - `--completed`, `-c` - Show only completed
  - `--incomplete`, `-i` - Show only incomplete
  - `--limit <n>` - Maximum number of results

- `show <reminder-id>` - Show reminder details

- `create <title>` - Create new reminder
  - `--list <id>`, `-l` - List ID (uses default if not specified)
  - `--notes <text>`, `-n` - Reminder notes
  - `--due <date>`, `-d` - Due date (YYYY-MM-DD or YYYY-MM-DD HH:MM)
  - `--priority <n>`, `-p` - Priority (0=none, 1=high, 5=medium, 9=low)

- `complete <reminder-id>` - Mark as completed

- `uncomplete <reminder-id>` - Mark as incomplete

- `delete <reminder-id>` - Delete reminder
  - `--yes`, `-y` - Skip confirmation

## Technical Details

### EventKit Framework

This CLI uses Apple's EventKit framework via PyObjC to interact with macOS Reminders. The EventKit framework provides access to calendar events and reminders stored in the system's Calendar database.

Key classes used:
- `EKEventStore` - Main interface to calendar/reminder data
- `EKReminder` - Represents a reminder
- `EKCalendar` - Represents a reminder list
- `NSDateComponents` - Date/time representation

### Permissions

The CLI requests `EKEntityTypeReminder` access on first use. This permission persists across sessions once granted.

### Asynchronous Operations

EventKit uses asynchronous callbacks for some operations. This CLI handles async operations using simple polling mechanisms suitable for command-line use.

## Troubleshooting

### "Access to Reminders denied"

Grant access in System Settings > Privacy & Security > Reminders

### "PyObjC is required"

Install PyObjC:
```bash
pip install pyobjc-framework-EventKit
```

### Reminders not appearing

Wait a moment and retry - EventKit fetching is asynchronous and may take a second to complete.

## Development

### Project Structure

```
reminders/
├── reminders_cli/
│   ├── __init__.py
│   ├── client.py           # EventKit client
│   ├── main.py             # CLI entry point
│   ├── output.py           # Output formatting
│   └── commands/
│       ├── __init__.py
│       └── lists.py        # List commands
├── pyproject.toml
├── README.md
└── .gitignore
```

### Testing

Ensure you have test reminders in your macOS Reminders app, then:

```bash
# Test list operations
reminders lists list

# Test reminder operations
reminders list
reminders create "Test reminder"
```

## References

- [Apple EventKit Documentation](https://developer.apple.com/documentation/eventkit)
- [PyObjC Documentation](https://pyobjc.readthedocs.io/)
- [PyObjC EventKit Framework](https://pypi.org/project/pyobjc-framework-EventKit/)

## License

MIT
