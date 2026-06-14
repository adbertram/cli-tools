---
name: facebook-marketplace-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute facebook_marketplace operations using the `facebook_marketplace` CLI tool.
  Search Facebook Marketplace via Playwright browser automation -- browse listings, search by keyword, filter by price and location.
  Triggers: facebook_marketplace, facebook_marketplace cli, facebook marketplace search, search marketplace, marketplace listings, browse facebook marketplace
---

<objective>
Execute facebook_marketplace operations using the `facebook_marketplace` CLI. All Facebook Marketplace listing searches should use this CLI.
</objective>

<quick_start>
The `facebook_marketplace` CLI follows this pattern:
```bash
facebook_marketplace <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Search listings | `facebook_marketplace listings list --query "LEGO" --table` |
| Browse Today's picks | `facebook_marketplace listings list --table` |
| Filter by price | `facebook_marketplace listings list --query "couch" --min-price 50 --max-price 500` |
| Get listing details | `facebook_marketplace listings get ITEM_ID` |
| Download images | `facebook_marketplace listings get ITEM_ID --download-images` |
| Check auth | `facebook_marketplace auth status` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `facebook_marketplace` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** — Manage authentication via headed browser (login, logout, status, test)
- **listings** — Search and browse Marketplace listings (list with filters, get details)
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
