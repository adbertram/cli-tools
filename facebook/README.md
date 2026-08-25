# Facebook CLI

## DESCRIPTION

The `facebook` CLI wraps playwright with standardized cli-tools behavior.

Use it when you need the underlying command exposed through cli-tools JSON/table conventions for agents, automation, or terminal workflows.

## Prerequisites

This CLI wraps the `playwright` command-line tool. You must install it first:

```bash
# Install playwright CLI
pip install playwright-cli
```

## Installation

```bash
cd facebook
./install.sh
```

After installation, the `facebook` command will be available in your terminal.

## Quick Start

```bash
# Check if browser session is active
facebook auth status

# Login (opens headed browser)
facebook auth login

# Browse marketplace listings
facebook marketplace list

# Search for items
facebook marketplace list --query "LEGO"

# List Messenger conversations
facebook messenger list

# Send a message
facebook messenger send 123456789 --text "Hello!"

# Read posts from a group
facebook groups posts list 123456789
facebook groups posts list 2318028917 --limit 25 --full-threads
```

## How It Works

This CLI is a **wrapper** around the `playwright` command-line tool:

- **Auth commands** manage the playwright browser session (shared across features)
- **Marketplace commands** use playwright to navigate Facebook Marketplace, capture page snapshots, and parse listing data
- **Messenger commands** use playwright to navigate Facebook Messenger, parse conversations and messages, and send messages
- **Groups commands** use playwright to navigate Facebook Groups and extract post data from the feed
- **Configuration** is minimal - stored in `.env`

## Commands

### Auth

Manage browser authentication sessions.

```bash
# Login via headed browser
facebook auth login
facebook auth login --force  # Re-authenticate
facebook auth login --force --profile work  # Uses USERNAME/PASSWORD from that profile

# Check authentication status
facebook auth status
facebook auth status --table

# Test authentication
facebook auth test
facebook auth test --verbose

# Logout (close browser session)
facebook auth logout
facebook auth logout --force  # Skip confirmation
```

`facebook auth login --force --profile <name>` requires `USERNAME` and
`PASSWORD` in that auth profile. The CLI submits those credentials into the
Facebook login form. If Facebook presents a checkpoint, two-step, or captcha
screen, complete it manually in the opened browser; the CLI waits until the
login finishes and the browser session is saved.

### Marketplace

Search and browse Facebook Marketplace listings.

```bash
# Browse "Today's picks" (default location)
facebook marketplace list
facebook marketplace list --location chicago

# Search by keyword
facebook marketplace list --query "LEGO"
facebook marketplace list --query "couch" --min-price 50 --max-price 500

# Sorting (Source-CLI Sort Standard)
facebook marketplace list --query "LEGO"                 # newest first (default)
facebook marketplace list --query "LEGO" --sort newest   # explicit newest first
facebook marketplace list --query "LEGO" --sort price     # price low -> high
facebook marketplace list --query "LEGO" --sort price --desc  # price high -> low

# Fulfillment filter (requires --query)
facebook marketplace list --query "LEGO" --delivery-method shipping  # NATIONWIDE
facebook marketplace list --query "LEGO" --delivery-method local     # local pickup
facebook marketplace list --query "LEGO" --delivery-method all       # default

# Output formatting
facebook marketplace list --table
facebook marketplace list --limit 20
facebook marketplace list --properties title,price
facebook marketplace list --filter "price:gt:100"

# Get specific listing
facebook marketplace get 123456789
facebook marketplace get 123456789 --table
facebook marketplace get 123456789 --properties title,price,location
```

#### Sorting

`marketplace list` follows the Source-CLI Sort Standard via the `--sort`/`-s`
and `--desc`/`-d` options, mapped to Facebook Marketplace's `sortBy` URL
parameter:

| `--sort` | `--desc` | Facebook `sortBy` | Order |
|----------|----------|-------------------|-------|
| `newest` (default) | no | `creation_time_descend` | Most recently listed first |
| `price` | no | `price_ascend` | Price low → high |
| `price` | yes | `price_descend` | Price high → low |

- **Default is `newest`**, so a bare search returns the most recently listed
  items first — what incremental "newest-first" crawlers depend on.
- **Unknown `--sort` values are rejected** with a clear error listing the valid
  values and a non-zero exit code (no silent fallback).
- **Recency-sort exception:** Facebook Marketplace has no oldest-first ordering
  (the sort menu offers only newest-first for date listed), so `--sort newest
  --desc` is rejected with a clear error instead of silently returning arbitrary
  order.

#### Fulfillment: `--delivery-method` (nationwide shipping search)

`marketplace list --delivery-method` maps to Facebook's own `deliveryMethod`
search parameter. It requires `--query`.

| `--delivery-method` | Facebook `deliveryMethod` | Result |
|---------------------|---------------------------|--------|
| `all` (default) | *(no parameter)* | Facebook's unfiltered default |
| `shipping` | `shipping` | **Nationwide** — only listings that ship |
| `local` | `local_pick_up` | Listings offering local pickup |

- **`shipping` is the nationwide lever.** The `--location` slug does not change
  the result set: `evansville` and `seattle` returned the same 30/30 item IDs
  (live 2026-08-18), and sellers span the country. The slug is still validated.
- **`local` means "offers local pickup", not "local only".** A listing can carry
  both `local_pick_up` and shipping; 1 of 30 rows in a live `local` run also
  carried `SHIPPING_ONSITE`.
- **Requires `--query`.** The browse feed ("Today's picks") has no
  delivery-method filter — live, `shipping` and `local_pick_up` returned the
  same 18 rows there, including out-of-area listings — so the flag is rejected
  without a query rather than sent into a filter that does not exist.
- **Only verified tokens are sent.** Facebook does not ignore an unknown token:
  `deliveryMethod=local` left every filter radio unchecked and the filter button
  reading `Delivery method:` with no value.

#### Location slugs are validated (no silent home-city fallback)

An unrecognized `--location` slug **fails with a non-zero exit** and names the
slug. Facebook never errors on an unknown slug — it rewrites the URL to its
slugless surface (`/marketplace/losangeles/search/` →
`/marketplace/category/search/`; `/marketplace/losangeles/` → `/marketplace/`)
and serves the logged-in account's **own home-city** inventory. Before this
check, `--location losangeles` returned 40 Evansville-area rows under exit 0.

The final URL's own location segment is the signal, verified live against
`losangeles` and `zzzzznotaplace` (both rejected) and `evansville`, `chicago`,
`seattle`, `nyc` (all preserved, each returning its own city's listings).

#### Result depth

Facebook's Marketplace search pagination exhausts at **2,448 unique listings**.
Measured live 2026-08-18 with `--limit 5000` on three different searches —
`"lego bulk"` + shipping (92 scrolls), `"lego"` + shipping (92 scrolls), and
`"lego"` in `chicago` with no fulfillment filter (80 scrolls) — every run
stopped at exactly 2,448. The ceiling is Facebook's, not the CLI's; a `--limit`
above it simply returns 2,448.

#### `radius` is not supported, on purpose

Facebook's `radius` URL parameter does **not** widen a search. Live 2026-08-18,
`radius=1` and `radius=99999` returned byte-identical 100-row result sets to a
search with no `radius` at all (100/100 identical item IDs, same four
locations), on both the city-slug surface and the `latitude`/`longitude`
surface. It only changes the rendered "Within N mi" label — and its unit is
**kilometers**, not miles (`radius=500` renders "Within 311 mi";
`radius=161` renders "Within 100 mi"). Use `--delivery-method shipping` for
nationwide reach.

#### Prices and price drops

Every listing record carries three price fields:

| Field | Meaning |
|-------|---------|
| `price` | The current/active asking price, as a number |
| `original_price` | The struck-through pre-drop price, or `null` when the seller never lowered it |
| `price_currency` | The currency symbol Facebook rendered, verbatim (`"$"`, `"CA$"`, `"£"`) |

Facebook renders a discounted listing as the current price immediately followed
by the struck-through original (`$15` `$20`), with no separator in the page
text. Both `list` and `get` read the price element's own text for the current
price and the nested struck-through element for the original, so the two are
never merged.

`price_currency` matters because Marketplace shop listings are priced in the
seller's currency — live Evansville results include `$`, `CA$`, and `£`. Compare
`price` across listings only when `price_currency` matches; never assume USD.

```bash
# Listings the seller has discounted
facebook marketplace list --query "LEGO" --properties title,price,original_price
```

#### Delivery types (fulfillment) and location

Every listing record carries `delivery_types` — Facebook's own per-listing
fulfillment model, reported verbatim. Observed tokens (live 2026-07-26):

| Token | Meaning |
|-------|---------|
| `IN_PERSON` | Meet the seller |
| `PUBLIC_MEETUP` | Meet at a public location |
| `DOOR_PICKUP` | Collect at the seller's door |
| `DOOR_DROPOFF` | Seller drops off at your door |
| `SHIPPING_ONSITE` | Ships via Facebook checkout |

The tokens are **not normalized** — a value Facebook adds later passes straight
through rather than being silently dropped. Anything starting with `SHIPPING`
means the listing ships; the rest are local collection/delivery.

None of this is rendered as text on the page. The detail page shows only the
seller's free-form meet-up prose ("Meet on Kansas Road in Evansville"), and a
search tile shows either a place name **or** the string "Ships to you" — and
which one it shows is a *distance* decision, not a fulfillment one, so a
shipping-capable listing near you still renders a place name. The CLI therefore
reads Facebook's own listing data (the Relay payload that hydrates the page and
the pagination responses served while scrolling), keyed by listing ID.

**`null` means UNKNOWN, never "no shipping offered".**

- `marketplace get` **never** returns `null`. A listing whose `delivery_types`
  cannot be read exits non-zero, because a record that reads as "local pickup
  only" would be reporting the CLI's ignorance as Facebook's data. This applies
  to cached records too.
- `marketplace list` reports `null` only for a tile Facebook's own payload never
  described, and prints a warning naming those listing IDs. The known case is
  the "commerce_interesting_product" notification tile Facebook injects into the
  grid, whose data comes from the notifications feed. Use `marketplace get` on
  those IDs for a definitive read.
- The field is never an empty list. `[]` would read as "this seller offers no
  fulfillment at all", so the model rejects it.

`location` on `get` comes from Facebook's own `location_text` ("Evansville, IN").
On `list` it comes from the tile; a tile that renders "Ships to you" instead of a
place name reports `location: null` — "Ships to you" is a fulfillment hint, not a
place, and `delivery_types` carries that answer.

```bash
# Which listings ship?
facebook marketplace list --query "LEGO" --properties item_id,title,delivery_types
facebook marketplace get 1716979012677494 --properties title,location,delivery_types
```

#### One listing, two IDs

Facebook identifies a listing by **two** IDs — a listing ID and a story/post ID —
and links to it by either. A search tile links by the listing ID; the injected
notification tile links by the post ID. The listing's own payload node is always
keyed by the listing ID and publishes the post ID in its `story.post_id` and
`product_item.id` fields, so `marketplace get` accepts either ID and resolves the
alias from Facebook's own data.

`item_id` in the output is the ID you asked for, not a canonical one. Two records
for the same listing under its two IDs are the same listing.

#### Availability

`availability` reports `Sold`, `Pending`, `Available`, or `null` (unknown) on
**both** surfaces, mapped from Facebook's own `is_sold` / `is_pending` /
`is_live` booleans in the same listing node that carries `delivery_types`.
Rendered banner text is not read. A consumer re-checking many saved listings for
sold state gets the answer from one `list` call instead of one `get` per listing.

A row Facebook never described reports `availability: null`, which means unknown,
never "still for sale".

#### Seller

`seller_id` and `seller_name` report who is selling the listing, on **both**
surfaces, read from Facebook's own `marketplace_listing_seller` node in the same
listing node that carries `delivery_types`. `seller_id` is the numeric profile ID
and is the stable key; `seller_name` is the display name, which a person can
change.

The rendered "Seller information" heading on the detail page is not read. The
description extractor already finds that heading and uses it only to mark where
the description ends.

Both fields report `null` when Facebook's payload named no seller. Unlike
`delivery_types`, that is not an error: an absent seller cannot be misread as a
different seller.

```bash
# Group a search by seller without a per-listing detail call
facebook marketplace list --query "LEGO" --properties item_id,title,seller_id,seller_name
```

#### Images

`marketplace get` returns the listing's full media gallery in `image_urls` (the
hero image plus every thumbnail). `marketplace list` returns Facebook's own tile
photo in `primary_image_url` — a square-cropped CDN render of the first gallery
photo, taken from the search payload. It is reported separately because it is one
cropped image, not the gallery; putting it in `image_urls` would claim the
listing has exactly one photo.

`--download-images` also writes the gallery to a local cache and reports the file
paths in `local_images`. Image URLs are returned either way, so reading a photo
needs no download. Sidebar advertisement creatives served from the same Facebook
CDN, and the images of the recommended listings shown below a detail page, are
excluded.

```bash
# Tile photo and sold state for a whole search, no per-listing navigation
facebook marketplace list --query "LEGO" --properties item_id,availability,primary_image_url
```

#### Empty results

An empty result is only ever reported when Facebook itself says so. `marketplace
list` returns `[]` with exit code 0 only when Facebook renders its results
container together with its own `No listings found for "..." within N miles`
message. Any other empty outcome — the results container never rendered, the
page never settled, a login/block wall, or listing tiles the extractor could not
read — exits non-zero with an error naming the cause. A silently empty result on
a healthy session is treated as a bug, not as "no matches".

### Messenger

Facebook Messenger conversations and messages.

```bash
# List conversations
facebook messenger list
facebook messenger list --table --limit 10
facebook messenger list --filter "name:contains:John"
facebook messenger list --properties id,name

# Get conversation with messages
facebook messenger get 123456789
facebook messenger get 123456789 --table
facebook messenger get 123456789 --limit 20

# Send a message
facebook messenger send 123456789 --text "Hello!"
facebook messenger send 123456789 -m "Thanks for your message"

# List message requests
facebook messenger requests
facebook messenger requests --table
```

### Groups

Read posts from Facebook Groups, list joined groups, create posts, comment, and reply.

```bash
# List the groups you've joined and the join requests still pending
facebook groups list
facebook groups list --table --limit 50
facebook groups list --filter "membership:eq:member"

# Get one group, including whether this session can read its posts
facebook groups get 123456789
facebook groups get 123456789 --properties group_id,privacy,membership,posts_readable

# List posts from a group (by ID or name)
facebook groups posts list 123456789
facebook groups posts list my-group-name

# Output formatting
facebook groups posts list 123456789 --table --limit 10
facebook groups posts list 2318028917 --limit 25 --full-threads
facebook groups posts list 123456789 --properties post_id,author,text
facebook groups posts list 123456789 --filter "author:contains:John"

# Get a specific post
facebook groups posts get https://www.facebook.com/groups/123/posts/456
facebook groups posts get 123/posts/456
facebook groups posts get 123/posts/456 --table

# Create a post in a group
facebook groups posts create 123456789 --text "Hello everyone!"
facebook groups posts create 123456789 -m "Looking for advice on shipping"

# Comment on a post
facebook groups posts comment https://www.facebook.com/groups/123/posts/456 --text "Great post!"
facebook groups posts comment 123/posts/456 -m "Thanks for sharing"

# Reply to a comment (by 1-based comment index)
facebook groups posts reply https://www.facebook.com/groups/123/posts/456 --comment-index 1 --text "Good point!"
facebook groups posts reply 123/posts/456 -c 2 -m "I agree"
```

### Groups Smoke Test

Run the batched groups smoke test to reuse one authenticated browser session for auth, joined groups, group post listing, and post get:

```bash
~/.local/share/uv/tools/facebook-cli/bin/python3 scripts/smoke_groups.py --group-id 2318028917
```

### Groups Get Instrumentation

Measure end-to-end process timing for `facebook groups get`, including CLI startup, the browser credential gate, page load, extraction, and JSON output:

```bash
~/.local/share/uv/tools/facebook-cli/bin/python3 scripts/instrument_groups_get.py GROUP_ID --iterations 3 --output data/group-get-timings.json
```

### Groups Posts Instrumentation

Measure end-to-end process timing for `facebook groups posts list`, including CLI startup, authenticated group-page fetch, GraphQL feed fetch, extraction, and JSON output:

```bash
~/.local/share/uv/tools/facebook-cli/bin/python3 scripts/instrument_groups_posts_list.py GROUP_ID --limit 3 --iterations 3 --output data/group-posts-timings.json
```

`facebook groups posts list` returns the latest 20 posts by default and accepts
`--limit` values from 1 to 25. Add `--full-threads` to fetch the thread
permalink, full body text, image URLs, and nested comments/replies for each
returned post in a single command invocation.

### Group membership and readability

`facebook groups get` reports three fields read from the live group page and
never inferred:

| Field | Values | Meaning |
|-------|--------|---------|
| `privacy` | `public`, `private` | Facebook's own privacy setting for the group. |
| `membership` | `member`, `pending`, `non_member` | Where the authenticated account stands. `pending` means a join request was submitted and has not been approved. |
| `posts_readable` | `true`, `false` | Whether this session can actually read the group's posts. A member always can; a non-member or pending requester can read a public group and cannot read a private one. |

```bash
facebook groups get 1647953932130640
# {"group_id": "1647953932130640", "name": "The Lego Group - Buy, Sell & Swap",
#  "url": "...", "member_count": "13.9K members", "privacy": "private",
#  "membership": "pending", "posts_readable": false}
```

`facebook groups posts list` **fails loudly** on an unreadable group instead of
returning an empty list:

```bash
facebook groups posts list 1647953932130640 --limit 2
# exit code 1
# stderr: Error: UNREADABLE_GROUP: Facebook group 1647953932130640
#         (privacy=private, membership=pending) is not readable by this
#         authenticated session, so its posts cannot be listed. ...
```

The `UNREADABLE_GROUP:` prefix is a stable marker. Exit code 1 with that marker
means "this session cannot see the group"; exit code 0 with `[]` means the group
is readable and genuinely has no posts in the requested window; exit code 2
still means a credential failure.

`facebook groups list` reports `group_id`, `name`, `url`, and `membership`
(`member` or `pending`) for every row, joined groups first. Facebook renders
neither privacy nor member counts on that page, so `privacy`, `posts_readable`,
and `member_count` stay `null` there — run `groups get` for those. `group_id` is
Facebook's own URL reference: the numeric id, or the vanity slug for groups that
have one. Every `facebook groups ...` command accepts either.

### Profiles

Manage authentication profiles for multiple accounts.

```bash
# List all profiles
facebook auth profiles list

# Create a new profile
facebook auth profiles create work

# Select active profile
facebook auth profiles select work

# Delete a profile
facebook auth profiles delete work
```

### Cache

Manage the local data cache.

```bash
# View cache status
facebook cache status

# Clear all cached data
facebook cache clear
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping
- **Table** (`--table`): Human-readable formatted table

## Filtering

Use `--filter` for client-side filtering with the format `field:operator:value`:

```bash
# Exact match
facebook marketplace list --filter "location:eq:New York, NY"

# Price range
facebook marketplace list --filter "price:gt:50"

# Contains
facebook marketplace list --filter "title:contains:LEGO"

# Messenger conversations
facebook messenger list --filter "name:contains:John"
```

Supported operators: `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `contains`, `startswith`, `endswith`, `in`, `nin`, `like`, `ilike`, `null`, `notnull`

## Configuration

Non-auth configuration is stored in `~/.local/share/cli-tools/facebook/.env`.
Browser-auth profiles live under
`~/.local/share/cli-tools/facebook/authentication_profiles/<profile>/`.

Facebook login runs in normal headed Chrome, while routine commands reuse the
same persistent profile headlessly. The CLI derives a normal Chrome User-Agent
from the installed Chrome version for both modes so Facebook sees one consistent
browser fingerprint instead of `Chrome` during login and `HeadlessChrome`
during automation. Set `BROWSER_USER_AGENT` only when an explicit override is
required.

Example root config:

```bash
# Required: active profile marker
ACTIVE=true

# Base URL
BASE_URL=https://www.facebook.com/marketplace

# Underlying CLI command (defaults to playwright)
CLI_COMMAND=playwright
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/CLI not available error |
| 130 | User interrupted (Ctrl+C) |

## Requirements

- Python 3.9+
- `playwright` CLI installed and in PATH
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - pydantic
  - cli-tools-shared

## License

MIT
