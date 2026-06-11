---
name: hyvor-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute hyvor operations using the `hyvor` CLI tool.
  CLI interface for Hyvor Talk API -- manage blog comments, moderate spam, reply to comments, and handle profiles.
  Triggers: hyvor, hyvor cli, hyvor comments, hyvor talk, list hyvor comments, reply to comment, moderate comments, hyvor spam, pending comments, publish comment
---

<objective>
Execute hyvor operations using the `hyvor` CLI. All Hyvor Talk interactions should use this CLI.
</objective>

<quick_start>
The `hyvor` CLI follows this pattern:
```bash
hyvor <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List all comments | `hyvor comments list --table` |
| List pending comments | `hyvor comments list --status pending --table` |
| List unreplied comments | `hyvor comments list --not-replied --table` |
| Get a specific comment | `hyvor comments get 12345 --table` |
| Reply to a comment | `hyvor comments reply 12345 "Thanks for your feedback!"` |
| Mark comment as spam | `hyvor comments spam 12345` |
| Publish pending comment | `hyvor comments publish 12345` |
| Check auth status | `hyvor auth status --table` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `hyvor` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- API authentication (login, logout, status, refresh, test)
- **comments** -- Comment moderation (list, get, reply, update, delete, spam, publish)
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
