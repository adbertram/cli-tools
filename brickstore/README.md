# BrickStore CLI

## DESCRIPTION

Read BrickStore price guide and catalog data through its local MCP server.

Use this CLI to get price guide data, catalog details, and local set and minifig contents in scripts.

The CLI does not call the BrickLink API; `set-contents` and `minifig-contents` read catalog data from the local BrickStore catalog database.

## Requirements

- `part`, `minifig`, `set`, `set-batch`, and `query` need BrickStore 2026.7.1 or later.
- Enable the MCP server and Catalog Read permission in BrickStore Settings > AI.
- Configure the MCP server port as `45111`, or set `BRICKSTORE_BASE_URL`.
- The CLI starts `/Applications/BrickStore.app/Contents/MacOS/BrickStore` when no MCP server is available.
- `set-contents`, `minifig-contents`, and `database status` need a local version 12 database.
- Run `brickstore database update` when the local database file does not exist.

## Installation

```bash
cd <cli-tools-root>/brickstore
uv tool install -e . --force --refresh
```

## Quick Start

```bash
brickstore part 3001 Red
brickstore minifig sw0001a
brickstore set 30670-1
brickstore set-batch 30670-1 75313-1
brickstore set-contents 30670-1 75313-1
brickstore minifig-contents sw0001a sw0036
brickstore database status
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

### `minifig <item-number> [--leave-open]`

Return the BrickStore price guide for one minifigure.

A minifigure carries no color, so the command takes no color argument.

Use `--leave-open` to keep a BrickStore app started by this command open.

```bash
brickstore minifig sw0001a
brickstore minifig sw0001a --table
brickstore minifig sw0001a --leave-open
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

Return direct item records from the local database for one through 25 sets.

Each input set ID must be unique.

The database stores one row for each inventory record.

The command merges the regular row and the extra row for the same item, color, alternate flag, counterpart flag, and match number.

`quantity` counts all units. `extra_quantity` counts extra units only.

The command does not call the BrickLink CLI or the BrickLink API.

See Output for the JSON result shape.

```bash
brickstore set-contents 30670-1 75313-1
```

### `minifig-contents <minifig-number> [<minifig-number> ...]`

Return direct component records from the local database for one through 25 minifigs.

Each input minifig ID must be unique.

The command follows the same local database read, record merge, and quantity rules as `set-contents`.

See Output for the JSON result shape.

```bash
brickstore minifig-contents sw0001a sw0036
```

### `database update [--force]`

Download and install the newest local version 12 database.

The command downloads `database-v12.lzma` from `BRICKSTORE_DATABASE_URL`.

The command checks the SHA-512 digest, LZMA data, magic bytes, and database version before it replaces the local file.

The command stores the server ETag in a `.etag` sidecar file.

Use `--force` or `-f` to download the file when the local ETag is current.

```bash
brickstore database update
brickstore database update --force
```

### `database status [--table]`

Return metadata for the local database.

Use `--table` or `-t` to display the metadata as a field-value table.

```bash
brickstore database status
brickstore database status --table
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

`part`, `minifig`, and `set` support `--table` or `-t` for a field-value table.

`set-batch` always returns its JSON results envelope.

`set-contents` always returns a top-level JSON array of set records.

Each `set-contents` record has `set_id` and an `items` array.

`minifig-contents` always returns a top-level JSON array of minifig records.

Each `minifig-contents` record has `minifig_id` and an `items` array.

Each `items` record has these fields:

| Field | Meaning |
|---|---|
| `item.no` | BrickLink item ID. |
| `item.name` | Catalog item name. |
| `item.type` | Catalog item type. |
| `item.category_id` | Catalog category ID, or `null`. |
| `color_id` | BrickStore color ID. |
| `quantity` | Total unit count. |
| `extra_quantity` | Extra unit count. |
| `is_alternate` | Whether the item is an alternate. |
| `is_counterpart` | Whether the item is a counterpart. |
| `match_no` | Match number from the source inventory. |

Price guide output preserves these source fields:

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

`database update` returns an object with `path`, `url`, `updated`, and `etag`.

An updated database also returns `compressed_bytes` and `bytes`.

An unchanged database returns `updated: false` after the server returns HTTP 304.

`database status` returns an object with `path`, `version`, `generated_at`, `etag`, `colors`, `categories`, `item_types`, `items`, `sets`, `sets_with_inventory`, `minifigs`, and `minifigs_with_inventory`.

## Configuration

The BrickStore price guide commands use no reusable credentials.

Store non-secret configuration in `~/.local/share/cli-tools/brickstore/.env`.

```bash
BRICKSTORE_BASE_URL=http://127.0.0.1:45111
BRICKSTORE_EXECUTABLE=/Applications/BrickStore.app/Contents/MacOS/BrickStore
BRICKSTORE_DATABASE_PATH=~/Library/Caches/BrickStore/database-v12
BRICKSTORE_DATABASE_URL=https://github.com/rgriebl/brickstore-database/releases/latest/download
```

The default database path is `~/Library/Caches/BrickStore/database-v12`.

The default database URL is `https://github.com/rgriebl/brickstore-database/releases/latest/download`.

The updater adds `/database-v12.lzma` to the database URL.

The CLI uses no reusable credentials for BrickStore or the database source.

## Errors

The price guide commands use an existing MCP server when it is ready.

When no MCP server is ready, the CLI starts the configured BrickStore executable and waits 30 seconds.

The CLI stops only the process that it starts after the price call completes.

Use `--leave-open` to keep that process open after the command completes.

The option does not affect an existing BrickStore process.

The CLI returns the source startup or readiness error when the server does not become ready.

`set-contents`, `minifig-contents`, and `database status` return a command error when the database file does not exist.

Run `brickstore database update` or set `BRICKSTORE_DATABASE_PATH` to a valid version 12 file.

The CLI returns a command error when the database file is unreadable, truncated, corrupt, missing a required chunk, or has an unsupported version.

`set-contents` returns a command error when the requested set does not exist in the local database.

`minifig-contents` returns a command error when the requested minifig does not exist in the local database.

`database update` returns a command error when the download fails, the server returns an unexpected status, the response has no ETag, or the database fails its SHA-512, LZMA, magic-byte, or version check.

The updater replaces the local file only after all database checks pass.

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
