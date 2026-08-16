---
name: stockx-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute StockX operations using the `stockx` CLI tool.
  Read-only access to the StockX catalog and its live resale market: search
  products by keyword, browse the catalog, read one product's catalog record,
  and read live asks, bids, and sales data.
  Triggers: stockx, stockx cli, stockx search, stockx product, stockx market, sneaker resale price
---

<objective>
Execute StockX operations using the `stockx` CLI. All StockX interactions should use this CLI.
</objective>

<quick_start>
The `stockx` CLI follows this pattern:
```bash
stockx <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Configure authentication credentials | `stockx auth login` |
| Clear stored credentials and browser sessions | `stockx auth logout` |
| Create a new profile from .env.example template | `stockx auth profiles create <NAME>` |
| Delete a profile and its data | `stockx auth profiles delete <NAME>` |
| Get details for a specific profile | `stockx auth profiles get <NAME>` |
| List all profiles and show their auth types and active state | `stockx auth profiles list` |
| Delete a profile and its data | `stockx auth profiles remove <NAME>` |
| Rename a profile, re-keying its secrets to the new profile name | `stockx auth profiles rename <OLD> <NEW>` |
| Activate a profile within its auth type | `stockx auth profiles select <NAME>` |
| Check authentication status across profiles | `stockx auth status` |
| Test authentication by verifying credentials work across profiles | `stockx auth test` |
| Remove all cached responses | `stockx cache clear` |
| Get the catalog record for one product | `stockx products get <PRODUCT>` |
| Browse the StockX catalog with no keyword | `stockx products list` |
| Get live market data (asks, bids, sales) for one product | `stockx products market <PRODUCT>` |
| Search the StockX catalog by keyword | `stockx products search <QUERY>` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `stockx` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `stockx --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **auth** -- Manage stockx authentication (subcommands: login, logout, profiles, status, test)
- **cache** -- Manage response cache (subcommands: clear)
- **products** -- Search and read StockX products (subcommands: get, list, market, search)
</principle>
<principle name="No StockX Account Is Needed For Reads">
Every `products` command works on a cold profile with no StockX account; the
catalog is public. Do not run `stockx auth login` or report an auth blocker
before a read command has actually failed. `auth login` exists only to save a
signed-in session for account-scoped work.
</principle>

<principle name="Never Invent A Filter Value">
StockX silently ignores an unknown filter id, an unknown filter value, and an
unknown sort id, returning the unfiltered default instead of an error. The CLI
validates every option against the vocabulary StockX publishes and exits
non-zero on anything else, so a rejected value means the value is wrong, not
the CLI. Use only:

- `--sort`: `featured` (default), `lowest-ask`, `highest-bid`, `release-date`.
  StockX publishes no reverse order, so `--desc` is always rejected; for
  descending price use `--sort highest-bid`.
- `--brand` and `--activity` (repeatable): slugs, e.g. `nike`, `adidas`,
  `basketball`. A display-case name such as `Nike` is not a StockX value.
- `--gender` (repeatable): `men`, `women`, `unisex`, `kids`.
- `--category` (repeatable): `sneakers`, `apparel`, `accessories`,
  `collectibles`, `shoes`, `trading-cards`.
- `--min-price` and `--max-price`: a range, so pass both or neither.
</principle>

<principle name="Use products market For Prices">
`products search` and `products list` carry a partial `market` block, but the
authoritative pricing view is `products market <url-key>`: lowest ask, highest
bid, ask counts, last sale, 72-hour and 90-day statistics, and per-size
`variants[].market`. Use `products get` for catalog attributes such as
`styleId` and `description`, not for prices.
</principle>

<principle name="Product Ids Are Url Keys">
`products get` and `products market` take the StockX url key (the last path
segment of a product URL, e.g.
`air-jordan-1-retro-high-og-shadow-brown`), not the UUID in a search result's
`id`. A full stockx.com product URL is also accepted. Take the url key from a
search result's `urlKey` or `url` field.
</principle>

<principle name="One Product Per Market Command">
`stockx products market` accepts one product key. It does not provide batch
market data. A caller loop must preserve each exit status and verify exact
requested, successful, failed, empty, and invalid JSON counts.
Do not use the loop's final exit status as proof of complete coverage.
</principle>

<principle name="Rapid Repeat Runs Are Rate Limited">
stockx.com rate-limits back-to-back browser sessions. If a run reports that
StockX did not serve its app payload, wait a few seconds and retry rather than
re-authenticating or changing configuration.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`stockx --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
