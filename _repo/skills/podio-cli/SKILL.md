---
name: podio-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute podio operations using the `podio` CLI tool.
  CLI interface for Podio API - Manage apps, items, tasks, and more.
  Triggers: podio, podio cli, podio items, podio apps, podio tasks, list podio items, podio workspace, podio conversations, podio files, podio webhooks, my podio
---

<objective>
Execute podio operations using the `podio` CLI. All podio interactions should use this CLI.
</objective>

<quick_start>
The `podio` CLI follows this pattern:
```bash
podio <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check auth status | `podio auth status` |
| List apps in workspace | `podio app list --table` |
| Get app fields | `podio app get APP_ID --fields` |
| List items in app | `podio item list APP_ID --table` |
| Get item details | `podio item get ITEM_ID` |
| Get item field values | `podio item values ITEM_ID` |
| Create a task | `podio task create "Task text"` |
| Upload a file | `podio file upload ./file.pdf` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `podio` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **item** -- Manage items (get, list, create, update, delete, values, field-value)
- **app** -- Manage applications (get, list, items, activate, deactivate, create, update, export, field)
- **task** -- Manage tasks (list, get, create, complete, delete, update, label)
- **space** -- Manage spaces (get, list)
- **org** -- Manage organizations (list, get)
- **auth** -- Authentication (login, logout, status, refresh, test)
- **comment** -- Manage comments (create, list, get, update, delete)
- **webhook** -- Manage webhooks (get, create, list, verify, validate, update, delete, field)
- **conversation** -- Messaging (list, get, create, reply, mark-read, mark-unread, star, unstar, leave, search, events, on-object, participant)
- **file** -- File operations (upload, attach, list, get, download, copy)
- **webform** -- Manage webforms (list, get, submit, field, attachments)
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
