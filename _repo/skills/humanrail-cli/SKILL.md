---
name: humanrail-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute Humanrail operations using the `humanrail` CLI tool.
  CLI interface for Humanrail.
  Triggers: humanrail, humanrail cli
---

<objective>
Execute Humanrail operations using the `humanrail` CLI. All Humanrail interactions should use this CLI.
</objective>

<quick_start>
The `humanrail` CLI follows this pattern:
```bash
humanrail <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Configure authentication credentials | `humanrail auth login` |
| Clear stored credentials and browser sessions | `humanrail auth logout` |
| Create a new profile from .env.example template | `humanrail auth profiles create <NAME>` |
| Delete a profile and its data | `humanrail auth profiles delete <NAME>` |
| Get details for a specific profile | `humanrail auth profiles get <NAME>` |
| List all profiles and show their auth types and active state | `humanrail auth profiles list` |
| Delete a profile and its data | `humanrail auth profiles remove <NAME>` |
| Rename a profile, re-keying its secrets to the new profile name | `humanrail auth profiles rename <OLD> <NEW>` |
| Activate a profile within its auth type | `humanrail auth profiles select <NAME>` |
| Check authentication status across profiles | `humanrail auth status` |
| Test authentication by verifying credentials work across profiles | `humanrail auth test` |
| Remove all cached responses | `humanrail cache clear` |
| Get full detail for a single task | `humanrail tasks get <TASK_ID>` |
| List currently available worker tasks from the live HumanRail queue | `humanrail tasks list` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `humanrail` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `humanrail --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Manage humanrail authentication (subcommands: login, logout, profiles, status, test)
- **cache** -- Manage response cache (subcommands: clear)
- **tasks** -- Manage HumanRail worker tasks (subcommands: get, list)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`humanrail --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
