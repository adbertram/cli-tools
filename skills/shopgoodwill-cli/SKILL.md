---
name: "shopgoodwill-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute shopgoodwill operations using the `shopgoodwill` CLI tool. CLI interface for ShopGoodwill. Triggers: shopgoodwill, shopgoodwill cli, shop goodwill, goodwill auction, search goodwill, goodwill listings, shopgoodwill search"
---

<objective>
Execute shopgoodwill operations using the `shopgoodwill` CLI. All ShopGoodwill interactions should use this CLI.
</objective>

<quick_start>
The `shopgoodwill` CLI follows this pattern:
```bash
shopgoodwill <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Search listings | `shopgoodwill search query "LEGO" --table` |
| Get listing details | `shopgoodwill search get LISTING_ID` |
| Check auth | `shopgoodwill auth status` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `shopgoodwill` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **search** -- Search listings (query, get)
- **auth** -- Manage authentication (login, logout, status)
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
