---
name: "bricklink-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute bricklink operations using the `bricklink` CLI tool. CLI interface for Bricklink API -- manage orders, inventory, catalog, messages, refunds, invoices, coupons, and members. Triggers: bricklink, bricklink cli, bricklink orders, bricklink inventory, bricklink catalog, bricklink messages, bricklink parts, LEGO parts, bricklink store, bricklink price guide"
---

<objective>
Execute bricklink operations using the `bricklink` CLI. All Bricklink interactions should use this CLI.
</objective>

<quick_start>
The `bricklink` CLI follows this pattern:
```bash
bricklink <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List orders | `bricklink order list` |
| Get order details | `bricklink order get <order_id>` |
| List inventory | `bricklink inventory list` |
| Look up a part | `bricklink catalog part <item_no>` |
| Get price guide | `bricklink catalog price <type> <item_no>` |
| Send a message | `bricklink messages send <username> <subject> <body>` |
| Issue a refund | `bricklink refund issue <order_id> <amount>` |
| Check auth | `bricklink auth status` |

`bricklink auth login` opens BrickLink's LEGO account login for browser sessions. Use the LEGO.com account email address and password, not the legacy BrickLink username.

Auth status output uses the shared profile shape: `{"profiles":[{"name":"default","authenticated":true,"credential_types":{...}}]}`. Read `auth profiles[].authenticated` for per-profile status; do not expect a flat top-level `authenticated` field.
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `bricklink` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **order** -- Order management (list, get, items, update-status, ship, file, search)
- **inventory** -- Store inventory (list, get, stats, update, update-qty, create, delete, search, stockroom)
- **catalog** -- Catalog data (get, list, part, set, minifig, price, colors, subsets, supersets)
- **member** -- Member info (ratings, note, set-note, delete-note)
- **coupon** -- Store coupons (list, get, create, delete)
- **messages** -- Messages via browser (list, get, send, reply, mark-read, mark-unread)
- **refund** -- Refunds via browser (info, issue, full)
- **invoice** -- Invoices via browser (get, list, pay)
- **notification** -- Notifications via browser (list, get, send-wanted-list)
- **auth** -- Authentication (login, logout, status, refresh, test)
- **cache** -- Response cache (clear)
- **auth** -- Authentication commands and nested `auth profiles` management
</principle>

<principle name="Item Dimensions">
BrickLink has **two separate dimension systems** for parts:

1. **Stud Dimensions** (`dim_x`/`dim_y`/`dim_z`) -- Modular grid units (studs horizontal, bricks vertical). Returned by the catalog API. Represents a bounding box on the stud grid, NOT actual physical volume. Z can be 0 for parts less than one brick high. Unusually shaped parts may have no stud dims at all.

2. **Packing Dimensions** -- Actual centimeter measurements used by BrickLink Instant Checkout for shipping. Far more accurate for physical volume calculations.

**CRITICAL**: Converting stud dims to cm (1 stud = 0.8cm, 1 brick = 1.05cm) produces a bounding box volume that **massively overestimates** thin, bent, hollow, or irregular parts. For volume-sensitive calculations, prefer packing dimensions or weight-based approaches.

For non-PART item types (sets, minifigs, instructions, books, catalogs, gear), dimensions are already in **centimeters** and represent actual physical measurements.

See `dimensions.md` for full reference with examples and per-item-type details.
</principle>
</essential_principles>


<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions for every command.
**`dimensions.md`** -- BrickLink item dimension systems, units, field definitions, and per-item-type measurement conventions.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>

## Known Issues

### 1. `bricklink messages send` Fails with `wait_for_selector: timed out ... waiting for selector 'textarea'`

**Symptom:** Running `bricklink messages send <orderId> "<body>"` (or `messages reply`, `messages send --member`) intermittently fails with `Error: wait_for_selector: timed out after 10000ms waiting for selector 'textarea' to be visible`. The browser navigates to `https://www.bricklink.com/contact.asp?orderID=<id>` but the page never renders the compose form.

**Cause:** BrickLink is fronted by AWS WAF, which serves an Amazon "Human Verification" CAPTCHA interstitial (`#amzn-captcha-verify-button`, `document.title === "🐴 Human Verification"`) instead of the real page when it flags the request as bot-like (very common in the bricklink CLI's headless Chrome). The CLI was waiting for `textarea` on the WAF page, which has no textarea, so the wait timed out and raised a misleading error. The real BL contact form is one reload away — the WAF challenge sets a token cookie on the first hit and the next navigation passes through to the real page.

**Fix:** `bricklink_cli/browser_runtime.py::_get_page_for` now (a) calls `_detect_waf_challenge(page)` after navigation, (b) reloads the URL up to 4 times (with a small backoff) until the challenge clears, and (c) raises a descriptive `RuntimeError` if it persists. `_fill_and_send_message` also bumps the textarea wait to 20s and re-checks for WAF on timeout, so unrecognized blockers surface a real error instead of a raw selector timeout. Source: `<repo-root>/bricklink/bricklink_cli/browser_runtime.py` (the new `_WAF_TITLE_MARKERS`, `_WAF_SELECTORS`, `_detect_waf_challenge`, and updated `_get_page_for` + `_fill_and_send_message`).

**Verification:** Run any browser-backed messages operation (e.g. `bricklink messages send <orderId> "<body>"`). On a fresh session the activity log will show `AWS WAF CAPTCHA detected (attempt 1/4) — reloading <url>` followed by a successful form submission. To verify without sending a real message, drive `BricklinkRuntimeBrowser()._get_page_for("https://www.bricklink.com/contact.asp?orderID=<id>")` and confirm `page.query_selector("textarea")` returns a handle.

**Recurrence Prevention:** WAF detection is applied centrally in `_get_page_for` — every browser-backed BL operation (messages, refunds, invoices, order search, etc.) inherits the retry, so a future flow that calls `_get_page_for` will get the same protection. If BrickLink/AWS rotates the CAPTCHA markup, update `_WAF_TITLE_MARKERS` / `_WAF_SELECTORS` to keep `_detect_waf_challenge` honest. If the challenge starts persisting past 4 reloads in practice, raise `max_waf_retries` rather than reintroducing silent waits.

**General rule:** When a browser automation step waits for a content selector that can be hidden behind an interstitial (WAF, login, consent, captcha), detect the interstitial explicitly before waiting for the content — otherwise a missing-selector timeout will misdiagnose the failure.
