---
name: "freshworks-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute freshworks operations using the `freshworks` CLI tool. CLI interface for Freshworks API. Triggers: freshworks, freshworks cli, freshworks auth, freshworks items, freshworks cache, list freshworks items"
---

<objective>
Execute freshworks operations using the `freshworks` CLI. All freshworks interactions should use this CLI.
</objective>

<quick_start>
The `freshworks` CLI follows this pattern:
```bash
freshworks <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check auth status | `freshworks auth status` |
| Login | `freshworks auth login` |
| List profiles | `freshworks auth profiles list --table` |
| List items | `freshworks items list --table` |
| Get one item | `freshworks items get ITEM_ID` |
| Clear cache | `freshworks cache clear` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `freshworks` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Manage freshworks authentication and profiles
- **cache** -- Inspect or clear cached freshworks responses
- **items** -- List or retrieve scaffolded freshworks items
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>
