---
name: shopsalvationarmy-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute shopsalvationarmy operations using the `shopsalvationarmy` CLI tool.
  CLI interface for Shop Salvation Army — search listings, browse categories, view item details.
  Triggers: shopsalvationarmy, shopsalvationarmy cli, salvation army shop, search salvation army, salvation army listings, salvation army items, browse salvation army, salvation army categories, salvation army auction
---

<objective>
Execute shopsalvationarmy operations using the `shopsalvationarmy` CLI. All shopsalvationarmy interactions should use this CLI.
</objective>

<quick_start>
The `shopsalvationarmy` CLI follows this pattern:
```bash
shopsalvationarmy <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Search for items | `shopsalvationarmy search query "keywords"` |
| Search with filters | `shopsalvationarmy search query "keywords" -c jewelry --sort price_low` |
| Browse all items | `shopsalvationarmy search query` |
| List categories | `shopsalvationarmy search categories` |
| Get item details | `shopsalvationarmy search get ITEM_ID` |
| Check auth status | `shopsalvationarmy auth status` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `shopsalvationarmy` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **search** — Search and browse item listings: query for items, list categories, get item details
- **auth** — Manage authentication: login, logout, check status
</principle>

<principle name="Listing Detail Is The Seller Evidence Path">
Use `search get <id>` for listing and seller evidence. Its single detail-page
request returns `seller_name`, `description`, `image_urls`, prices, and
fulfillment data. Do not fetch the returned `url` with a generic URL reader.
The site rejects Python's default URL reader with HTTP 403, while the CLI uses
the service-compatible request headers.
</principle>

<principle name="Fulfillment: read `shipping_options`, never a price or a quote">
`search get <id>` reports the listing's "Shipping Options" panel as **which
options the seller offers** (`shipping_options`) separately from **what each
one costs**. To answer "does this listing ship?", read `shipping_options` — do
not infer it from `shipping_cost`, `shipping_params`, or `shipping_quote_status`.

| Field | Meaning |
|-------|---------|
| `shipping_options.local_pickup` | The panel has a "Local Pick Up:" row |
| `shipping_options.flat_rate` | The panel quotes a flat shipping price outright |
| `shipping_options.carrier_calculator` | The panel offers live carrier-rate buttons |
| `local_pickup_price` | Cost of pickup (normally `0.0`) |
| `standard_shipping_label` | Seller's own label for the flat rate — varies ("Standard Shipping", "UPS Ground") |
| `standard_shipping_price` | The flat shipping price |
| `standard_shipping_additional_item_price` | The "($N as additional item)" price, when present |
| `shipping_carriers` | Carriers offering live rates, e.g. `["usps", "ups"]` |
| `shipping_params` | Live-quote request payload only — **not** evidence that shipping is offered |

`shipping_quote_status` describes the **live carrier quote only**:

- `quoted` — a live rate came back; `shipping_cost` / `shipping_total` / `total_price` are populated
- `destination_required` — a calculator exists and the quote payload is present, but no destination was quoted
- `unavailable` — a calculator exists and the quote failed or returned no rate. **The rate is unknown; this does NOT mean the seller refuses to ship.**
- `not_applicable` — the listing has no live-rate calculator at all (flat-rate or pickup-only listings)

Listing 562200044 is the worked example: `local_pickup` **and** `flat_rate`
are true, `standard_shipping_price` is `46.0`, and `carrier_calculator` is
false — so `shipping_carriers` is empty and `shipping_quote_status` is
`not_applicable`. A consumer that reads only the quote fields would wrongly
call that listing pickup-only.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** — Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>
