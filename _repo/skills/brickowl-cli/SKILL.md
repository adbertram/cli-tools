---
name: brickowl-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute brickowl operations using the `brickowl` CLI tool.
  CLI interface for Brick Owl API -- manage orders, inventory, catalog, messages, refunds, coupons, and quotes.
  Triggers: brickowl, brickowl cli, brick owl, brickowl orders, brickowl inventory, brickowl catalog, brickowl messages, brickowl quotes, brick owl store
---

<objective>
Execute brickowl operations using the `brickowl` CLI. All Brick Owl interactions should use this CLI.
</objective>

<quick_start>
The `brickowl` CLI follows this pattern:
```bash
brickowl <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List orders | `brickowl order list` |
| Get order details | `brickowl order get <order_id>` |
| List inventory | `brickowl inventory list` |
| Search catalog | `brickowl catalog search <query>` |
| Send a message | `brickowl messages send <user_id> <subject> <body>` |
| Issue a refund | `brickowl refund issue <order_id> <amount>` |
| List quotes | `brickowl quotes list` |
| Check auth | `brickowl auth status` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `brickowl` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Authentication management (login, logout, status, refresh, test)
- **order** -- Order management (list, get, items, status, ship, tracking, note)
- **inventory** -- Store inventory (list, get, search, stats, update, delete)
- **catalog** -- Catalog browsing (lookup, search, id, availability, inventory, colors, conditions, categories, themes)
- **user** -- User details
- **messages** -- Message management (list, get, send, reply, mark-read, mark-unread)
- **refund** -- Refund management (info, issue, full)
- **coupon** -- Coupon management (list, get, create-user, create-code, delete)
- **quotes** -- Quote management (list, get, submit)
- **cache** -- Response cache (clear)
- **auth** -- Authentication commands and nested `auth profiles` management
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
