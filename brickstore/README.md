# BrickStore CLI

## DESCRIPTION

Read BrickStore price guide and catalog data through its local MCP server.

Use this CLI to get price guide data, catalog details, and set contents in scripts.

The CLI does not call the BrickLink API directly; `set-contents` uses the installed `bricklink` CLI for read-only subset data.

## Requirements

- `part`, `set`, `set-batch`, and `query` need BrickStore 2026.7.1 or later.
- Enable the MCP server and Catalog Read permission in BrickStore Settings > AI.
- Configure the MCP server port as `45111`, or set `BRICKSTORE_BASE_URL`.
- The CLI starts `/Applications/BrickStore.app/Contents/MacOS/BrickStore` when no MCP server is available.
- `set-contents` needs an installed BrickLink CLI with an authenticated OAuth profile.

## Installation

```bash
cd <cli-tools-root>/brickstore
uv tool install -e . --force --refresh
```

## Quick Start

```bash
brickstore part 3001 Red
brickstore set 30670-1
brickstore set-batch 30670-1 75313-1
brickstore set-contents 30670-1 75313-1
brickstore query --item-id 3001
brickstore part 3001 Red --table
brickstore part 3001 Red --leave-open
```

## Commands

### `part <item-number> [color] [--leave-open]`

Return the BrickStore price guide for one part.

The optional color uses the `color` source argument.

BrickStore requires a color for item types with colors.

Use `--leave-open` to keep a BrickStore app started by this command open.

```bash
brickstore part 3001 Red
brickstore part 3001 Red --table
brickstore part 3001 Red --leave-open
```

### `set <set-number> [--leave-open]`

Return the BrickStore price guide for one set.

The command verifies the set through `catalog_query` before the price call.

Use `--leave-open` to keep a BrickStore app started by this command open.

```bash
brickstore set 30670-1
brickstore set 30670-1 --table
brickstore set 30670-1 --leave-open
```

### `set-batch <set-number> [<set-number> ...] [--leave-open]`

Return price guides for one through 25 known sets in one `catalog_price_guide` source call.

Each input set ID must be unique.

It preserves every source price field and fails when one input has no unique source result.

The batch command does not call `catalog_query` or the BrickLink API.

Use `--leave-open` to keep a BrickStore app started by this command open.

See Output for the JSON result shape.

```bash
brickstore set-batch 30670-1 75313-1
brickstore set-batch 30670-1 75313-1 --leave-open
```

### `set-contents <set-number> [<set-number> ...]`

Return direct item records for one through 25 sets.

Each input set ID must be unique.

The command runs one read-only `bricklink catalog subsets SET <set-id>` command for each set.

See Output for the JSON result shape.

```bash
brickstore set-contents 30670-1 75313-1
```

### `query [filters...] [--table] [--leave-open]`

Return BrickStore catalog items matching the given filters, without a price guide lookup.

Every filter is optional; combine any number of them to narrow results. Calling `query` with no filters returns the whole catalog, capped by the source.

| Option | Meaning |
|---|---|
| `--item-id` | Filter by item ID, case-insensitive partial match. |
| `--item-name` | Filter by item name, case-insensitive partial match. |
| `--item-type` | Item type full name (`Part`, `Set`, `Minifig`, ...) or single-letter BrickLink ID. |
| `--category` | Filter by category name, case-insensitive partial match. |
| `--color` | Filter by color name, case-insensitive partial match; only items available in that color are returned. |
| `--related-to-item-id` | Reference item ID; returns only items sharing a relationship with it. |
| `--related-to-item-type` | Item type of the reference item, required together with `--related-to-item-id`. |
| `--relationship` | Relationship type name filter, only considered when `--related-to-item-id` is set. |
| `--year-min` | Minimum production year (inclusive). |
| `--year-max` | Maximum production year (inclusive). |

Use `--leave-open` to keep a BrickStore app started by this command open.

See Output for the JSON result shape.

```bash
brickstore query --item-id 3001
brickstore query --item-name "Brick 2 x 4" --item-type Part
brickstore query --category Minifig --year-min 2020
brickstore query --related-to-item-id 3001 --related-to-item-type P --relationship Alternate
brickstore query --item-id 3001 --table
```

## Output

JSON is the default output format.

`part` and `set` support `--table` or `-t` for a field-value table.

`set-batch` always returns its JSON results envelope.

`set-contents` always returns a top-level JSON array of set records.

Each `set-contents` record has `set_id` and an `items` array.

Each `items` record preserves its BrickLink entry fields and adds `match_no`.

The CLI preserves these source fields:

| Field | Source meaning |
|---|---|
| `item_id` | BrickLink item ID. |
| `item_name` | Catalog item name. |
| `color` | Resolved BrickStore color name. |
| `currency` | Price currency. |
| `last_updated` | Price guide update time. |
| `last_six_months` | Sold price blocks for `new` and `used`. |
| `current` | Current inventory blocks for `new` and `used`. |

`query` always returns its JSON results envelope with `total_count`, `returned_count`, and `items`.

`query --table` renders only the `items` array as a table.

The envelope includes a `note` field only when the source caps `returned_count` below `total_count`; refine the filters to see the remaining matches.

Each `query` item preserves these source fields:

| Field | Source meaning |
|---|---|
| `id` | BrickLink item ID. |
| `name` | Catalog item name. |
| `type_id` | Single-letter BrickLink item type. |
| `type_name` | Full item type name. |
| `category` | Catalog category name. |
| `year_released` | First production year, when known. |
| `year_last_produced` | Last production year, when known and different from `year_released`. |

Each condition block has `total_quantity`, `lots`, and `prices`.

Each `prices` object has `min`, `avg`, `qty_avg`, and `max`.

## Configuration

The BrickStore price guide commands use no reusable credentials.

`set-contents` uses the existing authenticated BrickLink CLI profile.

Store non-secret configuration in `~/.local/share/cli-tools/brickstore/.env`.

```bash
BRICKSTORE_BASE_URL=http://127.0.0.1:45111
BRICKSTORE_EXECUTABLE=/Applications/BrickStore.app/Contents/MacOS/BrickStore
```

## Errors

The price guide commands use an existing MCP server when it is ready.

When no MCP server is ready, the CLI starts the configured BrickStore executable and waits 30 seconds.

The CLI stops only the process that it starts after the price call completes.

Use `--leave-open` to keep that process open after the command completes.

The option does not affect an existing BrickStore process.

The CLI returns the source startup or readiness error when the server does not become ready.

`set-contents` returns a command error when its BrickLink CLI source fails.

## Exit Codes

| Code | Meaning |
|---|---|
| 0 | Success. |
| 1 | Command or source error. |
| 2 | Invalid CLI input. |
| 130 | User interrupt. |

## Documentation

- [BrickStore source repository](https://github.com/rgriebl/brickstore)
- [MCP test plan](https://github.com/rgriebl/brickstore/blob/master/scripts/mcp-test-plan.md)
