# Reminders CLI - Claude Instructions

Always read the README.md file first when working with this CLI tool. It contains:

- Installation and setup instructions
- Available commands and usage examples
- Permission requirements for macOS Reminders
- EventKit framework documentation references

## Key Information

- **No authentication required** - Uses macOS EventKit framework
- **Permission grant needed** - macOS will prompt on first use to grant Reminders access
- **PyObjC dependency** - Requires pyobjc-framework-EventKit and pyobjc-framework-Cocoa
- **macOS only** - This CLI only works on macOS due to EventKit dependency

## Common Tasks

### List all reminder lists
```bash
reminders lists list
```

### List incomplete reminders
```bash
reminders list --incomplete
```

### Create a reminder with due date
```bash
reminders create "Task name" --due "2025-01-15 14:00" --priority 1
```

### Complete a reminder
```bash
reminders complete <reminder-id>
```

## Technical Notes

- Uses PyObjC to bridge Python and Objective-C EventKit framework
- Asynchronous EventKit operations handled via polling (suitable for CLI use)
- Reminder IDs are calendar item identifiers from EventKit
- Priority values: 0=none, 1=high, 5=medium, 9=low
