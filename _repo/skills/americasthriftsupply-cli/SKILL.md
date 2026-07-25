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
| Crawl the full catalog (~1806 products, multi-page) | `americasthriftsupply products list --limit 2000 --page-delay 30` |
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

<principle name="Rate Limiting And Pacing Multi-Page Crawls">
The public storefront JSON endpoints are rate-limited (HTTP 429 `local_rate_limited`, often with a `Retry-After` header of ~60s). The CLI retries with exponential backoff honoring `Retry-After`; never issue rapid manual/raw requests outside the CLI.

**Known-good rates:** collection-scoped requests (`--collection item-shop`, `last-chance`, `vintage-shop` — roughly 150-200 products each, one page) succeed reliably when spaced about 60 seconds apart. A full-catalog crawl is ~1806 products across 8 pages of 250 and WILL be rate-limited if paged back-to-back.

**`--page-delay SECONDS` (default `5`)** on `products list` and `collections list` waits between two consecutive *live* page requests. It never delays a single-page request (`--limit` up to 250), and never delays a page served from cache. For a full-catalog crawl, start at `--page-delay 30`:

```bash
americasthriftsupply products list --limit 2000 --page-delay 30
```

Prefer collection-scoped requests over full-catalog crawls whenever the target category is known.
</principle>

<principle name="Page-Level Caching And Crawl Resume">
Every page is written to the response cache the moment it arrives (`_fetch_page_<hash>.json` under `~/.local/share/cli-tools/americasthriftsupply/authentication_profiles/<profile>/cache/`), not once per completed crawl. Consequences:

- A crawl that dies partway through keeps its completed pages. **Re-running the same command resumes at the first uncached page** — cached pages cost no request and no `--page-delay` wait.
- Page size is fixed at 250, so a page cached by one run is reused by runs with a different `--limit`.
- The resume window is `CACHE_TTL` (default 3600s).
- Do NOT pass `--no-cache` to a multi-page crawl. It disables page persistence, so a rate-limited crawl restarts at page 1 with nothing salvaged.
- `americasthriftsupply cache clear` discards cached pages and forces a fresh crawl.
</principle>

<principle name="Interpreting A Rate-Limit Failure">
When retries and backoff are exhausted the command exits **non-zero** and writes an explanation to stderr (stdout stays data-only), e.g.:

```
Error: HTTP 429: local_rate_limited
Crawl of /products.json stopped after 7 page(s) yielding 1750 products.
Those 7 page(s) are cached at <cache dir> - re-run the same command to resume from page 8 without re-requesting them (cache TTL 3600s).
Retry with a slower pace, e.g. --page-delay 30 (current: 5s). Run 'americasthriftsupply cache clear' to discard cached pages and start over.
```

Recovery: re-run the SAME command with a larger `--page-delay`. Do not treat the non-zero exit as "no data available" — the reported pages are on disk and the retry only fetches what is missing. If the message instead says caching is disabled, the run used `--no-cache`; drop that flag before retrying.
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
