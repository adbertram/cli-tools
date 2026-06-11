---
name: lastpass-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute lastpass operations using the `lastpass` CLI tool.
  LastPass password manager CLI wrapper for retrieving passwords, usernames, and vault entries.
  Triggers: lastpass, lastpass cli, lastpass password, lastpass vault, get password from lastpass, lastpass credentials, lastpass login, list lastpass entries, search lastpass, lastpass username
---

<objective>
Execute lastpass operations using the `lastpass` CLI. All lastpass interactions should use this CLI.
</objective>

<quick_start>
The `lastpass` CLI follows this pattern:
```bash
lastpass <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check auth status | `lastpass auth status` |
| List vault entries | `lastpass items list --table` |
| List entries in folder | `lastpass items list Work --table` |
| List payment cards | `lastpass items list --category "Payment Cards" --table` |
| Search entries | `lastpass items list --filter "name:like:%github%"` |
| Get entry details | `lastpass items get <id-or-name>` |
| Get password only | `lastpass items password <id-or-name>` |
| Copy password to clipboard | `lastpass items password <id-or-name> --clip` |
| Get username only | `lastpass items username <id-or-name>` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `lastpass` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Manage LastPass authentication (login, logout, status, sync)
- **items** -- Manage vault entries (list, get, password, username)
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
