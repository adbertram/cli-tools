---
name: vinted-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute Vinted operations using the `vinted` CLI tool.
  Search Vinted marketplace listings and read single listing detail. The CLI needs no account, no API key, and no login.
  Triggers: vinted, vinted cli, search vinted, vinted listings, vinted prices, what is selling on vinted, find on vinted.
---

<objective>
Execute Vinted operations using the `vinted` CLI. All Vinted interactions should use this CLI.
</objective>

<quick_start>
The `vinted` CLI follows this pattern:
```bash
vinted <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Clear the Cloudflare check (run once) | `vinted auth login` |
| Check the saved session | `vinted auth status` |
| Search listings, newest first | `vinted listings search "lego bulk lot" --limit 25` |
| Search as a table | `vinted listings search "lego" --limit 25 --table` |
| Cheapest first | `vinted listings search "lego" --sort price --limit 10` |
| Most expensive first | `vinted listings search "lego" --sort price --desc --limit 10` |
| Limit the price range | `vinted listings search "lego" --min-price 5 --max-price 25 --currency USD` |
| Limit the condition | `vinted listings search "lego" --condition new-with-tags` |
| Select output fields | `vinted listings search "lego" --properties "id,title,price,url"` |
| Get one listing | `vinted listings get 9571854910` |
| Add shipping to a search | `vinted listings search "lego" --limit 10 --include-shipping` |
| Clear the response cache | `vinted cache clear` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `vinted` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `vinted --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="No Vinted Account, But A Browser Session Is Required">
There is no Vinted password, API key, or token, and no secret-manager entry.
Cloudflare fronts Vinted, so the CLI keeps a browser session that holds the
Cloudflare clearance. `vinted auth login` opens one real Chrome window to earn
it; every later command reuses the profile headless with no window.

If a command reports a Cloudflare check or `vinted auth status` shows
`authenticated: false`, run `vinted auth login --force`. Do not look for a
password or an API key.
</principle>

<principle name="Shipping Costs One Request Per Listing">
Neither the catalog endpoint nor the search results page carries shipping.
`--include-shipping` reads one item page per listing, about 1.5 seconds each, so
keep `--limit` small and leave the cache on.

`vinted listings get` always includes shipping, because it already reads the
item page. No account and no zip code are needed. The `shipping.price` value is
Vinted's estimate for a buyer with no address, not a checkout quote.
</principle>

<principle name="The CLI Paces Its Own Requests">
Every request passes through one rate limiter. It keeps 0.9 seconds between
requests, doubles that gap on HTTP 429 or 503, retries the same request up to
four times with exponential backoff, and narrows the gap again after five clean
requests. A `Retry-After` header wins over the computed delay.

Do not add your own sleep between commands, and do not retry a throttling error
yourself. An HTTP 429 error means the CLI already spent all four retries. Wait a
few minutes, then use a smaller `--limit`.
</principle>

<principle name="Newest First By Default">
`vinted listings search` returns listings strictly newest first unless `--sort`
says otherwise. Vinted's own order is only approximate, so the CLI sorts the
result on the `listed_at` field. Read `listed_at` to confirm recency; the
listing ID does not track it.
</principle>

<principle name="Search Is The Only Way To Discover IDs">
Vinted's catalog endpoint answers a query. There is no command that enumerates
listings without one. Use `vinted listings search` to find listing IDs, then
pass an ID to `vinted listings get`.
</principle>

<principle name="Get Adds Six Fields That Search Omits">
`vinted listings get` reads the item page, so it adds `description`, `category`,
`catalog_id`, `color`, `total_price`, and `shipping`. It omits `seller_login`,
`view_count`, `favourite_count`, and `listed_at`, which only search reports.

`condition` and `size` carry the same labels in both commands, so a search
result and a detail record compare directly. Pass the `catalog_id` value to
`--catalog-id` on a later search to find similar listings.

A listing can report `is_hidden: true`, `is_reserved: true`, or `is_closed:
true`. Check those before you treat a listing as available.
</principle>

<principle name="Sort Vocabulary">
`--sort` accepts `newest` (default), `price`, and `relevance`. `--desc`
reverses the field's natural direction and works only with `--sort price`.
Vinted offers no reverse order for `newest` or `relevance`, so the CLI rejects
those combinations with exit code 1. Do not pass directional names such as
`price_high`.
</principle>

<principle name="Condition Vocabulary">
`--condition` is repeatable and accepts `new-with-tags`, `new-without-tags`,
`very-good`, `good`, and `satisfactory`. Any other value fails.
</principle>

<principle name="Country Sites">
Each Vinted country site holds its own inventory and currency. The default is
`https://www.vinted.com`. To search another site, change `BASE_URL` in
`~/.local/share/cli-tools/vinted/.env`, for example `https://www.vinted.co.uk`
or `https://www.vinted.fr`.
</principle>

<principle name="Internal Endpoints">
The CLI calls Vinted's internal front-end endpoints. They are not a published
contract, and Vinted can change them without notice. If a command starts to
fail with an HTTP error or a parse error, treat it as a CLI defect and route
the repair to cli-tool-expert.
</principle>

<principle name="Command Groups">
- **auth** -- Browser session that holds the Cloudflare clearance
- **listings** -- `search` for catalog search, `get` for one listing's detail
- **cache** -- Local response cache management
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`vinted --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples, output contract, and limitations.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
