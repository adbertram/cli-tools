---
name: americasthriftsupply-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute Americasthriftsupply operations using the `americasthriftsupply` CLI tool.
  CLI interface for America's Thrift Supply (americasthriftsupply.com), a Shopify storefront selling LEGO mystery boxes and other liquidation/mystery-box products. Public, unauthenticated catalog reads only -- no login required.
  Triggers: americasthriftsupply, americasthriftsupply cli, lego mystery box, thrift supply mystery box
---

<objective>
Execute America's Thrift Supply catalog operations using the `americasthriftsupply` CLI. All americasthriftsupply.com product/collection lookups should use this CLI instead of ad hoc curl/browser access.
</objective>

<quick_start>
The `americasthriftsupply` CLI follows this pattern:
```bash
americasthriftsupply <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List/search products | `americasthriftsupply products list --filter "title:ilike:%lego%" --table` |
| List products in one collection (server-side) | `americasthriftsupply products list --collection mystery-box --table` |
| Newest products first (default) / oldest first | `americasthriftsupply products list --sort newest [--desc]` |
| Products by price low->high / high->low | `americasthriftsupply products list --sort price [--desc]` |
| Get one product by handle | `americasthriftsupply products get lego-mystery-box --table` |
| List collections (categories) | `americasthriftsupply collections list --table` |
| Get one collection by handle | `americasthriftsupply collections get mystery-box --table` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `americasthriftsupply` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `americasthriftsupply --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="No Authentication">
This CLI has no `auth` command group. It reads America's Thrift Supply's public Shopify storefront JSON endpoints (`/products.json`, `/products/{handle}.js`, `/collections.json`, `/collections/{handle}.json`, `/collections/{handle}/products.json`), which require no API key, login, or browser session.
</principle>

<principle name="Command Groups">
- **products** -- `list` (catalog browse/search via `--filter`, optionally scoped to one collection with `--collection`) and `get <handle>` (full detail with live per-variant availability)
- **collections** -- `list` and `get <handle>` (store categories, e.g. `mystery-box`, `lego`)
- **cache** -- Local response cache management
</principle>

<principle name="Search Has No Server-Side Full-Text Endpoint">
The storefront exposes no public full-text search JSON endpoint. Search is done with `products list --filter "title:ilike:%<term>%"` (client-side over the fetched page) or, more reliably for a known category, `products list --collection <handle>` (server-side, scoped by the store's own collection).
</principle>

<principle name="Sorting (products list)">
`products list` supports the Source-CLI Sort Standard: `--sort/-s` (default `newest`) plus `--desc/-d`. Canonical fields: `newest` (natural = newest-listed first) and `price` (natural = low->high). `--desc` reverses the natural direction. The Shopify JSON endpoints ignore `?sort_by=`, so sorting is applied client-side over the returned result set (up to `--limit`). An unknown `--sort` value fails fast with a clear error and non-zero exit.
</principle>

<principle name="Rate Limiting">
The public storefront JSON endpoints are rate-limited (HTTP 429 with a `Retry-After` header, commonly 60s). The CLI already retries with exponential backoff honoring `Retry-After`; avoid issuing many rapid manual/raw requests outside the CLI.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`americasthriftsupply --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
