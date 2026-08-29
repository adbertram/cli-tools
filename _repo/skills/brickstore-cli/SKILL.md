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
Use these commands to get BrickStore price guide data, catalog data, set and minifig contents, and database metadata:
```bash
brickstore part <item-number> [color] [--leave-open]
brickstore minifig <item-number> [--leave-open]
brickstore set <set-number> [--leave-open]
brickstore set-batch <set-number> [<set-number> ...] [--leave-open]
brickstore set-contents <set-number> [<set-number> ...] [--skip-unknown]
brickstore minifig-contents <minifig-number> [<minifig-number> ...] [--skip-unknown]
brickstore database update [--force]
brickstore database status [--table]
brickstore query [--item-id ...] [--item-name ...] [--item-type ...] [--category ...] [--color ...] [--related-to-item-id ...] [--related-to-item-type ...] [--relationship ...] [--year-min ...] [--year-max ...] [--table] [--leave-open]
```

| Task | Command |
|------|---------|
| Get price guide data for one part | `brickstore part <item-number> [color] [--leave-open]` |
| Get price guide data for one minifig | `brickstore minifig <item-number> [--leave-open]` |
| Get price guide data for one set | `brickstore set <set-number> [--leave-open]` |
| Get price guide data for up to 25 sets | `brickstore set-batch <set-number> [<set-number> ...] [--leave-open]` |
| Get direct items for up to 25 sets | `brickstore set-contents <set-number> [<set-number> ...] [--skip-unknown]` |
| Get direct components for up to 25 minifigs | `brickstore minifig-contents <minifig-number> [<minifig-number> ...] [--skip-unknown]` |
| Update the local catalog database | `brickstore database update [--force]` |
| Show local catalog database metadata | `brickstore database status [--table]` |
| Get general catalog info (name, type, category, years) without a price guide | `brickstore query [filters...] [--table] [--leave-open]` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `brickstore` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `brickstore --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Commands">
- **part** -- Return price guide data for one BrickLink part item ID. Provide an optional BrickStore color name.
- **minifig** -- Return price guide data for one BrickLink minifig item ID. A minifig carries no color argument.
- **set** -- Return price guide data for one BrickLink set item ID.
- **set-batch** -- Return price guide data for one through 25 unique BrickLink set item IDs in one source request.
- **set-contents** -- Return direct item records from the local version 12 database for one through 25 unique BrickLink set item IDs. Merge regular and extra rows for the same item record. See README.md Output for the JSON result shape.
- **minifig-contents** -- Return direct component records from the local version 12 database for one through 25 unique BrickLink minifig item IDs. Follows the same merge and quantity rules as `set-contents`; each record has `minifig_id` and an `items` array.
- **--skip-unknown** -- On `set-contents` and `minifig-contents`: return records for every ID the local database holds instead of failing the batch. Each skipped ID prints one `Warning: skipped unknown <set|minifig> ID <id>` stderr line and the command exits 0. Without the flag an unknown ID fails the whole command. Bulk backfills should pass this flag.
- **database update** -- Download and validate the newest local version 12 database. Use `--force` to redownload a current local copy.
- **database status** -- Return local database metadata. Use `--table` or `-t` for field-value output.
- **query** -- Return general catalog items (name, type, category, release years) matching optional filters, without a price guide lookup. Every filter is optional and combinable; no filters returns the whole catalog, capped by the source. The JSON envelope has `total_count`, `returned_count`, `items`, and an optional `note` when results are capped. See README.md Output for the JSON result shape.
- **--leave-open** -- Keep a BrickStore app started by a price guide or query command open after the command completes.
</principle>
</essential_principles>

## Local Database

`set-contents` and `minifig-contents` read the local database. They do not call the BrickLink CLI or the BrickLink API.

The default file is `~/Library/Caches/BrickStore/database-v12`.

Set `BRICKSTORE_DATABASE_PATH` to use another file. Set `BRICKSTORE_DATABASE_URL` to use another database source.

Store these non-secret values in `~/.local/share/cli-tools/brickstore/.env`.

`database status` reports the file path, database version, generation time, ETag, and catalog counts.

`database update` fails when the source response or database validation fails. The command replaces the local file only after validation.

See README.md for the complete output fields and error messages.

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
