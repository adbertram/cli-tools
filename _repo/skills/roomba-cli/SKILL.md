---
name: roomba-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute roomba operations using the `roomba` CLI tool.
  CLI to control iRobot Roomba vacuums.
  Triggers: roomba, roomba cli, roomba vacuum, start roomba, stop roomba, dock roomba, roomba status, roomba battery, vacuum cleaner, irobot
---

<objective>
Execute roomba operations using the `roomba` CLI. All Roomba vacuum interactions should use this CLI.
</objective>

<quick_start>
The `roomba` CLI follows this pattern:
```bash
roomba <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Quick status check | `roomba status` |
| List robots | `roomba robots list --table` |
| Start cleaning | `roomba control start` |
| Stop cleaning | `roomba control stop` |
| Send to dock | `roomba control dock` |
| Find robot (beep) | `roomba control find` |
| Evacuate bin | `roomba control evac` |
| Detailed status | `roomba control status` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `roomba` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **status** -- Quick robot status (shortcut for control status)
- **robots** -- List and view robot information (list, get)
- **control** -- Control robots (start, stop, pause, resume, dock, find, evac, status)
- **auth** -- Manage authentication and discovery (login, logout, status, refresh, test)
- **auth** -- Authentication commands and nested `auth profiles` management
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
