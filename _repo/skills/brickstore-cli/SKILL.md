---
name: brickstore-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute BrickStore operations using the `brickstore` CLI tool.
  CLI interface for BrickStore.
  Triggers: brickstore, brickstore cli
---

<objective>
Execute BrickStore operations using the `brickstore` CLI. All BrickStore interactions should use this CLI.
</objective>

<quick_start>
Use these commands to get BrickStore price guide data, catalog data, and set contents:
```bash
brickstore part <item-number> [color] [--leave-open]
brickstore set <set-number> [--leave-open]
brickstore set-batch <set-number> [<set-number> ...] [--leave-open]
brickstore set-contents <set-number> [<set-number> ...]
brickstore query [--item-id ...] [--item-name ...] [--item-type ...] [--category ...] [--color ...] [--related-to-item-id ...] [--related-to-item-type ...] [--relationship ...] [--year-min ...] [--year-max ...] [--table] [--leave-open]
```

| Task | Command |
|------|---------|
| Get price guide data for one part | `brickstore part <item-number> [color] [--leave-open]` |
| Get price guide data for one set | `brickstore set <set-number> [--leave-open]` |
| Get price guide data for up to 25 sets | `brickstore set-batch <set-number> [<set-number> ...] [--leave-open]` |
| Get direct items for up to 25 sets | `brickstore set-contents <set-number> [<set-number> ...]` |
| Get general catalog info (name, type, category, years) without a price guide | `brickstore query [filters...] [--table] [--leave-open]` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `brickstore` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `brickstore --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Commands">
- **part** -- Return price guide data for one BrickLink part item ID. Provide an optional BrickStore color name.
- **set** -- Return price guide data for one BrickLink set item ID.
- **set-batch** -- Return price guide data for one through 25 unique BrickLink set item IDs in one source request.
- **set-contents** -- Return direct item records for one through 25 unique BrickLink set item IDs. See README.md Output for the JSON result shape.
- **query** -- Return general catalog items (name, type, category, release years) matching optional filters, without a price guide lookup. Every filter is optional and combinable; no filters returns the whole catalog, capped by the source. The JSON envelope has `total_count`, `returned_count`, `items`, and an optional `note` when results are capped. See README.md Output for the JSON result shape.
- **--leave-open** -- Keep a BrickStore app started by a price guide or query command open after the command completes.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`brickstore --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
