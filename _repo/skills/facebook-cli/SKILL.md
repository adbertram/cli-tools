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
| Search NATIONWIDE (ships) | `facebook marketplace list --query "LEGO" --delivery-method shipping` |
| Browse Today's picks | `facebook marketplace list --table` |
| Get listing details | `facebook marketplace get ITEM_ID` |
| Check listing availability | `facebook marketplace status ITEM_ID` |
| List your groups + pending requests | `facebook groups list --limit 100 --table` |
| Check a group's privacy/membership | `facebook groups get GROUP_ID` |
| List group posts | `facebook groups posts list GROUP_ID --table` |
| Get a group post | `facebook groups posts get GROUP_ID/posts/POST_ID` |
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
- **groups** — Enumerate your groups and pending join requests (`groups list`), read one group's privacy/membership/readability (`groups get`), and read or write its posts (`groups posts list|get|create|comment|reply`)
- **marketplace** — Search, browse, inspect, and check Facebook Marketplace listings (list, get, status)
- **messenger** — Messenger conversations (list, get, send, requests)
- **auth** — Manage authentication via headed browser (login, logout, status, test)
- **auth** -- Authentication commands and nested `auth profiles` management
- **cache** — Manage response cache (clear)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** — Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<principle name="Group Membership, Privacy, and Readability">
Whether a group's posts can be read is a function of the group's privacy AND the
authenticated account's membership. Both are reported by `facebook groups get`,
read from the live group page and never inferred:

- `privacy` — `"public"` or `"private"`.
- `membership` — `"member"`, `"pending"` (join request submitted, not yet approved), or `"non_member"`.
- `posts_readable` — whether THIS session can actually read the group's posts. A member always can; a non-member or pending requester can read a public group and cannot read a private one.

An unknown Facebook privacy label or `viewer_join_state` raises instead of
defaulting, so a Facebook change surfaces as a loud failure rather than a group
silently reported as unreadable (or readable).

`facebook groups posts list` on an unreadable group exits **1** and writes a
stderr message starting with the stable marker `UNREADABLE_GROUP:`, naming the
privacy and membership that produced it. It NEVER returns `[]` with exit 0 for a
group this session cannot see — that silent-empty made a private group with a
pending join request indistinguishable from a group with no new posts. The exit
contract for `groups posts list`:

| Outcome | Exit | stdout | stderr |
|---------|------|--------|--------|
| Readable group, posts found | 0 | post array | progress only |
| Readable group, no posts in window | 0 | `[]` | progress only |
| Unreadable group | 1 | (empty) | `Error: UNREADABLE_GROUP: ...` |
| Credential failure | 2 | (empty) | `Error: ...` |

Before crawling a group you have not confirmed, call `facebook groups get
<group_id>` and gate on `posts_readable`.

`facebook groups list` returns BOTH joined groups and pending join requests,
joined first, each row carrying `membership`. Filter with
`--filter "membership:eq:member"` when only joined groups matter. Every row
carries `group_id`, `name`, and `url`; `group_id` is Facebook's own URL
reference — the numeric id, or the vanity slug for groups that have one, and
every `facebook groups ...` command accepts either. Facebook renders neither
privacy nor member counts on that page, so `privacy`, `posts_readable`, and
`member_count` are `null` on `list` rows — run `groups get` for those. `--limit`
caps how many rows are read from the scrolled page, so pass a limit at or above
the counts Facebook prints in its own section headings ("All groups you've
joined (34)", "Pending group requests (7)") to enumerate everything.
</principle>

<principle name="Group Comment Verification">
`facebook groups posts comment` and `facebook groups posts reply` perform multi-stage verification after submitting (composer-cleared → comment-count delta → markdown-stripped text-on-page) and return:

- `verification`: `"confirmed"` (any stage fired) or `"render-timeout-likely-success"` (stage 1 fired, stages 2-3 inconclusive — treat as success).
- `verificationDetails.signal`: which stage confirmed (`composer-cleared`, `count-delta`, `text-appeared`, or `composer-cleared-but-no-other-evidence`).
- `verificationDetails.commentCountBefore` / `commentCountAfter`: `[role="article"]` count delta inside the post.
- Exact-post verification (`groups posts get`) additionally returns `render-timeout-likely-success` with signal `composer-cleared-but-no-other-evidence` when the composer cleared but the comment sits outside the extracted window — NEVER retry that outcome either; a retry creates a real duplicate (2026-08-22: four retries produced five identical comments on one post).

A non-zero exit ONLY happens when all three verification signals fail (true submit failure). Never retry on `render-timeout-likely-success` — duplicate comments are worse than missed verification. Facebook also collapses identical duplicate comments server-side: retrying the exact same text after an ambiguous result may leave ONE comment, not several (observed live 2026-08-22), but never rely on that — the retry discipline above is the contract.

Facebook strips Markdown (`**bold**`, `[label](url)`) when rendering comments — never use raw substring matching against submitted text to verify a comment landed.

`groups posts get` merges the Relay payload window with the rendered-DOM comment tree (which expands "View more replies" controls), so `hasCommented`-style checks see the complete visible thread. If rendered extraction fails, it falls back to the Relay window only and logs a warning naming the gap.
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

A plain `marketplace list` row carries `primary_image_url` instead — Facebook's own tile photo from the search payload, a square-cropped CDN render of the first gallery photo. It is a separate field because it is ONE cropped image, not the gallery; reporting it in `image_urls` would claim the listing has exactly one photo. It is `null` on `get` (the detail page's listing node has no `primary_listing_photo`; `get` reads the real gallery instead) and `null` for a tile Facebook never described.
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

<principle name="Marketplace Nationwide Search, Location Slugs, Radius, and Depth">
`marketplace list --delivery-method` is the ONLY nationwide lever. It maps to Facebook's own `deliveryMethod` search parameter and REQUIRES `--query`.

| `--delivery-method` | Facebook `deliveryMethod` | Result |
|---------------------|---------------------------|--------|
| `all` (default) | *(no parameter)* | Facebook's unfiltered default — today's behavior, unchanged |
| `shipping` | `shipping` | **Nationwide** — only listings that ship |
| `local` | `local_pick_up` | Listings offering local pickup |

- **`shipping` ignores `--location`.** Facebook serves ONE nationwide shipping pool from any city slug: `evansville` and `seattle` returned the same 30/30 item ids (live 2026-08-18), with sellers across the country. Never run the same shipping search under several slugs expecting different inventory — it is the same rows. The slug is still validated, because an unrecognized slug is a caller mistake either way.
- **`local` means "offers local pickup", NOT "local only".** A listing can carry both; 1 of 30 rows in a live `local` run also carried `SHIPPING_ONSITE`. Use `delivery_types` for the per-listing answer.
- **`--delivery-method` without `--query` is rejected.** The browse feed ("Today's picks") has no delivery-method filter at all — live, `shipping` and `local_pick_up` returned the SAME 18 rows there, including Chicago IL, Tyler TX, Valdosta GA, and Woodstown NJ rows under `local_pick_up`. The parameter perturbs that feed without filtering it, so the CLI refuses instead of sending it.
- **An unrecognized `--location` slug FAILS with a non-zero exit** and names the slug. Facebook never errors on an unknown slug: it rewrites the URL to its slugless surface (`/marketplace/losangeles/search/` → `/marketplace/category/search/`; `/marketplace/losangeles/` → `/marketplace/`) and serves the LOGGED-IN ACCOUNT'S OWN home-city inventory. See Known Issue #8. Valid slugs verified live: `evansville`, `chicago`, `seattle`, `nyc`.
- **Depth ceiling: 2,448 unique listings per search.** Measured live 2026-08-18 with `--limit 5000` on three different searches — `"lego bulk"`+shipping (92 scrolls), `"lego"`+shipping (92 scrolls), `"lego"` in `chicago` with no fulfillment filter (80 scrolls) — every run stopped at exactly 2,448, in ~3 minutes each. That is Facebook's own pagination exhaustion, not a CLI limit. A `--limit` above 2,448 returns 2,448. To reach more inventory, vary the QUERY, not the limit.
- **There is no `--radius`, on purpose.** Facebook's `radius` URL parameter does NOT widen a search. Live 2026-08-18, `radius=1` and `radius=99999` returned byte-identical 100-row result sets to a search with no `radius` at all (100/100 identical item ids, same four locations), on both the city-slug surface and the `latitude`/`longitude` surface. It only changes the rendered "Within N mi" label, and its unit is KILOMETERS, not miles (`radius=500` → "Within 311 mi", `radius=161` → "Within 100 mi"). The effective radius comes from the account's saved Marketplace location preference, not from the URL. Never suggest `radius` as a way to search wider or nationwide; use `--delivery-method shipping`.
</principle>

<principle name="Marketplace One Listing, Two IDs">
Facebook identifies one listing by TWO ids and links to it by either: a LISTING id and a STORY/POST id. A search tile links by the listing id. Facebook's injected "commerce_interesting_product" notification tile links by the post id.

The listing's own payload node is always keyed by the LISTING id and publishes the post id in its own `story.post_id` and `product_item.id` fields. The CLI indexes that mapping, so `marketplace get <either id>` resolves.

`item_id` in the output is the id that was requested, NOT a canonical one. Two records for the same listing under its two ids are the same listing. Never treat them as two listings.
</principle>

<principle name="Marketplace Availability">
`availability` reports `Sold`, `Pending`, `Available`, or `null` on BOTH `marketplace list` and `marketplace get`. It is mapped from Facebook's own `is_sold` / `is_pending` / `is_live` booleans, which ride in the same listing node as `delivery_types`. These commands do not read rendered availability text.

`null` means UNKNOWN — Facebook did not describe that listing on the surface that was read. It NEVER means "still for sale".

A consumer that checks many visible search results should use one `marketplace list` call.

Use `facebook marketplace status ITEM_ID` for a direct, uncached availability check.

This command does not require prices, descriptions, images, or `delivery_types`.

Its output has `item_id`, `status`, `availability`, `status_source`, and `url`.

`Available` and `Pending` map to `status: "available"`. `Sold` maps to `status: "gone"`.

Facebook can redirect a removed listing to a Marketplace page with `unavailable_product=1`.

The status command also requires the exact unavailable banner before it returns `status: "gone"`.

The command fails when those two signals conflict. It never infers status from absent listing data.
</principle>

<principle name="Marketplace Seller">
Every Marketplace record carries `seller_id` and `seller_name` on BOTH `marketplace list` and `marketplace get`, read from Facebook's own `marketplace_listing_seller` payload node — not from the rendered "Seller information" heading.

`seller_id` is Facebook's numeric profile id (the stable key); `seller_name` is the display name (a person can change it). Both `null` means Facebook's payload named no seller for this listing — for example, a listing posted into a Facebook Group rather than to a seller's personal profile. Unlike `delivery_types`, an absent seller is NOT fatal and does not raise: an absent seller cannot be misread as a different seller the way an absent fulfillment model could be misread as "no shipping offered".

Never derive seller identity by parsing a `/marketplace/profile/<seller_id>/?product_id=<item_id>` link out of the rendered page — the CLI already reads it structurally and correctly covers the group-listing case where no such link exists at all.
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

**Superseded in part by Known Issue #7 (2026-08-04):** the `marketplace get` recovery path named above was broken for exactly those notification-tile IDs, because the capture was keyed by one of Facebook's two listing IDs and the notification tile links by the other. #7 restores it.

### 7. `marketplace get` on a notification-tile ID failed on a page that fully described the listing

**Symptom (2026-08-04):** `facebook marketplace list --query "lego" --location evansville --sort newest --limit 100` warned `Facebook described no delivery_types for 2 of 100 listing(s) ... IDs: ['28800686242866906', '37076565001958568']`, and Known Issue #6's documented recovery path then failed on both:

```
Error: Facebook did not describe the fulfillment options for listing 28800686242866906: no delivery_types were found in the page's listing data. ... (listings described on this page: 21)
```

Exit 1 both times, on a healthy authenticated session. Both rows also returned `location: null` and no description on `list`. Because the consumer is forbidden from guessing fulfillment, both listings were dropped — and both were real bulk LEGO lots ("Lego Lot" $100, "Large lot of misc lego/building blocks/max blocks" $50), the two most valuable candidates in that window.

**Cause:** ONE LISTING, TWO IDS. Facebook identifies a listing by a LISTING id and by a STORY/POST id, and links to it by either. The detail page WAS describing the listing in full — under its other id. Captured live from `/marketplace/item/28800686242866906/`:

```json
{"__typename":"GroupCommerceProductItem","id":"1533173811265557",
 "delivery_types":["IN_PERSON","PUBLIC_MEETUP"],
 "location_text":{"text":"Evansville, IN"},
 "story":{"post_id":"28800686242866906", ...},
 "product_item":{"id":"28800686242866906", ...},
 "is_sold":false,"is_pending":false,"is_live":true}
```

The capture map is keyed by `node.id` (the listing id `1533173811265557`), so a lookup by the URL id `28800686242866906` missed and the fail-loud guard fired. The error message ("Facebook changed its Marketplace payload") was misleading: Facebook had changed nothing, and the "21 listings described" it reported were the 20 recommended listings plus the target itself.

Which id a surface uses is not arbitrary. A normal search tile links by the listing id (`get 26999388286428618` was a direct hit and always worked). The injected "commerce_interesting_product" notification tile links by the post id, which is why only those two rows failed. Both failing tiles carried `?ref=notif&notif_t=commerce_interesting_product` in the href.

**Fix (`facebook/facebook_cli/client.py`, `facebook/facebook_cli/models.py`):**
- `INSTALL_DELIVERY_CAPTURE_JS` now also records `capture.aliases`, mapping each listing's `story.post_id` and `product_item.id` to the id its node is keyed by. Two listings claiming the same alias are recorded in `aliasConflicts` and raise, matching the existing `delivery_types` conflict handling.
- `_resolve_captured_listing_id` resolves a requested id: direct hit first, then the alias index. `_extract_listing_fulfillment` and the `list` attachment both use it.
- The same capture now records Facebook's `is_sold`/`is_pending`/`is_live` booleans and `primary_listing_photo`, so `list` reports `availability` and `primary_image_url`.
- `_derive_availability` takes those booleans on BOTH surfaces. The detail-page text markers it used before (`"no longer available"`, `"sale pending"`) were never validated against a real sold listing and were removed with the DOM signals that fed them.

**Verification:** `get 28800686242866906` → `delivery_types: ["IN_PERSON","PUBLIC_MEETUP"]`, `location: "Evansville, IN"`, `availability: "Available"`, `original_price: 250.0`, 7 gallery URLs. `get 37076565001958568` → `["IN_PERSON","PUBLIC_MEETUP"]`, `"Utica, KY"`. The exact failing `list` command exited 0 with 98 of 100 rows carrying `delivery_types`, `availability`, and `primary_image_url`. Regression coverage in `facebook/tests/test_marketplace_delivery_types.py` against a verbatim live fixture (`tests/fixtures/marketplace_item_delivery_post_id_alias.html`, the real script element from listing 28800686242866906's page). Full suite: `114 passed`.

**Honest limit (unchanged and confirmed live):** `marketplace list` STILL reports `null` for those same two notification tiles, and that is correct. Their ids appear nowhere in the search page's payloads — not in any `script[type="application/json"]` blob, not in any of the 15 captured XHR bodies, and not under the canonical listing id either. Facebook serves the notification tile's listing data from the notifications feed, which the search page never loads. So the `list` surface genuinely cannot describe them, the warning names them by id, and `marketplace get` is now once again the definitive read. Do NOT try to fill those rows by guessing.

**Recurrence Prevention:** Never assume the id in a Marketplace URL or tile href is the id Facebook's own payload is keyed by. When a lookup misses on a page that clearly rendered the listing, dump the node and compare its `id` against `story.post_id` and `product_item.id` BEFORE concluding Facebook changed its payload. The fail-loud guard did its job here — it refused to report an unknown fulfillment model — but its error text blamed Facebook for a keying bug in the CLI, so a "Facebook changed its payload" message is a hypothesis to test against the live page, never a conclusion.

### 8. `marketplace list --location <unknown-slug>` returned another city's inventory under exit 0

**Symptom (2026-08-18):** `facebook marketplace list --query "lego bulk" --location losangeles --sort newest --limit 40` exited 0 and returned 40 healthy-looking rows whose locations were `Evansville, IN` (31), `Newburgh, IN` (5), and `Henderson, KY` (3) — a 100% overlap with an `--location evansville` run. Nothing in the output said Los Angeles had not been searched. Valid slugs behaved correctly and are the control: `chicago` → Chicago/Elmwood Park/Oak Park, `seattle` → Seattle/Redmond/Bellevue, `nyc` → Leonia NJ/New York.

**Cause:** Facebook does not error on an unknown Marketplace location slug. It silently drops the slug and serves the LOGGED-IN ACCOUNT'S OWN home city (Evansville, IN for this profile). Captured live from the page's own `location.href` after settle:

```
requested /marketplace/losangeles/search/?query=lego%20bulk&sortBy=creation_time_descend
served    /marketplace/category/search/?query=lego%20bulk&sortBy=creation_time_descend
requested /marketplace/zzzzznotaplace/search/?...   ->  served /marketplace/category/search/?...
requested /marketplace/losangeles/                  ->  served /marketplace/
```

Facebook's own filter button on both rejected pages still read `Location: Evansville, Indiana, Within 11 mi`, while `chicago` / `seattle` / `nyc` each kept their slug in the served URL and rendered their own city in that button. The CLI never compared the requested slug against the served one, so the substitution was invisible: a full result set, a clean exit, and the wrong city. That is worse than an empty result, because a downstream consumer cannot detect it.

**Fix (`facebook/facebook_cli/client.py`):** `_served_location_slug` reads the location segment out of the URL Facebook actually served, and `_assert_requested_location` raises `ClientError` naming the slug and both URLs unless the served segment equals the requested one. `_paginated_fetch` now takes the requested `location` and runs that assertion after `_wait_for_marketplace_results` (the slug rewrite happens during Facebook's client-side routing, so it must be read after the page settles) and BEFORE the zero-result early return, so a rejected slug can never be reported as "this city has no matches" either. The literal slugless segment `category` is rejected as a requested location too, since `--location category` would otherwise satisfy a naive equality check while returning exactly the home-city inventory this guard exists to catch. No fallback, no warning-and-continue: the command exits non-zero.

**Verification:** The exact failing command now exits 1 with `Error: Facebook does not recognize the Marketplace location slug 'losangeles'. It served https://www.facebook.com/marketplace/category/search/?... instead of the requested https://www.facebook.com/marketplace/losangeles/search/?...`. All four valid controls still exit 0 and return their own city: `evansville` (11 Evansville + 1 Henderson KY), `chicago` (Chicago/Elmwood Park/Evanston/Morton Grove/Riverside IL), `seattle` (Seattle/Redmond/Bellevue WA), `nyc` (Astoria/Brooklyn/Flushing NY + Bloomfield/Leonia NJ). Regression coverage in `facebook/tests/test_marketplace_delivery_and_location.py` against verbatim live URL captures in `facebook/tests/fixtures/marketplace_location_slugs.json`, including a `_paginated_fetch` test proving the guard fires before extraction and is not masked by the zero-result path. Full suite: `337 passed`.

**Recurrence Prevention:** Never trust that Facebook searched what the CLI asked for. Facebook's Marketplace surfaces answer an unrecognized identifier by substituting a default rather than failing, so any new location-, category-, or filter-bearing URL must be re-read from the served page and compared against the request. `--delivery-method shipping` is exempt from caring about the slug (Facebook serves one nationwide pool from any city), but it is NOT exempt from the check, because an unknown slug still means the caller believes something false.

## Raw Browser Fallback Notes

The `facebook` CLI extracts Marketplace data structurally, from Facebook's own embedded GraphQL/Relay payloads (see the principles above and Known Issues #3–#7) — not from rendered DOM text. That is more reliable than DOM scraping and is always the first choice; load this skill and use the CLI before ever touching a raw browser tool. The notes below were captured 2026-08-14 during a one-off LegoScout sourcing exercise that deliberately used Claude's raw browser-pane tools (`navigate`, `read_page`, `get_page_text`, `javascript_tool`, screenshots) instead of this CLI, to test a browser-pane-only workflow. Keep them for two cases only: (1) a genuine CLI-unavailable fallback, and (2) extending the CLI's own scraper. Where a note duplicates existing CLI behavior, it says so instead of repeating the derivation.

### Already covered by the CLI — do not re-derive

- **Gallery photo scoping.** The CLI's `img[alt^="Product photo of"]` DOM scope (Known Issue #4) is the same technique a raw browser session needs: `document.querySelectorAll('img')` alone returns dozens of unrelated images (the "Today's picks" sidebar reuses thumbnails across every page), and filtering by image size/width is not reliable — sidebar thumbnails can also be large. Use the alt-prefix filter in either context; it is the only filter that worked cleanly.
- **Sort order.** `--sort newest` already maps to Facebook's `sortBy=creation_time_descend` URL parameter. A raw browser session has to build that URL param itself, because Facebook's on-page "Sort by" radio control (Suggested / Distance / Date listed: Newest first / Price low / Price high) does not always render in the left filter panel on a plain query search. The separate "Date listed" radio group (All / Last 24 hours / Last 7 days / Last 30 days) is a time-window filter, not a sort order — don't confuse the two or assume the sort radio is always in the DOM.
- **Reduced-price rendering.** `$15$20` (no separator) is a current-then-struck-through-original render; the CLI already splits it correctly into `price`/`original_price` (Known Issue #3, "Marketplace Prices" principle). Never read the second, struck-through number as the current price, on either surface.
- **Fulfillment/delivery.** `delivery_types` is read structurally and is authoritative (Known Issue #6, #7). Rendered delivery text (`"Door pickup"`, `"Public meetup"`, `"Door pickup or dropoff"`, `"Ships for $X.XX"`) is incomplete — several confirmed pickup-only listings render no tag at all — so a raw browser session that only reads visible text will systematically under- or mis-report fulfillment. A `"Ships for $X.XX"` tag pairs with a real Facebook Shop checkout flow (a "Shipping & returns" panel, an "Estimated arrival" date range, and a "Buy now" button with "Covered by Purchase Protection"), while `"Open to shipping, please provide the zip code"` in the listing body is only a soft/negotiable seller signal, not a firm quote — don't treat the two the same.
- **Seller identity.** `seller_id`/`seller_name` are read structurally from Facebook's own `marketplace_listing_seller` payload node (see the "Marketplace Seller" principle above), including the group-posted case where no profile link exists and seller_id is genuinely unrecoverable. Don't parse the rendered `/marketplace/profile/<seller_id>/?product_id=<item_id>` link — the CLI's structural read already covers what that link would give you, and correctly returns `null` where the link doesn't exist.

### New: Facebook Shop-style listings can bundle multiple priced items under one item_id

A listing's body text can describe several separately-priced items in one post (e.g. 10 sealed sets, each its own `"<set> - $<price>"` line, some marked `*SOLD*`), while the page's own header price, delivery/shipping quote, and (for a Shop-style listing) "Buy now" button all describe only ONE of those items — the one keyed by the `item_id` in the URL, never "the lot". This holds whether the listing is read via the CLI or raw browser tools: `marketplace get <item_id>` returns the single sellable item that id names, not the multi-item description. When a listing body lists several priced items, do not assume the record's `price` field applies to all of them — confirm which single item the id/price actually corresponds to before pricing the listing.

### Raw-browser-only technique notes (no CLI equivalent needed)

These apply only when actually falling back to the Claude browser pane / computer-use tools, because the CLI does not use them at all:

- **Photo carousel arrow clicks are unreliable.** Clicking a listing's "View next image" control frequently does not advance the visible image in a follow-up screenshot (looked like a stale-render/lag issue), even though the click registers. Don't enumerate a gallery by clicking through it — use the `img[alt^="Product photo of"]` JS query above instead; it returns every gallery image URL in one call, with zero clicking.
- **Bulk item-ID/price/location harvesting.** `read_page` (not screenshots) on a search-results page, or on any listing page's own "Today's picks" sidebar, exposes each listing link's accessible name as `"<Title>, $<price>, <location>, listing <item_id>"` — title, price, location, and item_id in one shot, without visiting each listing individually.
- **`get_page_text` covers almost all per-listing capture.** One `get_page_text` call on an item page reliably returns title, price (with struck-through original if reduced), condition, brand, the seller's full free-text description, item location, the delivery-method tag if one is rendered, and the seller's display name — plus, as a side effect, that listing's own "Today's picks" sidebar. Reserve screenshots/zoom for genuinely visual tasks: reading a set number off box art, assessing a bulk lot's visual composition, or comparing a listing photo against a BrickLink catalog image. Defaulting to screenshots for routine data capture is slower and hits more rendering/timing bugs (see the carousel and scroll notes here).
- **Infinite-scroll pagination is flaky under `computer scroll`.** Triggering more results by scrolling the results grid sometimes produced a "Browser pane is currently hidden" timeout and could silently fail to load additional listings. Prefer navigating directly to a search URL with query params (`https://www.facebook.com/marketplace/<location-id>/search/?query=lego&sortBy=creation_time_descend`) and treating each navigation as its own result page, over chaining scrolls.
