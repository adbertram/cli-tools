---
name: atlas-capture-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute AtlasCapture operations using the `atlas-capture` CLI tool.
  CLI interface for AtlasCapture.
  Triggers: atlas-capture, atlas-capture cli
---

<objective>
Execute AtlasCapture operations using the `atlas-capture` CLI. All AtlasCapture interactions should use this CLI.
</objective>

<quick_start>
The `atlas-capture` CLI follows this pattern:
```bash
atlas-capture <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Show live account facts from the authenticated session (user.me) | `atlas-capture account show` |
| Configure authentication credentials | `atlas-capture auth login` |
| Clear stored credentials and browser sessions | `atlas-capture auth logout` |
| Create a new profile from .env.example template | `atlas-capture auth profiles create <NAME>` |
| Delete a profile and its data | `atlas-capture auth profiles delete <NAME>` |
| Get details for a specific profile | `atlas-capture auth profiles get <NAME>` |
| List all profiles and show their auth types and active state | `atlas-capture auth profiles list` |
| Delete a profile and its data | `atlas-capture auth profiles remove <NAME>` |
| Rename a profile, re-keying its secrets to the new profile name | `atlas-capture auth profiles rename <OLD> <NEW>` |
| Activate a profile within its auth type | `atlas-capture auth profiles select <NAME>` |
| Check authentication status across profiles | `atlas-capture auth status` |
| Test authentication by verifying credentials work across profiles | `atlas-capture auth test` |
| Remove all cached responses | `atlas-capture cache clear` |
| Refuse to apply to a task | `atlas-capture tasks apply <TASK_ID>` |
| Get full detail for a single task | `atlas-capture tasks get <TASK_ID>` |
| List tasks Atlas Capture exposes to this account | `atlas-capture tasks list` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `atlas-capture` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `atlas-capture --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **account** -- Atlas Capture account state (subcommands: show)
- **auth** -- Manage atlas-capture authentication (subcommands: login, logout, profiles, status, test)
- **cache** -- Manage response cache (subcommands: clear)
- **tasks** -- Atlas Capture worker tasks (discovery only) (subcommands: apply, get, list)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`atlas-capture --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
