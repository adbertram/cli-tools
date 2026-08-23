---
name: poshmark-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute Poshmark operations using the `poshmark` CLI tool.
  CLI interface for Poshmark.
  Triggers: poshmark, poshmark cli
---

<objective>
Execute Poshmark operations using the `poshmark` CLI. All Poshmark interactions should use this CLI.
</objective>

<quick_start>
The `poshmark` CLI follows this pattern:
```bash
poshmark <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Authenticate | `poshmark auth login` |
| Check auth | `poshmark auth status` |
| List newest listings | `poshmark listings list` |
| Search listings | `poshmark listings search <query>` |
| Get listing detail | `poshmark listings get <id-or-direct-url>` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `poshmark` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `poshmark --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Authentication management (login, logout, status, test) and nested `auth profiles`
- **cache** -- Local response cache management
- **listings** -- List, search, and get detail through the saved browser profile
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`poshmark --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
