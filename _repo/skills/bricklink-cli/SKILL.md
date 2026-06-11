---
name: bricklink-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute bricklink operations using the `bricklink` CLI tool.
  CLI interface for Bricklink API -- manage orders, inventory, catalog, messages, refunds, invoices, coupons, and members.
  Triggers: bricklink, bricklink cli, bricklink orders, bricklink inventory, bricklink catalog, bricklink messages, bricklink parts, LEGO parts, bricklink store, bricklink price guide
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

**Before ANY auth/credential error, read `<authentication>` below.** A `bricklink` auth blocker is yours to remediate — never stop and ask the user how to authenticate, which credential type to use, or for credentials.
</quick_start>

<authentication>
**Authentication & blocker self-remediation — MANDATORY.**

On ANY `bricklink` auth or credential error (e.g. `Authentication required. Missing credentials: oauth: missing CLIENT_ID, CLIENT_SECRET, ACCESS_TOKEN, REFRESH_TOKEN`, or a browser-session expiry), you MUST remediate it yourself. NEVER call AskUserQuestion to ask the user how to authenticate, which credential type to use, whether to run `auth login`, or to supply credentials. Asking the user to log in or paste credentials is a rule violation (Global Blocker Ownership + browser-password policy). The only allowed user touchpoints are documented at the end of this section.

**Step 1 — diagnose which credential type is missing. Never guess.**
```bash
bricklink auth status            # read-only; per-profile, per-credential-type truth
```
`bricklink` has TWO independent credential types (`bricklink auth status` reports both under `credential_types`):

| Credential type | Gates these commands | How `auth login` configures it | Autonomous remediation path |
|---|---|---|---|
| `oauth` (OAuth 1.0a) | `inventory *`, `order *`, `catalog *`, `member *`, `coupon *` — i.e. all `api.bricklink.com` REST commands | `bricklink auth login -c oauth` prompts for 4 static long-lived fields (CLIENT_ID/SECRET = consumer key/secret, ACCESS_TOKEN/REFRESH_TOKEN = token value/secret). NO browser. NO `auth refresh` (tokens never expire). | See "OAuth remediation" below. There is **no browser fallback** for these commands. |
| `browser_session` | `messages *`, `refund *`, `notification *`, `order search` — i.e. all browser-scraped commands | `bricklink auth login -c browser_session` opens a **headed** Chrome at `bricklink.com/v2/login.page` and blocks until login completes. | See "Browser-session remediation" below. |

`order` spans both: `order list/get/items/file/ship/update-status` are `oauth`; only `order search` is `browser_session`.

**Critical:** match the failing command to its credential type. `inventory get/delete` are `oauth`-gated. A `browser_session` that is already authenticated does NOT satisfy them, and driving the LEGO.com browser login does NOT fix an `oauth` error.

**OAuth remediation (for `inventory`/`order`/`catalog`/`member`/`coupon` auth errors):**
1. OAuth 1.0a consumer/token credentials are user-issued secrets from BrickLink (Account > API > Access Tokens). They cannot be machine-generated and there is no refresh flow. They live in the CLI-tools secret manager (Keychain-backed; profile `.env` holds `secret://…` placeholders, never raw values), so they may already exist on this machine.
2. Probe the secret manager BEFORE concluding the credentials are unavailable. The canonical helper and names are verified — do not guess:
   ```bash
   SM=/Users/adam/Dropbox/GitRepos/cli-tools/_repo/_secret-manager/secrets.sh
   "$SM" list | grep -i bricklink     # names only, never prints values
   "$SM" has bricklink-legacy-client-secret
   "$SM" has bricklink-legacy-access-token
   "$SM" has bricklink-legacy-refresh-token
   ```
   Load the `cli-tool-secrets` skill (via the Skill tool) for the full command surface and naming schema. Retrieve values with `"$SM" get <name>` and pipe them straight into the consumer — never echo a secret, never write OAuth creds into any `.env` directly.
3. Map secret-manager names to the 4 OAuth fields: `CLIENT_ID` = consumer key, `CLIENT_SECRET` = `bricklink-legacy-client-secret`, `ACCESS_TOKEN` = `bricklink-legacy-access-token`, `REFRESH_TOKEN` = `bricklink-legacy-refresh-token`. If the profile is not wired to existing secrets, run `bricklink auth login -c oauth` to configure it.
4. Escalate to the user ONLY for an OAuth field that exists nowhere on the machine (a missing field is genuinely unavailable under Global Blocker Ownership). Tell the user the exact field name needed and that BrickLink issues it at Account > API > Access Tokens. Do NOT ask the user to "run auth login" or to re-supply credentials that the secret manager already holds.

**Browser-session remediation (for `messages`/`refund`/`notification`/`order search` auth errors):**
1. Re-establish the session yourself: `bricklink auth login -c browser_session`. This opens a headed Chrome at the BrickLink/LEGO login.
2. **The shared browser-auth flow is human-in-the-loop**: `PlaywrightBrowserAutomation.authenticate()` opens the page, prints "Log in, then press Enter…", and blocks on stdin (`/dev/tty`) until login is completed. It does NOT itself type the email/password. To authenticate autonomously, drive the LEGO.com login form with the `playwright-cli` binary and retrieve the LEGO/BrickLink password from the `lastpass` CLI (lastpass holds a `bricklink.com` and a `lego.com` entry; the ad-hoc browser-login password comes from lastpass — NOT from the CLI-tools secret manager, which owns only the OAuth API creds). Per the browser-password policy, never ask the user for the password and never use browser-stored credentials. Then return to the blocked `auth login` and confirm completion.
3. Verify: `bricklink auth status` must report `browser_session.authenticated: true` for the active profile.

**The only allowed user touchpoints:** (a) BrickLink OAuth 1.0a secrets that do not exist anywhere on this machine (issued by BrickLink, outside automation), or (b) a hard CAPTCHA/2FA wall that blocks the browser login after a genuine automated attempt. In every other case, authenticate yourself. Run `bricklink auth status`, `bricklink auth login --help`, and the relevant `--help` before acting — never guess flags.
</authentication>

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

**Fix:** `bricklink_cli/browser_runtime.py::_get_page_for` now (a) calls `_detect_waf_challenge(page)` after navigation, (b) reloads the URL up to 4 times (with a small backoff) until the challenge clears, and (c) raises a descriptive `RuntimeError` if it persists. `_fill_and_send_message` also bumps the textarea wait to 20s and re-checks for WAF on timeout, so unrecognized blockers surface a real error instead of a raw selector timeout. Source: `~/Dropbox/GitRepos/cli-tools/bricklink/bricklink_cli/browser_runtime.py` (the new `_WAF_TITLE_MARKERS`, `_WAF_SELECTORS`, `_detect_waf_challenge`, and updated `_get_page_for` + `_fill_and_send_message`).

**Verification:** Run any browser-backed messages operation (e.g. `bricklink messages send <orderId> "<body>"`). On a fresh session the activity log will show `AWS WAF CAPTCHA detected (attempt 1/4) — reloading <url>` followed by a successful form submission. To verify without sending a real message, drive `BricklinkRuntimeBrowser()._get_page_for("https://www.bricklink.com/contact.asp?orderID=<id>")` and confirm `page.query_selector("textarea")` returns a handle.

**Recurrence Prevention:** WAF detection is applied centrally in `_get_page_for` — every browser-backed BL operation (messages, refunds, invoices, order search, etc.) inherits the retry, so a future flow that calls `_get_page_for` will get the same protection. If BrickLink/AWS rotates the CAPTCHA markup, update `_WAF_TITLE_MARKERS` / `_WAF_SELECTORS` to keep `_detect_waf_challenge` honest. If the challenge starts persisting past 4 reloads in practice, raise `max_waf_retries` rather than reintroducing silent waits.

**General rule:** When a browser automation step waits for a content selector that can be hidden behind an interstitial (WAF, login, consent, captcha), detect the interstitial explicitly before waiting for the content — otherwise a missing-selector timeout will misdiagnose the failure.
