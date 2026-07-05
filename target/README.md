# Target CLI

## DESCRIPTION

A command-line interface for Target. Reads (product search, detail, and store
inventory) run over Target's internal JSON API (redsky) for sub-second responses;
cart and checkout run through a logged-in browser session. Use this CLI for fast,
repeatable Target workflows: search products, check availability, manage the cart,
and place orders.

## Installation

```bash
cd <cli-tools-root>/target
uv tool install -e . --force --refresh
```

Browser automation is driven by `browser-harness` (a transitive dependency of
`cli-tools-shared`); no separate browser install step is required.

After installation, the `target` command is available in your terminal.

## Architecture

Reads and writes use two different paths on purpose:

- **Reads (fast):** `products list`, `products get`, `products inventory`, and
  `store list` call Target's redsky JSON API directly over `httpx` — no browser,
  ~200–600 ms per call.
- **Writes (browser):** `cart` and `checkout` drive a logged-in browser session,
  because they require your Target account.

Redsky's bot layer (PerimeterX) only issues its authorizing cookies
(`_tgt_token` / `_tgt_session`) to a **real, visible browser**, and rejects
headless requests. So `target session refresh` opens a real browser, mints and
captures those cookies, and verifies them with a live search before saving. The
captured session is cached under the active profile and reused for all reads. It
lasts ~24h; when it expires, reads fail loudly and you re-run `target session
refresh`. There is no silent DOM fallback.

`target auth login` is separate: it logs into your Target **account**, which is
only needed for `cart` and `checkout`. For search/browse you only need
`session refresh`.

## Quick Start

```bash
# One-time (and ~daily): capture the fast-search session (opens a browser briefly)
target session refresh

# For cart/checkout only: log into your Target account (opens a browser)
target auth login

# Search (fast, no browser)
target products list "aa batteries" --limit 10 --table

# Product detail + live availability
target products get 88830890
target products inventory 88830890 --table

# Cart + checkout
target cart add 88830890
target cart list --table
target cart checkout            # dry run — reviews the order, places nothing
target cart checkout --yes      # places the real order (spends money)
```

## Commands

### Authentication (`target auth`)

```bash
target auth login            # log into your Target account (for cart/checkout)
target auth login --force    # re-authenticate from scratch
target auth status           # show auth status across profiles
target auth logout           # clear stored credentials/session
target auth profiles list    # manage profiles (list/get/create/select/rename/delete)
```

### Fast-search session (`target session`)

```bash
target session refresh   # re-capture the redsky read session via a headed browser
target session status    # show cached session age / expiry
```

`session refresh` re-mints the read session without a full account re-login. Use
it when reads report the session is expired but you're still logged in.

### Products (`target products`)

```bash
target products list "search terms"                 # search (JSON)
target products list "search terms" --table         # search (table)
target products list "search terms" --limit 10      # cap results (max 96)
target products list "search terms" --store 1481 --zip 47715
target products list "search terms" --filter "price:contains:$4"
target products list "search terms" --properties "id,title,price"

target products get 88830890                         # product detail
target products get 88830890 --table

target products inventory 88830890 --table           # pickup + shipping availability
target products inventory 88830890 --store 1481 --zip 47715
```

`products get` includes `street_date` (a `"YYYY-MM-DD"` release date, or `null`
when the item has none). `products inventory` includes `orderable` (bool): `true`
when shipping or at least one store's pickup is in an orderable status right now.

`products inventory` also surfaces pre-launch ("coming soon") signals, present
only for items that aren't purchasable yet (`null`/absent for a normal in-stock
item):

- **`notify_me_eligible`** (bool or `null`): whether Target offers a "notify me"
  signup for this item.
- **`available_online_date`** / **`available_instore_date`** (ISO datetime string
  or `null`): when the item is scheduled to become orderable online / in stores.
- **`pre_order_quantity`** (number or `null`): the pre-order-to-promise quantity
  signal (the max across stores, when Target has allocated pre-order stock).

### Cart (`target cart`)

```bash
target cart list --table                     # view cart contents
target cart add 88830890                     # add item by TCIN (store pickup by default)
target cart add 88830890 --method shipping   # ...or ship this item instead
target cart remove 88830890                  # remove item by TCIN
target cart clear                            # remove every item in the cart (asks to confirm)
target cart clear --yes                      # skip confirmation
target cart checkout                         # DRY RUN — reviews order, places nothing
target cart checkout --yes                   # places the real order (spends money)
```

Each `cart list` item includes `tcin`, alongside its existing `title`/`price`,
so a line item can be fed straight into `cart remove <tcin>` or `products get
<tcin>` without hand-copying an id from the title. `cart clear` empties the
cart by listing its current items and removing each one (the same removal
`cart remove` uses); an already-empty cart is a no-op ("0 item(s) removed").

### Payment methods (`target payment-method`)

Name the cards already in your Target wallet so `cart checkout --card <name>`
can select one. The CLI stores only a **pointer** (name + last4 + brand), never
the card number — you enter that into Target's own wallet page. A CVV may be
stored (opt-in) so checkout is one-shot; `list`/`get` only report `cvv_stored`,
never the CVV itself.

```bash
target payment-method add --name amex-personal      # opens Target's add-card page; captures a pointer
target payment-method add --name debit --last4 5636  # point at a card already in your wallet, by last4
target payment-method list --table                   # saved pointers (cross-checked against the live wallet)
target payment-method get amex-personal              # one pointer by name...
target payment-method get 5636 --table               # ...or by the card's last 4 digits
target payment-method set-default amex-personal      # default used when checkout gets no --card
target payment-method set-cvv amex-personal          # store a CVV (hidden prompt) for one-shot checkout
target payment-method remove amex-personal           # delete the pointer (leaves the Target wallet untouched)
```

The stored CVV (if any) lets checkout confirm a debit/gift card without an
interactive prompt; when no CVV is stored and Target asks for one, checkout
prompts securely for it at that moment and never saves it.

### Orders (`target orders`)

```bash
target orders list --table                # recent orders (find an order number)
target orders get 123456789               # one order's status + total
target orders get 123456789 --table
target orders cancel 123456789            # cancel all items (while still cancellable)
target orders cancel 123456789 --cancel-reason "Ordered wrong item" --yes
```

`orders list`/`get` read your purchase history (needs a logged-in account
session); `cancel` only works while an order is still cancellable (processing,
not yet picked up or shipped).

### Stores (`target store`)

```bash
target store list 47710 --table   # Target stores near a zip code
```

### Favorites (`target favorites`)

```bash
target favorites list             # items you saved with the heart (JSON)
target favorites list --table     # human-readable table
target favorites list --limit 10  # cap results
target favorites list --filter "available:eq:True"   # only in-stock favorites
target favorites list --properties "id,title,price"  # restrict fields

target favorites get 94962117            # look up one saved favorite by TCIN
target favorites get 94962117 --table    # errors if the TCIN isn't a favorite

target favorites remove 78790319         # un-favorite an item by TCIN
```

`favorites list` reads your saved favorites (the heart) from your Target account,
so it needs a logged-in account session (`target auth login`) just like `cart` and
`orders`. Target stores favorites as product IDs only, so each item's title and
price are enriched from the fast-search API, and a real fulfillment (pickup +
shipping) read determines whether it's actually purchasable right now.

Each favorite carries:

- **`available`** (bool): `true` only when the item is purchasable NOW (some
  fulfillment channel -- shipping or an in-store pickup -- is orderable). This is
  NOT "the listing exists"; a live, in-stock-soon listing that can't be ordered
  yet is `available: false`.
- **`street_date`** (string or `null`): the item's release date (`"YYYY-MM-DD"`)
  when Target has one on file, e.g. for a not-yet-launched collection; `null`
  when the item has no release date.
- **`status`** (string): one of
  - `"available"` -- purchasable now
  - `"coming_soon"` -- not purchasable yet, but has a future `street_date`
    (a pre-launch item, like a collection that drops in stores next week)
  - `"out_of_stock"` -- not purchasable and has no future `street_date`
  - `"delisted"` -- Target no longer has this product at all (title/price are
    `null`)
- **`notify_me_eligible`** (bool or `null`): whether Target offers a "notify me"
  signup for this item; `null` for a delisted favorite.
- **`available_online_date`** / **`available_instore_date`** (ISO datetime string
  or `null`): when a `coming_soon` favorite is scheduled to become orderable
  online / in stores -- so a pre-launch favorite shows WHEN it drops, not just
  its `street_date`. `null` for an available/out-of-stock/delisted favorite.

`favorites remove <tcin>` un-favorites an item: it looks up the TCIN in your
favorites, resolves it to the item's membership id, and deletes it (errors if the
TCIN isn't one of your favorites). This is handy for clearing out delisted
favorites that show `status: "delisted"`.

Example output (a real pre-launch favorite -- a collection street-dated for the
next day):

```json
[
  {
    "id": "94962117",
    "title": "LoveShackFancy x Target - Yoobi Ribbon Rosa Quilted Tote Bag Sterling Dusk",
    "price": "$34.99",
    "available": false,
    "street_date": "2026-07-05",
    "status": "coming_soon",
    "added": "2026-07-03T21:10:14Z",
    "note": null,
    "brand": "LoveShackFancy x Target",
    "url": "https://www.target.com/p/loveshackfancy-x-target-yoobi-ribbon-rosa-quilted-tote-bag-sterling-dusk/-/A-94962117",
    "rating": 0.0,
    "notify_me_eligible": true,
    "available_online_date": "2026-07-05T10:00:00.000Z",
    "available_instore_date": "2026-07-05T10:00:00.000Z"
  }
]
```

### Cache (`target cache`)

```bash
target cache clear                # clear cached read responses
target --no-cache products list "test"   # bypass the cache for one call
```

## Purchase Safety

`cart checkout` never spends money unless you pass `--yes`. Without it, the
command drives to the Place Order screen, prints the order summary (items,
subtotal, total), and stops. Add `--yes` to actually click Place Order and
capture the order confirmation.

## Output Formats

- JSON is the default. Add `--table` / `-t` for human-readable tables.

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display data as a table |
| `--limit` | `-l` | Maximum number of results |
| `--filter` | `-f` | Filter results using `field:op:value` syntax |
| `--properties` | `-p` | Restrict output to selected fields |
| `--store` |  | Override the store id for pricing/inventory |
| `--zip` |  | Override the zip for geo context |
| `--yes` | `-y` | Place the real order at checkout (spends money) |
| `--version` | `-v` | Show version and exit |
| `--no-cache` |  | Bypass cached read responses for this execution |

## Configuration

Non-authentication configuration lives in
`~/.local/share/cli-tools/target/.env`. The captured redsky session and browser
data are runtime auth state under the active profile
(`~/.local/share/cli-tools/target/authentication_profiles/<profile>/`). The
source repo only carries `.env.example`.

Root config variables:

```bash
# Default store / geo context for reads (overridable per-command with --store/--zip)
STORE_ID=108
ZIP=47710

# Browser: true = headless (default). Reads never launch a browser; this affects
# cart/checkout. The redsky prime always forces a visible browser regardless.
HEADLESS=true

# Response cache
CACHE_ENABLED=true
CACHE_TTL=3600
```

Reusable credentials must go through the CLI-tools secret manager, never a `.env`
file. `.env` holds only non-secret config and CLI-managed runtime state.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error (includes an expired/missing redsky session) |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Requirements

- Python 3.11+
- Dependencies (installed automatically): typer, python-dotenv, httpx,
  cli-tools-shared (which pulls in browser-harness).

## License

MIT
