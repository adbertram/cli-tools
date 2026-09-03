---
name: mercor-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute Mercor operations using the `mercor` CLI tool.
  CLI interface for Mercor.
  Triggers: mercor, mercor cli
---

<objective>
Execute Mercor operations using the `mercor` CLI. All Mercor interactions should use this CLI.
</objective>

<quick_start>
The `mercor` CLI follows this pattern:
```bash
mercor <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Configure authentication credentials | `mercor auth login` |
| Clear stored credentials and browser sessions | `mercor auth logout` |
| Create a new profile from .env.example template | `mercor auth profiles create <NAME>` |
| Delete a profile and its data | `mercor auth profiles delete <NAME>` |
| Get details for a specific profile | `mercor auth profiles get <NAME>` |
| List all profiles and show their auth types and active state | `mercor auth profiles list` |
| Delete a profile and its data | `mercor auth profiles remove <NAME>` |
| Rename a profile, re-keying its secrets to the new profile name | `mercor auth profiles rename <OLD> <NEW>` |
| Activate a profile within its auth type | `mercor auth profiles select <NAME>` |
| Check authentication status across profiles | `mercor auth status` |
| Test authentication by verifying credentials work across profiles | `mercor auth test` |
| Remove all cached responses | `mercor cache clear` |
| Dry-run stub | `mercor tasks apply <TASK_ID>` |
| Get the full record for a single Mercor listing | `mercor tasks get <TASK_ID>` |
| List the role listings on Mercor's worker Explore surface | `mercor tasks list` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `mercor` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `mercor --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Manage mercor authentication (subcommands: login, logout, profiles, status, test)
- **cache** -- Manage response cache (subcommands: clear)
- **tasks** -- Inspect Mercor role listings on the worker Explore surface (subcommands: apply, get, list)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`mercor --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
