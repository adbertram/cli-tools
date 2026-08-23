---
name: ups-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute UPS pickup operations using the `ups` CLI tool.
  CLI interface for UPS Pickup API operations.
  Triggers: ups, ups cli
---

<objective>
Execute UPS pickup operations using the `ups` CLI. All UPS pickup scheduling, inspection, and authentication work should use this CLI.
</objective>

<quick_start>
The `ups` CLI follows this pattern:
```bash
ups <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Authenticate | `ups auth login` |
| Check auth | `ups auth status` |
| Schedule pickup | `ups pickup schedule --weight <pounds>` |
| Preview pickup request | `ups pickup schedule --dry-run` |
| List pending pickups | `ups pickup list` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `ups` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `ups --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Authentication management (login, logout, status, test) and nested `auth profiles`
- **cache** -- Local response cache management
- **pickup** -- Schedule UPS pickups and inspect pending pickup requests
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`ups --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
