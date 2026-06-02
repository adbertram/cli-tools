---
name: "doordash-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute doordash operations using the `doordash` CLI tool. CLI interface for DoorDash via browser automation -- list orders, get order details, browse stores, and reorder a previous order. Triggers: doordash, doordash cli, doordash orders, food delivery, list restaurants, doordash stores, recent orders, delivery orders, place doordash order, reorder doordash, doordash reorder, re-place doordash order, place a doordash order"
---

<objective>
Execute doordash operations using the `doordash` CLI. All doordash interactions should use this CLI.
</objective>

<quick_start>
The `doordash` CLI follows this pattern:
```bash
doordash <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check auth status | `doordash auth status` |
| Login via browser | `doordash auth login` |
| List recent orders | `doordash orders list --table` |
| Get order details | `doordash orders get ORDER_ID` |
| Reorder (dry run) | `doordash orders reorder ORDER_ID` |
| Reorder (actually charges) | `doordash orders reorder ORDER_ID --confirm` |
| List open restaurants | `doordash stores list --filter "is_open:eq:true"` |
| High-rated restaurants | `doordash stores list --filter "rating:gte:4.5"` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `doordash` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Manage browser-based DoorDash authentication (login, status, test, logout)
- **orders** -- List and inspect DoorDash orders
- **stores** -- Browse available restaurants and stores for delivery
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
