---
name: toloka-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute Toloka operations using the `toloka` CLI tool.
  CLI interface for Toloka.
  Triggers: toloka, toloka cli
---

<objective>
Execute Toloka operations using the `toloka` CLI. All Toloka interactions should use this CLI.
</objective>

<quick_start>
The `toloka` CLI follows this pattern:
```bash
toloka <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Configure authentication credentials | `toloka auth login` |
| Clear stored credentials and browser sessions | `toloka auth logout` |
| Create a new profile from .env.example template | `toloka auth profiles create <NAME>` |
| Delete a profile and its data | `toloka auth profiles delete <NAME>` |
| Get details for a specific profile | `toloka auth profiles get <NAME>` |
| List all profiles and show their auth types and active state | `toloka auth profiles list` |
| Delete a profile and its data | `toloka auth profiles remove <NAME>` |
| Rename a profile, re-keying its secrets to the new profile name | `toloka auth profiles rename <OLD> <NEW>` |
| Activate a profile within its auth type | `toloka auth profiles select <NAME>` |
| Check authentication status across profiles | `toloka auth status` |
| Test authentication by verifying credentials work across profiles | `toloka auth test` |
| Remove all cached responses | `toloka cache clear` |
| Apply to a task | `toloka tasks apply <TASK_ID>` |
| Get full detail for a specific task | `toloka tasks get <TASK_ID>` |
| List open/available tasks for the logged-in worker | `toloka tasks list` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `toloka` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `toloka --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Manage toloka authentication (subcommands: login, logout, profiles, status, test)
- **cache** -- Manage response cache (subcommands: clear)
- **tasks** -- Browse and apply to Toloka tasks (subcommands: apply, get, list)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`toloka --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
