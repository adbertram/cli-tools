---
name: facebook-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute facebook operations using the `facebook` CLI tool.
  Facebook CLI via Playwright browser automation -- Marketplace search, Messenger conversations, Groups posts, and caching.
  Triggers: facebook, facebook cli, facebook marketplace, facebook messenger, facebook groups, search facebook marketplace, facebook messages, send facebook message, facebook message requests, facebook group posts, read facebook group, list facebook groups
---

<objective>
Execute facebook operations using the `facebook` CLI. All facebook interactions should use this CLI.
</objective>

<quick_start>
The `facebook` CLI follows this pattern:
```bash
facebook <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Search Marketplace | `facebook marketplace list --query "LEGO" --table` |
| Browse Today's picks | `facebook marketplace list --table` |
| Get listing details | `facebook marketplace get ITEM_ID` |
| List group posts | `facebook groups list GROUP_ID --table` |
| Get a group post | `facebook groups get GROUP_ID/posts/POST_ID` |
| List conversations | `facebook messenger list --table` |
| Read messages | `facebook messenger get CONVERSATION_ID` |
| Send message | `facebook messenger send CONVERSATION_ID --text "Hello"` |
| Check auth status | `facebook auth status` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `facebook` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **groups** — Read posts from Facebook Groups (list, get)
- **marketplace** — Search and browse Facebook Marketplace (list, get with price/location filters)
- **messenger** — Messenger conversations (list, get, send, requests)
- **auth** — Manage authentication via headed browser (login, logout, status, test)
- **auth** -- Authentication commands and nested `auth profiles` management
- **cache** — Manage response cache (clear)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** — Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<principle name="Group Comment Verification">
`facebook groups posts comment` and `facebook groups posts reply` perform multi-stage verification after submitting (composer-cleared → comment-count delta → markdown-stripped text-on-page) and return:

- `verification`: `"confirmed"` (any stage fired) or `"render-timeout-likely-success"` (stage 1 fired, stages 2-3 inconclusive — treat as success).
- `verificationDetails.signal`: which stage confirmed (`composer-cleared`, `count-delta`, `text-appeared`, or `composer-cleared-but-no-other-evidence`).
- `verificationDetails.commentCountBefore` / `commentCountAfter`: `[role="article"]` count delta inside the post.

A non-zero exit ONLY happens when all three verification signals fail (true submit failure). Never retry on `render-timeout-likely-success` — duplicate comments are worse than missed verification.

Facebook strips Markdown (`**bold**`, `[label](url)`) when rendering comments — never use raw substring matching against submitted text to verify a comment landed.
</principle>

<principle name="Marketplace Prices, Currency, and Empty Results">
Every Marketplace record carries three price fields on BOTH `marketplace list` and `marketplace get`:

- `price` — the current/active asking price.
- `original_price` — the struck-through pre-drop price, or `null` when the seller never lowered it. A non-null value means the listing has been discounted.
- `price_currency` — the currency symbol Facebook rendered, verbatim (`"$"`, `"CA$"`, `"£"`). Marketplace shop listings are priced in the seller's currency, so compare `price` across listings ONLY when `price_currency` matches. Never assume USD.

Facebook renders a discounted listing as the current price immediately followed by the struck-through original with NO separator (`$15$20`, `$850$1,100`). Both surfaces read the price element's own text for the current price and the nested struck-through element for the original, so the two are never concatenated. Never re-derive a price by string-splitting a rendered price blob.

`marketplace list` returns `[]` with exit 0 ONLY when Facebook renders its own results container together with `No listings found for "..." within N miles`. Every other empty outcome exits non-zero and names the cause (results container never rendered, page never settled, blocked, or listing tiles the extractor could not read). Treat a silently empty result as impossible: if `list` exits 0 with `[]`, Facebook genuinely has no matches.

`marketplace get` and `marketplace list --include-detail` return `image_urls` on every call. `--download-images` is a separate, optional step that ALSO writes those images to a local cache and reports the paths in `local_images`.

Both cover only the listing's own media gallery (hero image plus thumbnails). Sidebar advertisement creatives and recommended-listing images are excluded.

`image_urls` is `null` on a `list` row read without `--include-detail` (the gallery was never opened) and `[]` when the gallery was read and the listing has no photos. Those are different answers and are not collapsed.
</principle>

<principle name="Marketplace Delivery Types (Fulfillment)">
Every Marketplace record carries `delivery_types` on BOTH `marketplace list` and `marketplace get` — Facebook's own per-listing fulfillment model, reported VERBATIM and unnormalized. Observed tokens (live 2026-07-26): `IN_PERSON`, `PUBLIC_MEETUP`, `DOOR_PICKUP`, `DOOR_DROPOFF` (all local collection/delivery) and `SHIPPING_ONSITE` (ships via Facebook checkout). Treat any token starting with `SHIPPING` as "this listing ships"; a token Facebook adds later passes straight through rather than being dropped.

`null` means UNKNOWN. It NEVER means "no shipping offered".

- `marketplace get` never returns `null` — an unreadable fulfillment model exits non-zero, including for a stale cached record (`facebook cache clear` then retry).
- `marketplace list` returns `null` only for a tile Facebook's own payload never described, and prints a warning naming those listing IDs. The known case is the injected "commerce_interesting_product" notification tile. Re-read those IDs with `marketplace get`.
- The field is never `[]`; the model rejects an empty list, because `[]` reads as "offers no fulfillment at all".

Never infer fulfillment from rendered text. The detail page shows only the seller's free-form meet-up prose, and a search tile shows a place name OR the string "Ships to you" — that choice is a DISTANCE decision, not a fulfillment one, so a shipping-capable listing near the viewer still renders a place name. Reading the prose or the tile text will get the answer wrong.

`location` on `get` now comes from Facebook's own `location_text` (the previous "Listed in " text parse never matched, which is why `get` returned `location: null`); carrying location from the `list` row is no longer necessary. On `list`, a tile rendering "Ships to you" reports `location: null` rather than that string.
</principle>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>

## Known Issues

### 1. Authentication expires shortly after a successful headed login

**Symptom:** `facebook auth login` succeeds and commands work initially, but later the same day `facebook auth status` reports unauthenticated and the persistent cookie database no longer contains Facebook's authenticated `c_user` cookie.

**Cause:** Login used normal headed Chrome's `Chrome/<version>` User-Agent, while subsequent autonomous commands used headless Chrome's default `HeadlessChrome/<version>` User-Agent against the same persistent profile. That abrupt fingerprint change is a Facebook risk signal and can invalidate the server-side session even though the on-disk profile is reused correctly.

**Fix:** `facebook_cli.config.Config.browser_user_agent` now derives the normal Chrome User-Agent from the installed Chrome binary and supplies it to both headed and headless browser launches. This preserves one browser fingerprint across login and command reuse without forcing routine automation into a visible browser. `BROWSER_USER_AGENT` remains an explicit override.

**Verification:** The focused auth test asserts the Facebook config returns a non-headless real-Chrome User-Agent. A browser boundary test launches the actual headless browser against a local HTTP endpoint and confirms both `User-Agent` and `sec-ch-ua` advertise Google Chrome without a `Headless` token. After reauthentication, verify the live service path with `facebook auth status` and a read-only Facebook command.

### 2. Group comment posting fails: "Expected one target article for post <id>, found 0"

**Symptom:** `facebook groups posts comment <group>/posts/<id> -m "..."` aborts during composer activation with `Error: Failed to activate comment composer: Expected one target article for post <id>, found 0`. Nothing is typed or submitted. The READ path (`facebook groups posts get ...`) on the same post still works, so auth/session is healthy — only the comment-WRITE locator is broken.

**Cause:** A Facebook DOM structure change. The comment-composer activator in `facebook_cli/client.py::comment_on_post` required exactly one `[role="article"]` inside `[role="main"]` that BOTH contained a post-permalink anchor AND a "Comment" control. Facebook moved the post-permalink anchor and the comment controls OUT of the `[role="article"]` wrapper. Verified against the live DOM on the permalink page: the post-permalink anchor's `closestArticle === false` (it is no longer inside any article), the `[role="main"]` article wrappers contain zero anchors and zero comment controls, and the post's comment composer (a single visible `[role="textbox"][contenteditable="true"][data-lexical-editor="true"]`) is rendered in a React portal OUTSIDE `[role="main"]` (`inMain === false`). So the "one article containing both" requirement matched 0 articles and aborted. Note: the hardcoded permalink href patterns (`/groups/<gid>/posts/<pid>/`) were NOT the problem — those anchors still match; the article-scoping was the broken assumption.

**Fix:** Rewrote the `js_activate` locator in `comment_on_post` to stop requiring a `[role="article"]` match. Because the CLI navigates to the canonical single-post permalink URL (which isolates exactly one target post), the activator now: (1) detects an already-visible comment composer DOCUMENT-WIDE (it lives in a portal outside `[role="main"]`) and uses it when exactly one exists; (2) only if none is present, clicks the post's Comment activator scoped to `[role="main"]`, matched by exact text "comment" or aria-label `leave a comment`/`write a comment`/`comment as`, requiring uniqueness. Post identity stays pinned by the canonical URL plus the existing `_wait_for_comment_on_exact_post` verifier. A secondary trap: the already-visible-composer check must be DOCUMENT-WIDE, not scoped to `[role="main"]` — the composer's `inMain` is false, so a main-scoped check finds 0 and then wrongly clicks an activator that disrupts the open composer, causing a later "Could not find filled comment box" submit failure.

**Verification:** `facebook groups posts comment 2318028917/posts/<id> -m "..."` returned `success: true, verification: "confirmed", signal: "exact-post-comment-found"` with a new `commentId`. Independent read path confirmed `comment_count` incremented 5 → 6 and the comment text was present. (The facebook CLI has no delete-comment command; remove a test comment by driving the comment's `aria-label="Edit or delete this"` menu → Delete menuitem → confirm "Delete Comment?" dialog via the same authenticated session.)

**Recurrence Prevention:** The locator no longer depends on Facebook nesting the permalink anchor and comment controls inside a `[role="article"]`. It relies on the more stable invariants of a single-post permalink page: one visible Lexical composer document-wide, or one comment activator in `[role="main"]`. If Facebook changes the composer/activator selectors again, capture the live DOM FIRST (instantiate `FacebookClient`, call `_get_page(url)`, then `page.evaluate(...)` to dump article/anchor/composer facts) before editing — diagnose from the live page, never from assumptions. The aria-label for the inline activator is currently "Leave a comment"; the composer's `aria-placeholder` is personalized (e.g. "Answer as Adam"), so never match on placeholder text.

### 3. `marketplace list` returned `[]` with exit 0 on a healthy session; `get` returned digit-concatenated prices

**Symptom (2026-07-25):** Two failures on a fully authenticated session. (a) `facebook marketplace list --query "lego"` intermittently returned `[]` with exit 0 and `Loaded 0 listing(s) after 1 scroll(s)`, while an immediate identical retry returned 114 listings. (b) `facebook marketplace get <id>` returned a digit-concatenation of the current and struck-through original price on price-dropped listings — `$850` → `8501100.0`, `$15` → `1520.0` — on 8 of 28 listings in one run, while `list` reported the same items correctly.

**Cause:** Both were extraction bugs that failed silently.
- Facebook serves TWO Marketplace tile variants: aria-labelled (`"Arcade 1Up, $300, Newburgh, IN, listing 1356224139807798"`) and content-derived (`"Just listed $400 Legos. Collection with instruction books Boonville, IN"`). The old extractor parsed the flattened accessibility-tree name with regexes that only matched the aria-labelled form, so the content-derived variant parsed to ZERO listings — which the code then reported as an empty search. The aria-labelled form was also lossy: tiles with an empty location segment (`"Lego Truck, $10, , listing 123"`, i.e. ships-to-you listings) were silently dropped, 10 of 22 on one live page.
- The detail-page extractor read the price from `main.innerText`, and Facebook renders a price drop as `<span>$15<span struck>$20</span></span>` — one text line, `"$15$20"`. The price normalizer stripped `$` and `,` and parsed `1520`.

**Fix (`facebook/facebook_cli/client.py`, `facebook/facebook_cli/models.py`):**
- `LIST_PAGE_LISTINGS_JS` extracts each tile from the DOM (`a[href*="/marketplace/item/"]`) instead of parsing the accessible name. The per-tile DOM is identical for both variants: a span whose OWN text nodes hold the current price (with the struck-through original as a nested span), then the title span, then the location span. Tiles that render text but no usable price/title are returned as `unparsed` and raise. `facebook_cli/parsers.py` was deleted.
- `DETAIL_PAGE_PRICE_JS` applies the same own-text-vs-nested-element split on the detail page, returning `{price, originalPrice}`. The split is structural, so it does not depend on Facebook's obfuscated CSS class names.
- `MARKETPLACE_PAGE_STATE_JS` + `_raise_for_empty_marketplace_results` make an empty extraction raise unless Facebook's own results container (`[aria-label="Collection of Marketplace items"]`) is present AND it printed `No listings found for "..." within N miles`.
- `_wait_for_marketplace_results` replaces the fixed settle delay with a real readiness wait (first item link, or Facebook's zero-result state), removing the "page not settled" window that produced the intermittent empties. No retry was added.
- `MarketplaceListing` gained `original_price` and `price_currency`. `normalize_price` now RAISES on an unrecognized price string instead of returning `None`.
- Both extractors match the price as a Unicode currency symbol (`\p{Sc}`) with an optional currency-code prefix, so `$15`, `CA$75`, and `£1,600` all parse. Live Evansville results carry all three; the fail-loud tile check surfaced the `CA$` and `£` shapes, which the previous parser dropped silently.
- Tiles are re-checked for up to 5s before the unreadable-tile error fires, because Facebook's virtualized grid can paint a tile's title before its price. That is a readiness wait on a deterministic condition, not a retry of a failed read.

**Verification:** All 8 reported item IDs re-read live and returned the correct current price with the pre-drop price in `original_price` (`1543005510652070` → `price: 850.0, original_price: 1100.0`). `list --query lego --limit 120` returned 120 (140 loaded, previously 116). A nonsense query returned `[]` with exit 0 and the `No listings found` message. Regression coverage in `facebook/tests/test_marketplace_extractors.py` against verbatim live DOM in `facebook/tests/fixtures/`.

**Recurrence Prevention:** Never parse a Marketplace accessible name as a string — read the tile/price DOM. A currency-prefixed price (`CA$75`) is real and appears on both surfaces; `price_currency` preserves it so 75 CAD is never reported as 75 USD. Any new tile shape now fails loudly rather than shrinking the result set.

### 4. `--download-images` saved a sidebar advertisement as a listing image

**Symptom (2026-07-25):** `facebook marketplace get 26999388286428618 --download-images` saved two images, the second being a scraped GoDaddy domain advertisement rather than a listing photo.

**Cause:** The extractor took every `img[src*="scontent"]` with `naturalWidth > 100` that was not inside a recommended-listing anchor. Facebook serves sidebar ad creatives from the same `scontent` CDN, so a video ad in a `[role="group"][aria-label="Video player"]` slot passed the filter.

**Fix:** `DETAIL_PAGE_IMAGES_JS` scopes to the listing's own media gallery via `img[alt^="Product photo of"]`, the alt Facebook applies to the hero image and every gallery thumbnail. Ad creatives and recommended-listing tiles do not carry it.

**Verification:** After clearing the item's image cache, `get 26999388286428618 --download-images` saved exactly 1 image (the LEGO buckets photo, byte-identical to the previously-correct image 1) and `get 1543005510652070 --download-images` saved its 4 real gallery photos.

### 5. `marketplace list` raised "listing tile(s) still rendered without a recognizable price and title" on a healthy session

**Symptom (2026-07-26):** `facebook marketplace list --query "lego" --location evansville --sort newest --limit 100 --properties item_id,title,price,original_price,price_currency,location,url` exited 1 with `Error: 1 Facebook Marketplace listing tile(s) still rendered without a recognizable price and title after 5000ms. Facebook changed its tile markup and the CLI extractor needs updating. Samples: [{'item_id': '27542838245367180', 'text': 'UnreadHuge Lot thousands crayons,colored pencils... listed for $50.00.9h·4 saved'}]`. Auth was healthy (`facebook auth status` showed authenticated) and every other tile on the page parsed correctly.

**Cause:** A THIRD Marketplace tile variant, distinct from the two fixed in Known Issue #3. Facebook injects a "commerce_interesting_product" notification/recommendation tile into the search grid -- its `href` carries `?ref=notif&notif_id=...&notif_t=commerce_interesting_product`. Verified against the live DOM (instantiated `FacebookClient`, navigated to the Evansville "lego" search, dumped the tile's `outerHTML` and every `span`'s own text/children): unlike variants 1-2, this tile has NO dedicated price or title span at all. The title and price are each wrapped in their own `<b>` element inside one prose sentence, with an unrelated "Unread" badge `<div>` immediately before the title:
```html
<div>Unread</div><b>Huge Lot thousands crayons,colored pencils...</b> listed for <b>$50.00</b>.
```
The existing extractor only scans `span` elements for a price-shaped own-text node, so it found neither a price span nor a title span on this tile and correctly reported it `unparsed` rather than dropping it silently (the fail-loud behavior from Known Issue #3 working as designed) -- but the extractor itself needed the third shape added.

**Fix (`facebook/facebook_cli/client.py`):** `LIST_PAGE_LISTINGS_JS` now falls back to a second structural pass when the span scan finds no price/title on a tile: it looks for two `<b>` elements sharing the same parent element whose own text (the words connecting the two `<b>` elements) contains the literal phrase "listed for" -- the invariant Facebook renders for this notification-tile sentence. The first `<b>` is the title (read via its own text nodes, so the sibling "Unread" `<div>` is never included), the last `<b>` is the price (with the same nested-struck-through-element check used elsewhere for a discounted `original_price`). This tile shape carries no location field, so `location` is `null` rather than invented from the badge/relative-time text ("Unread", "9h", "4 saved"). The requirement that both `<b>` elements share a parent AND that parent's own text contains "listed for" keeps the fallback from misfiring on an unrelated pair of bold elements elsewhere in a tile.

**Verification:** Regression coverage added to `facebook/tests/test_marketplace_extractors.py` against verbatim live DOM appended to `facebook/tests/fixtures/marketplace_list_tiles.html` (item 27542838245367180) -- asserts the correct title/price/currency and a `null` location, plus a synthetic negative test confirming two unrelated `<b>` elements without "listed for" still report `unparsed`. Full suite: `86 passed`. Live re-run of the exact failing command exited `0`, loaded 114 listings (returned 100 per `--limit`), and item `27542838245367180` now extracts as `{"title": "Huge Lot thousands crayons,colored pencils...", "price": 50.0, "original_price": null, "price_currency": "$", "location": null}`.

**Recurrence Prevention:** The extractor now recognizes three tile shapes: aria-labelled, content-derived, and notification/prose. Any further Facebook tile markup change will still fail loudly via `unparsed` (Known Issue #3's fail-loud contract is unchanged) rather than silently dropping the listing. If a fourth shape appears, capture the live DOM FIRST -- instantiate `FacebookClient`/`get_client()`, navigate to the reproducing search, and dump the tile's `outerHTML` plus each `span`'s/`b`'s own text via `page.evaluate(...)` -- before editing `LIST_PAGE_LISTINGS_JS`, exactly as this fix and Known Issue #3 did.

### 6. `marketplace get` exposed no delivery type, and returned `location: null`

**Symptom (2026-07-26):** `facebook marketplace get 26999388286428618` returned `location: null` and no fulfillment field at all, so the only evidence of how the item could be collected was the seller's prose in `description` ("Meet on Kansas Road in Evansville \nEvansville, IN · Location is approximate"). Facebook Marketplace models fulfillment per listing, so a consumer had to guess — and guessing "local pickup only" from meet-up prose silently misprices anything that ships.

**Cause:** Both fields were being read from rendered text that does not carry them.
- Fulfillment is never rendered. The detail page shows only the seller's free-form meet-up sentence. A search tile shows either a place name or the literal string "Ships to you" — and that choice is a DISTANCE decision, not a fulfillment one, so a shipping-capable listing near the viewer still renders a place name. Verified live: item 1550889686417279 renders "Ships to you" yet carries `["SHIPPING_ONSITE","IN_PERSON"]`, while dozens of tiles rendering a place name carry `SHIPPING_ONSITE` too.
- `location` was parsed from a `main.innerText` line starting with `"Listed in "`. Facebook renders `"Listed 4 weeks ago in Evansville, IN"`, so that prefix never matched and the field was always `null` on `get`. The parse was effectively dead code.

The answer for both is in the Relay payload that hydrates the page, under Facebook's own GraphQL field names (captured live 2026-07-26):
```json
{"__typename":"GroupCommerceProductItem","id":"26999388286428618",
 "location_text":{"text":"Evansville, IN"},"delivery_types":["IN_PERSON"], ...}
```
Two transports carry it and neither alone is complete: `script[type="application/json"]` blobs in the served HTML (the detail page's own listing; a search page's first 24 tiles), and Relay pagination responses (every tile loaded by scrolling — XHR bodies, so a hook must be installed BEFORE scrolling).

**Fix (`facebook/facebook_cli/client.py`, `facebook/facebook_cli/models.py`):**
- `INSTALL_DELIVERY_CAPTURE_JS` seeds an `item_id -> delivery_types / location_text` map from the embedded blobs and hooks `XMLHttpRequest`/`fetch` for Relay pagination bodies (handling Facebook's multi-document streaming shape and its `for(;;);` prefix). `READ_DELIVERY_CAPTURE_JS` reads it back. Payloads that describe the same listing differently are recorded as conflicts and raise rather than resolving to whichever arrived first.
- `_extract_listing_fulfillment` raises `ClientError` when a listing has no `delivery_types`; `get_item` re-checks the contract OUTSIDE the `@cached` boundary (the cached worker is now `_fetch_item`) so a record written before this change cannot be replayed with the field silently absent.
- `_paginated_fetch` installs the capture before the first scroll and `_attach_delivery_types` sets each row, warning by ID for rows Facebook never described. `MarketplaceListing.delivery_types` rejects `[]`.
- The dead `"Listed in "` location parse was removed; `get` location now comes from `location_text`. A `list` tile rendering `"Ships to you"` reports `location: null` instead of that string as a place name.

**Verification:** `get 26999388286428618` → `location: "Evansville, IN"`, `delivery_types: ["IN_PERSON"]` (was `null` / absent). `get 1716979012677494` → `"Williamsburg, VA"`, `["IN_PERSON","SHIPPING_ONSITE"]`. `list --query lego --limit 100` covered 99/100 rows (vocabulary `IN_PERSON` 99, `DOOR_PICKUP` 23, `PUBLIC_MEETUP` 15, `SHIPPING_ONSITE` 2, `DOOR_DROPOFF` 2), zero rows carrying "Ships to you" as a location, and warned by ID for the one uncovered tile. Regression coverage in `facebook/tests/test_marketplace_delivery_types.py` against verbatim live fixtures, including replaying a real Relay pagination body through a real XHR. Full suite: `100 passed`.

**Recurrence Prevention:** Never read fulfillment from rendered text — not the description prose, not the tile's location slot. `delivery_types` is reported verbatim, so a token Facebook adds later flows through instead of being dropped, and `null` is reserved for UNKNOWN and must never be read as "no shipping offered". The one uncovered row is Facebook's injected "commerce_interesting_product" notification tile, whose listing data comes from the notifications feed rather than the search payload; `marketplace get` on that ID gives a definitive read. If the capture starts returning nothing, dump `script[type="application/json"]` contents and an XHR body from the live page FIRST and confirm Facebook's field names, exactly as this fix did.
