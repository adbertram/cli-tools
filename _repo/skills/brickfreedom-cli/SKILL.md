---
name: "brickfreedom-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute brickfreedom operations using the `brickfreedom` CLI tool. CLI interface for BrickFreedom dashboard automation -- manage LEGO orders and tasks across Bricklink and Brick Owl. Triggers: brickfreedom, brickfreedom cli, brickfreedom orders, brickfreedom tasks, LEGO orders, process orders, ship orders, replacement parts, missing parts, order tracking"
---

<objective>
Execute brickfreedom operations using the `brickfreedom` CLI. All BrickFreedom dashboard interactions should use this CLI.
</objective>

<quick_start>
The `brickfreedom` CLI follows this pattern:
```bash
brickfreedom <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List orders | `brickfreedom order list` |
| List paid orders | `brickfreedom order list --status PAID` |
| Get an order | `brickfreedom order get <order_id>` |
| Set tracking | `brickfreedom order tracking <order_id> <tracking>` |
| List tasks | `brickfreedom task list` |
| Create replacement task | `brickfreedom task create --type customer-replacement-part --platform bricklink --order-id <id> ...` |
| Complete a task by 1-based index (interactive only) | `brickfreedom task complete <index>` |
| Complete a missing-part task by content match (PREFERRED for scripts) | `brickfreedom task complete --match-platform <bricklink\|brickowl> --match-order-id <id> --match-item-number <part> [--match-quantity <qty>]` |
| Show raw task rows that did not parse (debug new dashboard formats) | `brickfreedom task list --type missing-part --debug-unparsed` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `brickfreedom` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Authentication management (login, logout, status, refresh, test)
- **cache** -- Manage response cache (clear)
- **auth** -- Authentication commands and nested `auth profiles` management
- **task** -- Dashboard task management (list, get, create, complete, delete)
- **order** -- Order management (list, get, processed, process, post, tracking)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<gotchas>
**`task list` — `-t` is `--table`, NOT `--type`.** The `-t` short flag toggles table output (boolean). To filter by task type, you MUST spell out `--type`. Valid `--type` values: `customer-replacement-part`, `missing-part`. Passing `-t customer-replacement-part` fails with `Got unexpected extra argument (customer-replacement-part)` because `customer-replacement-part` gets parsed as a positional arg after the boolean `-t` consumes nothing.

```bash
# WRONG — fails silently-looking but exits non-zero
brickfreedom task list -t customer-replacement-part

# RIGHT
brickfreedom task list --type customer-replacement-part
```

**`task complete <index>` is fragile for scripts -- prefer `--match-*` flags.** Positional indexes are 1-based positions in the live dashboard list. Completing a task shifts every higher-indexed task down by one. Any script or agent that captures an index before mutating the list (e.g. completes one missing-part task, then completes another) will hit the wrong slot. Use match-mode for any non-interactive workflow:

```bash
# WRONG for scripts -- index may shift between list and complete
INDEX=$(brickfreedom task list --type missing-part | jq '.parts[] | select(.order_id=="30823995") | .index')
brickfreedom task complete "$INDEX"

# RIGHT for scripts -- re-resolves the current index at click time
brickfreedom task complete \
    --match-platform bricklink \
    --match-order-id 30823995 \
    --match-item-number 75270-1
# Exit 0 + JSON with resolved {index, platform, orderId, itemNumber, quantity} on single match.
# Exit 1 + JSON {"success": false, "error": "no matching missing-part task"} on zero matches.
# Exit 1 + JSON {"success": false, "error": "ambiguous match ...", "matches": [...]} on multiple matches -- pass --match-quantity to disambiguate.
```

**Silent missing-part parser misses are visible.** `task list --type missing-part` includes a top-level `unparsed_count` field in JSON output and prints a stderr warning when it is > 0. When BF ships a new task text format, run `task list --type missing-part --debug-unparsed` to print the raw unparsed rows to stderr so the parser can be updated.
</gotchas>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>
