---
name: microworkers-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute Microworkers operations using the `microworkers` CLI tool.
  CLI interface for Microworkers.
  Triggers: microworkers, microworkers cli
---

<objective>
Execute Microworkers operations using the `microworkers` CLI. All Microworkers interactions should use this CLI.
</objective>

<quick_start>
The `microworkers` CLI follows this pattern:
```bash
microworkers <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Configure authentication credentials | `microworkers auth login` |
| Clear stored credentials and browser sessions | `microworkers auth logout` |
| Create a new profile from .env.example template | `microworkers auth profiles create <NAME>` |
| Delete a profile and its data | `microworkers auth profiles delete <NAME>` |
| Get details for a specific profile | `microworkers auth profiles get <NAME>` |
| List all profiles and show their auth types and active state | `microworkers auth profiles list` |
| Delete a profile and its data | `microworkers auth profiles remove <NAME>` |
| Rename a profile, re-keying its secrets to the new profile name | `microworkers auth profiles rename <OLD> <NEW>` |
| Activate a profile within its auth type | `microworkers auth profiles select <NAME>` |
| Check authentication status across profiles | `microworkers auth status` |
| Test authentication by verifying credentials work across profiles | `microworkers auth test` |
| Remove all cached responses | `microworkers cache clear` |
| Apply to (submit proof for) a task | `microworkers tasks apply <TASK_ID>` |
| Get full detail for a single task | `microworkers tasks get <TASK_ID>` |
| List available worker jobs from the live Microworkers /jobs.php listing | `microworkers tasks list` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `microworkers` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `microworkers --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Manage microworkers authentication (subcommands: login, logout, profiles, status, test)
- **cache** -- Manage response cache (subcommands: clear)
- **tasks** -- Manage Microworkers worker jobs (tasks) (subcommands: apply, get, list)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`microworkers --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
