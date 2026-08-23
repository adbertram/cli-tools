---
name: ebay-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute ebay operations using the `ebay` CLI tool.
  eBay CLI -- seller tools, marketplace categories, and account management.
  Triggers: ebay, ebay cli, ebay orders, ebay inventory, ebay listings, list ebay orders, create ebay listing, ebay shipping, ebay messages, ebay seller, ebay categories, ebay policies
---

<objective>
Execute ebay operations using the `ebay` CLI. All ebay interactions should use this CLI.
</objective>

<quick_start>
The `ebay` CLI follows this pattern:
```bash
ebay <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check current user | `ebay whoami --table` |
| List orders | `ebay seller orders list --table` |
| Get order details | `ebay seller orders get ORDER_ID` |
| List inventory | `ebay seller inventory list --table` |
| Create listing | `ebay seller listings create --sku SKU ...` |
| Create store category | `ebay seller store categories create "NAME" --yes` |
| Create fulfillment policy | `ebay seller policies create ... --yes` |
| Publish listing | `ebay seller listings publish OFFER_ID` |
| Upload image | `ebay seller images upload FILE_PATH` |
| List messages | `ebay seller messages list --table` |
| Enable Time Away | `ebay seller store time-away enable <end_date> --yes` |
| Disable Time Away | `ebay seller store time-away disable --yes` |
| Search categories | `ebay categories list "keyword"` |
| Search completed/sold comps | `ebay listings search "<q>" --sold --limit 5` |
| Search US-only sold comps | `ebay listings search "<q>" --sold --us-only --limit 5` |
| Discover ACTIVE listings | `ebay listings search "<q>" --active --format bin --sort newest` |
| Active auctions (time-left/bids) | `ebay listings search "<q>" --active --format auction --sort ending` |
| Active item detail | `ebay listings get <item_id>` |
| Fulfillment for one item | `ebay listings get <item_id> -p item_id,ships,local_pickup,item_location` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `ebay` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Marketplace Search Page Limit">
eBay provides at most four marketplace search result pages. Therefore,
`ebay listings search` returns up to 960 results. It prints a warning when
`--limit` requests more results than those four pages provide.
</principle>

<principle name="One Item Per Detail Command">
`ebay listings get` accepts one item id. It does not provide batch detail.
A caller loop must preserve each exit status and verify exact requested,
successful, failed, empty, and invalid JSON counts.
Do not use the loop's final exit status as proof of complete coverage.
</principle>

<principle name="Completed Search Browser Session">
Completed and sold searches require an authenticated browser session. Run
`ebay auth login --credential-type browser_session` before those searches.
Active search and active item detail remain public.
</principle>

<principle name="Item Fulfillment Fields">
`ebay listings get <item_id>` reports fulfillment from eBay's own label rows on
the item page, not from the shipping price alone:

- **`ships`** (bool) — the `Shipping:` row quotes a rate, a free-shipping
  phrase, or a delivery estimate. The row's trailing "See details for shipping"
  link is not a quote, so a listing that does not ship reports `ships: false`.
- **`local_pickup`** (bool) — the `Pickup:` row is present (buyer can collect in
  person).
- **`item_location`** (str) — the origin from the shipping row's
  `Located in: <city, state, country>` line. Omitted from JSON output on
  pickup-only listings, because eBay only prints that line inside the shipping
  row.
- **`shipping_price`** (str) — unchanged: the numeric rate. Omitted when there
  is no rate. Read `ships`, not `shipping_price`, to decide whether a listing
  ships; a missing `shipping_price` alone cannot tell "local pickup only" apart
  from "the rate did not parse".

A page with neither fulfillment row is an error (`BrowserError`), not a listing
with no fulfillment — treat it as a scraping failure and retry or investigate.
Both `ships` and `local_pickup` can be true; item 157780039676 is that case.
</principle>

<principle name="Command Structure">
Top-level (admin/agnostic):
- **whoami** — Display current user details and scopes
- **auth** — Manage eBay API authentication (OAuth)
- **auth** -- Authentication commands and nested `auth profiles` management
- **categories** — Search and browse marketplace categories
- **listings** — Browser-based marketplace search and item detail. Completed
  search requires a browser session. Use `--active` for public live BIN or
  auction listings. `listings get <item_id>` remains public.

Under `ebay seller`:
- **orders** — View orders and fulfillment details
- **shipping-labels** — Create, void, and download shipping labels
- **shipping-quote** — Get shipping rate quotes
- **inventory** — Manage inventory items (SKUs)
- **listings** — Manage listings lifecycle (create, publish, unpublish, delete)
- **templates** — Manage listing templates
- **policies** — Manage fulfillment (shipping) policies
- **payment-policies** — View payment policies
- **return-policies** — View return policies
- **images** — Upload and manage listing images
- **locations** — Manage merchant/inventory locations
- **messages** — Manage seller messages and buyer inquiries
- **store** — Manage eBay store settings, categories, and Time Away
</principle>

<principle name="Seller Mutation Guards">
Preview store category and fulfillment policy requests with `--dry-run`.
Use `--yes` only after you verify the request.
Omit `destinationParentCategoryId` to create a top-level store category.
Use `--exclude-us-special-locations` only with `EBAY_US`.
Set template `pricing.allowOffers` to `true` to enable Best Offer.
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
