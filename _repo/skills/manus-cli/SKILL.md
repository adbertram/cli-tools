---
name: "manus-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute manus operations using the `manus` CLI tool. CLI interface for Manus AI API -- create and manage AI tasks, profiles, and authentication. Triggers: manus, manus cli, manus task, manus ai, create manus task, run manus, manus agent, list manus tasks, manus auth profiles"
---

<objective>
Execute manus operations using the `manus` CLI. All manus interactions should use this CLI.
</objective>

<quick_start>
The `manus` CLI follows this pattern:
```bash
manus <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check auth status | `manus auth status` |
| Create a task | `manus task create "Your prompt here"` |
| Create task (no wait) | `manus task create "Prompt" --no-wait` |
| Send a follow-up | `manus task send TASK_ID "Follow-up"` |
| Get task metadata | `manus task get TASK_ID` |
| List recent tasks | `manus task list --table` |
| List task messages | `manus task messages TASK_ID --limit 20` |
| Confirm a waiting task | `manus task confirm TASK_ID EVENT_ID` |
| List profiles | `manus auth profiles list --table` |
| Set default profile | `manus auth profiles select PROFILE_NAME` |
| Inspect cache commands | `manus cache --help` |

Auth status output uses the shared profile shape: `{"profiles":[{"name":"default","authenticated":true,"credential_types":{...}}]}`. Read `auth profiles[].authenticated` for per-profile status; do not expect a flat top-level `authenticated` field.
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `manus` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Manage API authentication (login, logout, status, refresh, test)
- **task** -- Manage Manus API v2 tasks (create, send, continue alias, get, wait, list, messages, update, stop, delete, confirm)
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
