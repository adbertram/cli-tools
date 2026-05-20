---
name: "notifier-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute notifier operations using the `notifier` CLI tool. CLI wrapper for terminal-notifier -- macOS desktop notifications. Triggers: notifier, notifier cli, send notification, desktop notification, notify me, mac notification, alert notification, notification sound"
---

<objective>
Execute notifier operations using the `notifier` CLI. All desktop notification interactions should use this CLI.
</objective>

<quick_start>
The `notifier` CLI follows this pattern:
```bash
notifier <command> [options]
```

| Task | Command |
|------|---------|
| Send a notification | `notifier send -m "message"` |
| Send with title and sound | `notifier send -m "Done" -T "Build" --sound default` |
| Send bypassing DND | `notifier send -m "Urgent" --ignore-dnd` |
| Check installation | `notifier auth status` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `notifier` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **send** -- Send a macOS desktop notification with optional title, subtitle, sound, and DND override
- **auth** -- Verify terminal-notifier installation (login, status)
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
