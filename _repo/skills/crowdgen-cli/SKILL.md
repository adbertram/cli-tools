---
name: crowdgen-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute Crowdgen operations using the `crowdgen` CLI tool.
  CLI interface for Crowdgen.
  Triggers: crowdgen, crowdgen cli
---

<objective>
Execute Crowdgen operations using the `crowdgen` CLI. All Crowdgen interactions should use this CLI.
</objective>

<quick_start>
The `crowdgen` CLI follows this pattern:
```bash
crowdgen <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Configure authentication credentials | `crowdgen auth login` |
| Clear stored credentials and browser sessions | `crowdgen auth logout` |
| Create a new profile from .env.example template | `crowdgen auth profiles create <NAME>` |
| Delete a profile and its data | `crowdgen auth profiles delete <NAME>` |
| Get details for a specific profile | `crowdgen auth profiles get <NAME>` |
| List all profiles and show their auth types and active state | `crowdgen auth profiles list` |
| Delete a profile and its data | `crowdgen auth profiles remove <NAME>` |
| Rename a profile, re-keying its secrets to the new profile name | `crowdgen auth profiles rename <OLD> <NEW>` |
| Activate a profile within its auth type | `crowdgen auth profiles select <NAME>` |
| Check authentication status across profiles | `crowdgen auth status` |
| Test authentication by verifying credentials work across profiles | `crowdgen auth test` |
| Remove all cached responses | `crowdgen cache clear` |
| Refusal stub — CrowdGen applications are never automated | `crowdgen tasks apply <TASK_ID>` |
| Get full detail for a single listed project/task | `crowdgen tasks get <TASK_ID>` |
| List available worker projects from CrowdGen's projects/available feed | `crowdgen tasks list` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `crowdgen` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `crowdgen --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Manage crowdgen authentication (subcommands: login, logout, profiles, status, test)
- **cache** -- Manage response cache (subcommands: clear)
- **tasks** -- Manage CrowdGen worker projects/tasks (available until shortlisted) (subcommands: apply, get, list)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`crowdgen --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
