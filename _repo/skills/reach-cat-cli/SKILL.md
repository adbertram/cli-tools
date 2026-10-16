---
name: reach-cat-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute ReachCat operations using the `reach-cat` CLI tool.
  CLI interface for ReachCat.
  Triggers: reach-cat, reach-cat cli
---

<objective>
Execute ReachCat operations using the `reach-cat` CLI. All ReachCat interactions should use this CLI.
</objective>

<quick_start>
The `reach-cat` CLI follows this pattern:
```bash
reach-cat <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Remove all cached responses | `reach-cat cache clear` |
| Read native campaign fields and public rules; management/payment identities are excluded | `reach-cat campaigns get <CAMPAIGN_ID>` |
| List campaign records with server cursor pagination and local status/platform filters | `reach-cat campaigns list` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `reach-cat` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `reach-cat --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **cache** -- Manage response cache (subcommands: clear)
- **campaigns** -- Read sanitized public campaign records (subcommands: get, list)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`reach-cat --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
