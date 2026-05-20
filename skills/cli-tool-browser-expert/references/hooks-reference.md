# BrowserAutomation Hooks Reference

## Class Constants (Declarative Hooks)

These are the ONLY things a CLI tool's `browser.py` should set:

| Constant | Type | Required | Description |
|----------|------|----------|-------------|
| `SESSION_NAME` | `str` | Yes | Named session for playwright-cli. Must be unique per CLI. |
| `LOGIN_URL` | `str` | Yes | URL to open for interactive headed login |
| `AUTH_CHECK_URL` | `str` | Yes | URL to load in headless mode to verify auth |
| `AUTH_URL_PATTERN` | `str` | Yes | Regex: if current URL matches, user is on login page (not auth'd) |
| `AUTH_SUCCESS_SELECTOR` | `str` | Recommended | CSS selector visible ONLY when authenticated |
| `AUTH_COOKIE_PATTERNS` | `list[str]` | Optional | Cookie name regexes indicating valid session |
| `AUTH_SUCCESS_URL` | `str` | Optional | URL pattern indicating successful auth |
| `AUTH_STORAGE_KEY` | `str` | Optional | localStorage key that must exist when auth'd |
| `LOGIN_TIMEOUT` | `int` | Optional | Seconds to wait for manual login (default: 300) |
| `AUTH_CHECK_TTL` | `int` | Optional | Cache successful auth check N seconds (default: 300) |
| `AUTOMATION_HEADED` | `bool` | Optional | When `True`, `get_page()` runs in headed Chrome instead of headless (default: `False`). Required for sites behind Cloudflare bot detection or Cloudflare Turnstile (e.g. DoorDash) — headless Chrome lands on the `<title>Just a moment...</title>` interstitial and never reaches the real page. |

## Anti-bot detection (verified cases)

Two distinct blocks have been verified against DoorDash. **Always capture a
network log AND an HTML snapshot before applying mitigations.** A "page hangs
on a loading panel" can have an application-layer cause (e.g. server returning
HTTP 400 to an SPA fetch — see the "Deep-link UUID-vs-id gotcha" Known Issue
below) and should not be reflexively attributed to anti-bot blocking.

1. **Headless interstitial** — Page HTML is `<title>Just a moment...</title>`
   with Cloudflare's challenge markup and no real DOM. Cause: headless Chrome
   fingerprint. Mitigation: set `AUTOMATION_HEADED = True` on the CLI's
   `BrowserAutomation` subclass. Verified to work on DoorDash.

2. **Cloudflare Turnstile (managed/invisible mode)** — Page renders
   `[data-testid='turnstile/widget']` etc. and the rest of the SPA is gated
   behind it. Resolution time varies (a few seconds to ~30s in practice).
   Mitigation: poll for the Turnstile selectors to disappear before issuing
   real interactions. Verified to clear on DoorDash within ~10s on both the
   warmup page and the order detail page when the launch is headed.

### Defensive launch hardening (always apply for browser CLIs)

`cli_tools_common/browser/service.py` `browser_open()` already passes the
following on every persistent and non-persistent launch. Treat these as
defensive defaults rather than DoorDash-specific fixes — they have not been
shown necessary on DoorDash specifically (network logs prove DoorDash works
once `AUTOMATION_HEADED` is set and the URL uses a UUID), but they are
inexpensive and prevent classes of detection that DO bite other sites:

- `args=["--disable-blink-features=AutomationControlled",
  "--disable-features=AutomationControlled"]`
- `ignore_default_args=["--enable-automation"]`
- `context.add_init_script("Object.defineProperty(navigator, 'webdriver',
  {get: () => undefined});")` after creating the context.

If a future page hangs on a loading shell, capture a network log first and
look for HTTP 400/403/429 on real fetches before re-tuning these flags.

## Known Issue: DoorDash deep-link UUID-vs-merchant-id gotcha

**Symptom:** After a hard navigation to `https://www.doordash.com/orders/<numeric_id>/`,
the order detail SPA renders `[data-testid='loadingPanel']` and stays there
forever. The Cloudflare Turnstile widgets disappear within seconds (Turnstile
is NOT the blocker), and other GraphQL endpoints (e.g.
`getConsumerOrdersWithDetails`) return 200, so auth/cookies/anti-bot are all
fine. The only failing call is repeated GETs to
`/unified-gateway/marketplace-order-tracking/v1/get-order-status?merchant_order_uuid=<numeric_id>`,
each returning HTTP 400 with body
`{"localized_message":"unknown error","internal_message":"unknown error",...}`.
The SPA polls forever (~2-5s exponential-then-linear backoff) and never gives up.

**Cause:** DoorDash's order-detail SPA reads the URL path segment and passes
it verbatim to the `get-order-status` API as `merchant_order_uuid`. Despite
the parameter name suggesting it accepts the merchant order id, the endpoint
accepts ONLY the canonical order UUID (e.g.
`0c3b80bc-fdf9-4ce8-9b32-5e1fbca9c900`). Numeric merchant ids (e.g.
`3000010020128114`) are rejected with HTTP 400. The page architecture has
no recovery path — it just retries.

**Fix:** Always navigate to `/orders/<order_uuid>/`. Never use the numeric
merchant order id in the URL. In doordash CLI, `client.resolve_order_uuid()`
detects whether the input is already a UUID (regex match), otherwise scans
the order history (up to `REORDER_UUID_RESOLVE_LIMIT`) and returns the
matching order's `order_uuid`. If no UUID can be resolved, it raises
`ClientError` — there is NO fallback to using the numeric id.

**Verification:** After the fix, the network log
(`<debug-dir>/network.jsonl`) should show exactly one
`get-order-status?merchant_order_uuid=<UUID>` call returning HTTP 200. The
order detail SPA renders within a few seconds and the loading panel
disappears. Run:
`doordash orders reorder <ORDER_ID> --dry-run --debug-dir <DIR>` and
`jq -r 'select(.event=="response" and (.url | test("get-order-status"))) | .status' <DIR>/network.jsonl | sort -u` should print only `200`.

**Recurrence Prevention:** `data/reorder_flow.json` declares only one URL
template, `https://www.doordash.com/orders/{order_uuid}/` — no numeric id
fallback. The Python `client.reorder()` method calls
`resolve_order_uuid()` BEFORE touching the browser; if it returns no UUID,
the command fails with `ClientError` before any navigation happens. Any
future regression (e.g., adding `{order_id}` back to the URL templates)
would re-introduce the 400-loop and is forbidden by the Fail-Fast philosophy.

**General rule:** When an SPA hangs on a loading panel, capture a network
log before hypothesizing about anti-bot detection. Application-layer 400s
on data-fetch endpoints look identical to anti-bot blocks from the DOM but
have completely different fixes.

## Domain Knowledge: DoorDash reorder via the `reorderOrder` GraphQL mutation

**Context:** When implementing or maintaining a "reorder a previous order"
feature on DoorDash. Use this in preference to UI-driven Reorder-button
clicks. The mutation is server-side, fast, deterministic, and not subject
to UI/CSS churn or Cloudflare-Turnstile gating.

**Key Facts:**

- **Endpoint:** `POST https://www.doordash.com/graphql/reorderOrder?operation=reorderOrder`
  (DoorDash routes GraphQL by operation name in the path).
- **Operation name** is `reorderOrder` -- NOT `reorderCart`, `createReorderCart`,
  or `consumerReorder` (all of which return GraphQL "Cannot query field"
  validation errors). Introspection is disabled, so the only way to discover
  this is via network capture from a real Reorder button click.
- **Request body shape:**
  ```json
  {
    "operationName": "reorderOrder",
    "variables": {"orderUuid": "<UUID>"},
    "query": "mutation reorderOrder($orderUuid: ID!) { reorderOrder(orderUuid: $orderUuid) { cartUuid isGroup failReason __typename } }"
  }
  ```
- **Argument type is `ID!`** (not `String!`). Wrong scalar -> validation error.
- **Argument is the canonical order UUID**, not the merchant order id. The
  same UUID-vs-id rules from the deep-link Known Issue above apply here.
- **Authentication:** Inherits the standard authenticated browser-cookie session
  (the same cookies used by `getConsumerOrdersWithDetails`). No extra
  `x-csrf-token`, `apollographql-client-name`, or other headers are required;
  the standard JSON-content-type request that already works for read queries
  also works for this mutation.
- **Response shape:**
  `{"data": {"reorderOrder": {"cartUuid": "<UUID>", "isGroup": false, "failReason": null, "__typename": "ReorderOrderResponse"}}}`.
  `failReason` is `null` on success and a server-side message string on failure.
- **Idempotent:** Calling the mutation twice for the same order returns the
  same `cartUuid` (DoorDash deduplicates against an existing in-progress
  reorder cart for that order). Safe to retry.
- **The mutation creates a real cart** in the user's account but does NOT
  place an order. Submission is a separate step (UI Place-Order click on
  `/checkout?orderCartId=<cartUuid>`).
- **Cart contents == original order's line items** (same item ids, same
  modifier/option selections). For a dry-run summary you can derive items
  from the cached original order via `getConsumerOrdersWithDetails`; no
  additional cart-fetch round-trip is required.
- **Cart submission URL:** `https://www.doordash.com/checkout?orderCartId=<cartUuid>`.

**Gotchas:**

- The Reorder UI button lives on `/orders` (the list page), NOT on
  `/orders/<uuid>` (the detail page). The detail page is a receipt view
  with `[data-testid='MerchantActions']` showing only a "Rate store" button
  for delivered orders. Don't waste time hunting Reorder selectors on the
  detail surface.
- `/consumer/orders` returns 404 — that route was removed. Use plain
  `/orders` for the list page.
- The mutation argument is documented in the Apollo error suggestion as
  "Did you mean `createGroupCart`, `createOrderFromCart`, or `createReferral`"
  — none of those is the right operation. Suggestions are misleading; only
  network capture from a real click yields the correct operation name.
- DoorDash's web client polls `getOpenCartsCount` and `listCarts` after
  reorder; those are bookkeeping endpoints, not required for cart creation.
  Only the `reorderOrder` mutation is needed to build the cart.

## Auth Detection Priority

`_check_auth(page)` checks in this order (first match wins):

1. **Cookies** — If `AUTH_COOKIE_PATTERNS` set, checks `cookie_list()` for matching non-expired cookies
2. **Selector** — If `AUTH_SUCCESS_SELECTOR` set, checks if element is visible on page
3. **localStorage** — If `AUTH_STORAGE_KEY` set, checks if key exists with non-empty value
4. **Success URL** — If `AUTH_SUCCESS_URL` set, checks if current URL contains pattern
5. **Not-login-page** — Fallback: if `AUTH_URL_PATTERN` set, returns True if NOT on login page

## Choosing the Right Hook

| Site Behavior | Use This Hook |
|--------------|---------------|
| Login redirects to dashboard with unique element | `AUTH_SUCCESS_SELECTOR` (most reliable) |
| Auth sets a specific cookie (JWT, session token) | `AUTH_COOKIE_PATTERNS` |
| Auth stores token in localStorage | `AUTH_STORAGE_KEY` |
| Login page has distinct URL pattern | `AUTH_URL_PATTERN` (always set as fallback) |
| Auth redirects to specific URL | `AUTH_SUCCESS_URL` |

**Best practice:** Always set `AUTH_SUCCESS_SELECTOR` + `AUTH_URL_PATTERN`. The selector is the primary check; the URL pattern is the fallback.

## Selector Guidelines

**DO:**
- Target elements visible on the main content area (headings, navigation items)
- Use specific selectors: `h2.text-xl`, `nav .user-menu`, `[data-testid="dashboard"]`
- Validate against real page: `playwright-cli page goto <url>` then `playwright-cli page snapshot`

**DON'T:**
- Target elements in collapsible menus/sidebars (may have `offsetParent === null`)
- Target avatar images (often lazy-loaded or hidden on mobile layouts)
- Use overly generic selectors: `div`, `span`, `.container`

## Overridable Methods (Advanced)

These methods CAN be overridden in the BrowserAutomation subclass, but rarely need to be:

| Method | Default Behavior | Override When |
|--------|-----------------|---------------|
| `_check_auth(page)` | Priority-based check using constants | Never — use constants instead |
| `_is_login_page(page)` | Regex match on `page.url` vs `AUTH_URL_PATTERN` | Login detection needs complex logic |
| `_on_authenticated(page)` | No-op | Need to extract tokens/data after login |
| `_get_auth_cookies(cookies)` | Filter by `AUTH_COOKIE_PATTERNS`, skip expired | Cookie detection needs custom logic |

**Rule:** If you're overriding `_check_auth()` or `_is_login_page()`, you're probably doing it wrong. Adjust the class constants instead.
