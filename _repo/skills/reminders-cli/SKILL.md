---
name: reminders-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute reminders operations using the `reminders` CLI tool.
  CLI for managing macOS Reminders.
  Triggers: reminders, reminders cli, reminders app, create reminder, list reminders, complete reminder, my reminders, reminder lists, macos reminders
---

<objective>
Execute reminders operations using the `reminders` CLI. All macOS Reminders interactions should use this CLI.
</objective>

<quick_start>
The `reminders` CLI follows this pattern:
```bash
reminders <action> [arguments] [options]
reminders lists <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List reminders | `reminders list` |
| Show a reminder | `reminders show REMINDER_ID` |
| Create a reminder | `reminders create "Buy groceries"` |
| Complete a reminder | `reminders complete REMINDER_ID` |
| Delete a reminder | `reminders delete REMINDER_ID` |
| List reminder lists | `reminders lists list` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `reminders` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **list** -- List reminders with optional filtering
- **show** -- Show details of a specific reminder
- **create** -- Create a new reminder
- **complete** -- Mark a reminder as completed
- **uncomplete** -- Mark a reminder as incomplete
- **delete** -- Delete a reminder
- **lists** -- Manage reminder lists (list, show)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>
