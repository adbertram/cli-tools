---
name: taskerdata-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute Taskerdata operations using the `taskerdata` CLI tool.
  CLI interface for Taskerdata.
  Triggers: taskerdata, taskerdata cli
---

<objective>
Execute Taskerdata operations using the `taskerdata` CLI. All Taskerdata interactions should use this CLI.
</objective>

<quick_start>
The `taskerdata` CLI follows this pattern:
```bash
taskerdata <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Configure authentication credentials | `taskerdata auth login` |
| Clear stored credentials and browser sessions | `taskerdata auth logout` |
| Create a new profile from .env.example template | `taskerdata auth profiles create <NAME>` |
| Delete a profile and its data | `taskerdata auth profiles delete <NAME>` |
| Get details for a specific profile | `taskerdata auth profiles get <NAME>` |
| List all profiles and show their auth types and active state | `taskerdata auth profiles list` |
| Delete a profile and its data | `taskerdata auth profiles remove <NAME>` |
| Rename a profile, re-keying its secrets to the new profile name | `taskerdata auth profiles rename <OLD> <NEW>` |
| Activate a profile within its auth type | `taskerdata auth profiles select <NAME>` |
| Check authentication status across profiles | `taskerdata auth status` |
| Test authentication by verifying credentials work across profiles | `taskerdata auth test` |
| Remove all cached responses | `taskerdata cache clear` |
| Apply to / pick up a TaskerData task | `taskerdata tasks apply <TASK_ID>` |
| Get full detail for a specific task | `taskerdata tasks get <TASK_ID>` |
| List open/available tasks for the logged-in worker | `taskerdata tasks list` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `taskerdata` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `taskerdata --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Manage taskerdata authentication (subcommands: login, logout, profiles, status, test)
- **cache** -- Manage response cache (subcommands: clear)
- **tasks** -- Manage TaskerData worker tasks (subcommands: apply, get, list)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`taskerdata --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
