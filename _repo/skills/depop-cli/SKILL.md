---
name: depop-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute Depop marketplace search operations using the `depop` CLI tool.
  CLI interface for the Depop resale marketplace -- search public listings with price, condition, gender, category, and sort filters.
  Triggers: depop, depop cli, depop search, search depop
---

<objective>
Execute Depop marketplace search operations using the `depop` CLI. All Depop interactions should use this CLI.
</objective>

<quick_start>
The `depop` CLI follows this pattern:
```bash
depop <command> [arguments] [options]
```

| Task | Command |
|------|---------|
| Authenticate (one-time Cloudflare clearance) | `depop auth login` |
| Check auth | `depop auth status` |
| Search listings | `depop search "<query>"` |
| Search with filters | `depop search "<query>" --price-min 10 --price-max 50 --condition used_good --gender female --category coats-jackets --sort price_asc --limit 25` |
| Table output | `depop search "<query>" --table` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `depop` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `depop --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **search** -- Top-level command (not a group). Searches public Depop listings by keyword. All filters (`--price-min`, `--price-max`, `--condition`, `--gender`, `--category`, `--sort`) are sent to Depop's own search API server-side; `--limit` drives cursor pagination rather than truncating a larger fetch. `--filter`/`--properties`/`--table` apply on top of the returned records.
- **auth** -- Authentication management (login, logout, status, test) and nested `auth profiles`. "Authentication" here means earning a Cloudflare `cf_clearance` cookie, not a Depop account login -- there is no username/password. Run `depop auth login` once; it opens a headed browser, Cloudflare's Managed Challenge clears silently within seconds, and every `search` call afterward runs headless against the persisted profile.
- **cache** -- Local response cache management
</principle>

<principle name="Depop search filter values">
- `--condition` (repeatable): `brand_new`, `used_like_new`, `used_excellent`, `used_good`, `used_fair`
- `--gender`: `male`, `female`, `unisex` (there is no `kids` gender value -- Depop's Kids category is a separate top-level nav, not implemented as a filter here)
- `--category`: a group slug matching a result's `category` field, e.g. `coats-jackets`, `tops`, `bottoms`, `dresses`, `jeans`, `sweaters`, `footwear`
- `--sort`: `relevance` (default), `price_asc`, `price_desc`
- Size filtering is intentionally not implemented (Depop's size taxonomy is nested per-category composite ids, not a flat enum) -- filter client-side on a result's `sizes[]` array instead, e.g. `--filter "sizes:contains:M"` only works if `sizes` were a flat string; in practice inspect the returned `sizes[].name` values and post-filter with `jq` for anything beyond a simple size lookup.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`depop --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
