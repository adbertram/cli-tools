---
name: udemy-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute udemy operations using the `udemy` CLI tool.
  Udemy Instructor API CLI
  Triggers: udemy, udemy cli, udemy courses, udemy instructor courses, list udemy courses, get udemy course, udemy auth, udemy auth profiles, my udemy courses
---

<objective>
Execute udemy operations using the `udemy` CLI. All Udemy Instructor API interactions should use this CLI.
</objective>

<quick_start>
The `udemy` CLI follows this pattern:
```bash
udemy <command-group> <action> [arguments] [options]
```

| Command | Purpose |
|---|---|
| `udemy auth login` | Save the Udemy Instructor API bearer token. |
| `udemy auth status` | Check the active auth profile and masked token status. |
| `udemy auth profiles list` | List configured auth profiles. |
| `udemy courses list --limit 100` | List instructor-taught courses as JSON. |
| `udemy courses list --table` | List instructor-taught courses as a table. |
| `udemy courses get COURSE_ID` | Get one instructor-taught course by numeric course ID. |
| `udemy cache clear` | Clear cached CLI responses. |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `udemy` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- `courses` — list and get instructor-taught Udemy courses through the official Instructor API.
- `auth` — save bearer tokens, inspect auth status, test credentials, and manage profiles.
- `auth profiles` — create, list, inspect, select, and delete named credential profiles.
- `cache` — clear local response cache files.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** — Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>
