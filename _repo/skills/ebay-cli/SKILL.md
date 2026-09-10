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
| Active auctions (time-left/bids) | `ebay listings search "<q>" --active --format auction --limit 5` |
| Check SoldComps plan usage | `ebay quota --table` |
| Active item detail | `ebay listings get <item_id>` |
| Fulfillment for one item | `ebay listings get <item_id> -p item_id,ships,local_pickup,item_location` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `ebay` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Marketplace Search Runs On A Metered API">
`ebay listings search` calls the SoldComps API (`api.sold-comps.com`), not a
browser. It needs the `ebay-soldcomps-api-key` secret and NO browser session.

The plan is metered, so treat requests as a budget:

- `--limit` accepts up to 960. Every 200 results is one request against the
  monthly quota, and a `--limit` above 200 prints its cost on stderr first.
  Ask for the smallest `--limit` that answers the question.
- `--sold` searches ARE cached (a week by default), so repeating an identical
  sold search costs nothing. Do not add `--no-cache` unless the caller needs
  provably fresh data.
- `--active` searches are NEVER cached, by design.
- `ebay quota` reports the recorded plan usage and costs no request. Check it
  before a large batch of searches.
</principle>

<principle name="Search Capabilities Removed With The Scraper">
Two option combinations the browser scraper supported now fail fast with a
message naming what is missing. Do not retry them or work around them:

- **Unsold completed listings** — `--completed --no-sold`, and a bare
  `ebay listings search "<q>"` with neither `--sold` nor `--active`. SoldComps
  returns sold or active listings, nothing in between. Always pass `--sold` or
  `--active`.
- **`--sort ending`** (eBay's "ending soonest"), for active listings as well as
  completed. Use `--sort newest` or `--sort price`.
</principle>

<principle name="One Item Per Detail Command">
`ebay listings get` accepts one item id. It does not provide batch detail.
A caller loop must preserve each exit status and verify exact requested,
successful, failed, empty, and invalid JSON counts.
Do not use the loop's final exit status as proof of complete coverage.
</principle>

<principle name="Search And Item Detail Use Different Backends">
`ebay listings search` runs on the SoldComps API — no browser, no eBay sign-in,
no browser session. If it reports a missing API key, the fix is storing
`ebay-soldcomps-api-key` in the CLI-tools secret manager, never `ebay auth
login`.

`ebay listings get` and `ebay listings status` still scrape the public
`/itm/<id>` page through the stealth browser. Those pages are public, so they
need no session either, but they CAN hit eBay's interstitial walls (see Known
Issues).
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
- **quota** — SoldComps plan usage recorded from the last marketplace search
- **listings** — Marketplace search (SoldComps API) and item detail (browser).
  Pass `--sold` for sold comps or `--active` for live BIN/auction listings; one
  of the two is required. `listings get <item_id>` scrapes one public item page.

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

## Known Issues

### 1. `ebay listings get` / `ebay listings status` fail with an eBay interstitial page

**Applies to item-page scraping only.** Marketplace search moved to the SoldComps
API and no longer touches a browser, so this cannot affect `ebay listings
search`. The three walls below were captured live on 2026-08-28 against a search
URL, but they front every eBay page, including `/itm/<id>`.

**Symptom:** `ebay listings get <item_id>` intermittently exits 1 reporting a
page that did not load as expected, quoting a title such as `🐴 Error Page |
eBay` or a URL under `/splashui/`.

**Cause:** eBay fronts the same URL with **three** distinct walls that look alike
to a naive title check but need opposite handling. The original retry loop was
gated on a one-string title blocklist (`ERROR_PAGE_TITLE_MARKERS = ("Error
Page",)`), so `/splashui/challenge`, titled **"🐴 Pardon Our Interruption..."**,
was classified as a healthy page and returned to the caller, whose selector wait
then timed out and reported a misleading "page did not load" error.

This is **not** a stale-session symptom. It reproduces with `ebay auth status`
reporting `browser_session.authenticated: true`, and item pages are public
anyway.

| Wall | Signature | Behavior | Handling |
|------|-----------|----------|----------|
| `error` | title `🐴 Error Page \| eBay`, body `SORRY Something went wrong on our end <ref>` | eBay's **request-rate** wall. Sticky — held 8s+ without re-navigation and survived re-navigation at ~9.5s spacing | Jittered exponential backoff, then re-navigate |
| `challenge` | `/splashui/challenge`, title `🐴 Pardon Our Interruption...` | **Self-clearing** JS check ("your browser will redirect ... shortly") — resolved to real content on the next sample | **Waited out in place.** Re-navigating abandons the redirect eBay just issued and spends another request against the rate budget |
| `captcha` | `/splashui/captcha`, hcaptcha/recaptcha, "verify you are human" | Real human verification | **Hard stop** — never solved, clicked through, or reloaded around |

**Fix:** The handling lives in the shared engine as a declarative hook, so
`EbayBrowser` stays a declarative subclass
(`test_lean_cli_architecture.py::test_browser_automation_subclasses_are_declarative`).
`cli_tools_shared.auth` provides the `Interstitial` rule dataclass,
`classify_interstitial()`, and the `settle`/`reload`/`abort` strategies;
`BrowserAutomation.get_page` navigates via `_navigate_page` and then resolves the
walls declared in `INTERSTITIALS`, returning **only** once the page holds real
content. eBay declares its three rules in `EBAY_INTERSTITIALS` (most-severe
first, so a captcha can never be masked by a retryable rule). Sources:
`_repo/cli-tools-shared/cli_tools_shared/auth.py`, `ebay/ebay_cli/browser.py`.
Tests: `cli-tools-shared/tests/test_browser_interstitials.py`,
`ebay/tests/test_browser_error_interstitial.py`.

**Verification:** Run `ebay listings get 127992747834`. When the walls are hit,
stderr shows the retry working through them, e.g.:
```
Warning: error ('Error Page') interstitial detected (attempt 1/4) -- retrying <url> in 4.4s
Warning: browser-check ('Pardon Our Interruption') interstitial detected -- waiting for it to clear (0s/20s)
```
followed by the item JSON on stdout.

**Recurrence Prevention:** Resolution is central to `BrowserAutomation.get_page`,
so every browser-backed operation in every browser CLI inherits it. If eBay adds
or rotates a wall, add/adjust an `Interstitial` rule in `EBAY_INTERSTITIALS` — do
not reintroduce a bare title check, and do not treat "the title isn't the one bad
string" as proof the page is good. Match on the narrowest reliable signal (URL
path first, then title); broad body markers such as "something went wrong"
legitimately appear inside real listing content. If the rate wall starts
outlasting the backoff, raise
`INTERSTITIAL_MAX_ATTEMPTS`/`INTERSTITIAL_BASE_DELAY_MS` rather than shortening
the waits — tight reloads measurably deepen the throttle.

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>
