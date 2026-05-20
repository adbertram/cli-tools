---
name: "shopsalvationarmy-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute shopsalvationarmy operations using the `shopsalvationarmy` CLI tool. CLI interface for Shop Salvation Army \u2014 search listings, browse categories, view item details. Triggers: shopsalvationarmy, shopsalvationarmy cli, salvation army shop, search salvation army, salvation army listings, salvation army items, browse salvation army, salvation army categories, salvation army auction"
---

<objective>
Execute shopsalvationarmy operations using the `shopsalvationarmy` CLI. All shopsalvationarmy interactions should use this CLI.
</objective>

<quick_start>
The `shopsalvationarmy` CLI follows this pattern:
```bash
shopsalvationarmy <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Search for items | `shopsalvationarmy search query "keywords"` |
| Search with filters | `shopsalvationarmy search query "keywords" -c jewelry --sort price_low` |
| Browse all items | `shopsalvationarmy search query` |
| List categories | `shopsalvationarmy search categories` |
| Get item details | `shopsalvationarmy search get ITEM_ID` |
| Check auth status | `shopsalvationarmy auth status` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `shopsalvationarmy` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **search** — Search and browse item listings: query for items, list categories, get item details
- **auth** — Manage authentication: login, logout, check status
</principle>
</essential_principles>

<reference_index>
**`usage.json`** — Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>
