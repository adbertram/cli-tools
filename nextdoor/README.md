# Nextdoor CLI

## DESCRIPTION

A command-line interface for Nextdoor's GraphQL API, authenticated with a saved
browser session. Covers the neighborhood feed, the For Sale & Free classifieds
(with direct listing URLs and prices), global content search, notifications, and
the current user profile.

Use this CLI when you need scriptable, JSON-first access to Nextdoor from agents, automation, or terminal workflows.

## Docs

- Base URL: https://nextdoor.com/api/gql


## Installation

```bash
cd <cli-tools-root>/nextdoor
uv tool install -e . --force --refresh
```

After installation, the `nextdoor` command will be available in your terminal.

## Quick Start

```bash
# Authenticate with Nextdoor
nextdoor auth login

# List feed items
nextdoor feed --limit 10

# Show table output
nextdoor feed --limit 10 --table

# Browse the For Sale & Free classifieds with direct listing URLs
nextdoor classifieds list --limit 20 --table

# Search Nextdoor content
nextdoor search "lego" --limit 10 --table

# Get current user profile
nextdoor me --table
```

## Commands

### Authentication (`nextdoor auth`)

```bash
# Interactive login
nextdoor auth login

# Force re-authentication
nextdoor auth login --force

# Check authentication status
nextdoor auth status

# Run the configured live auth test
nextdoor auth test

# Clear saved credentials/session
nextdoor auth logout
```

### Profiles (`nextdoor auth profiles`)

```bash
# List all profiles
nextdoor auth profiles list

# Show a profile
nextdoor auth profiles get default

# Select the active profile for its auth type
nextdoor auth profiles select PROFILE_NAME

# Create a profile
nextdoor auth profiles create PROFILE_NAME

# Delete a profile
nextdoor auth profiles delete PROFILE_NAME
```

### Feed

```bash
# View feed (default sort is newest-first)
nextdoor feed --limit 25

# View feed with table output
nextdoor feed --limit 25 --table

# Explicit newest-first (chronological)
nextdoor feed --sort newest --limit 25

# Oldest-first over the fetched page
nextdoor feed --sort newest --desc --limit 25

# Nextdoor's algorithmic "For you" feed
nextdoor feed --sort relevance --limit 25

# Filter feed
nextdoor feed --filter "type:eq:POST"

# Restrict output fields
nextdoor feed --properties "id,title,url"

# Only feed items that are For Sale & Free listings (they carry a price)
nextdoor feed --limit 50 --filter "type:eq:POST" --properties "title,price,url"
```

Every POST row carries `url`, the post's real permalink. Nextdoor permalinks are
opaque short slugs that exist only in the API response
(`https://nextdoor.com/p/Wg398DknXZ_z?view=detail`) — they are **not** derivable
from the numeric `id`, so the CLI never synthesizes one. PROMO (ad) rows have no
permalink and report `url: null`.

#### Feed sorting

The `feed` command follows the Source-CLI Sort Standard with a **server-side
recency sort**. Nextdoor's `PersonalizedFeed` query accepts a `sortOrder`
argument (its own `sortOrderOptions` advertise a chronological "Recent" order),
so the ordering is done by the server, not re-sorted client-side.

| `--sort` | Server order | Natural direction | Notes |
|----------|--------------|-------------------|-------|
| `newest` (default) | `RECENT_POSTS` | Most recent post first | The default; what incremental "newest-first" crawlers rely on. |
| `relevance` | `FOR_YOU` | Nextdoor's algorithmic ranking | Optional. `--desc` is rejected (relevance has no reverse). |

- `--sort`/`-s` selects the field; the default is `newest`.
- `--desc`/`-d` reverses the natural direction. For `newest`, `--desc` yields
  oldest-first **over the fetched page** (Nextdoor exposes no server-side
  oldest-first order, so the fetched page is reversed client-side).
- An unrecognized `--sort` value fails fast with a clear error listing the valid
  values and a non-zero exit code — there is no silent fallback.
- The feed is heterogeneous: POST items are chronological under `RECENT_POSTS`,
  while PROMO (ad) items are interleaved by the server and carry no timestamp.

### Classifieds (`nextdoor classifieds`)

Nextdoor's dedicated "For Sale & Free" section
(<https://nextdoor.com/for_sale_and_free/>), backed by the same
`searchClassifiedV2` GraphQL operation the web grid issues. Every organic row
carries a **direct listing URL** and the listing price.

```bash
# Browse listings, newest first (default)
nextdoor classifieds list --limit 25

# Table output
nextdoor classifieds list --limit 25 --table

# Keyword-search the classifieds (see "Keyword search is not a filter" below)
nextdoor classifieds list "lego" --limit 25 --filter "type:eq:ORGANIC,title:contains:lego"

# Nextdoor's own "Most Relevant" ordering
nextdoor classifieds list --sort relevance --limit 25

# Oldest-first over the fetched pages
nextdoor classifieds list --sort newest --desc --limit 25

# Only real listings (drop the sponsored grid slots)
nextdoor classifieds list --filter "type:eq:ORGANIC"

# Only discounted listings (they carry a struck-through original price)
nextdoor classifieds list --limit 100 --filter "original_price:notnull"

# Restrict output fields
nextdoor classifieds list --properties "title,price,url"

# Full detail for one listing (the UUID from `list` or the listing URL)
nextdoor classifieds get e0a5a7da-7c11-410a-b185-930cca2a1818
nextdoor classifieds get e0a5a7da-7c11-410a-b185-930cca2a1818 --table
```

The grid is cursor-paginated at ~20 nodes per page; `--limit` transparently
follows the server's `endCursor` until it has enough rows.

#### Keyword search is not a filter

The positional `QUERY` is sent verbatim as `classifiedSearchArgs.query` to
Nextdoor's own For Sale & Free search — verified live, because a nonsense token
returns zero rows:

```bash
nextdoor classifieds list "zzzzznotarealthing"   # -> 0 rows
```

But Nextdoor ranks by relevance with **no relevance floor**, so it pads thin
result sets with unrelated listings rather than returning fewer rows. `wheelchair`
returns real wheelchairs *and* "Burgundy Sofa"; `lego` (no local inventory)
returns only padding such as "Vintage Secretary Desk". Row counts for the same
keyword vary between consecutive calls. The operation exposes no exact-match
argument and no relevance threshold.

Post-filter every keyword search, with all conditions in **one** `--filter`:

```bash
nextdoor classifieds list "lego" --limit 50 \
  --filter "type:eq:ORGANIC,title:contains:lego"
```

Repeating `--filter` is OR, not AND. Comma-separated conditions inside a single
`--filter` are AND. Zero rows after post-filtering is the honest answer: Nextdoor
has no local listing for that term.

#### Classifieds sorting

| `--sort` | Server order | Natural direction | Notes |
|----------|--------------|-------------------|-------|
| `newest` (default) | `SORT_BY_TIME` | Most recently listed first | The site's "Newest" menu option. |
| `relevance` | `SORT_BY_DISTANCE_AND_DATE` | Nextdoor's ranking | The site's "Most Relevant" default. `--desc` is rejected. |

Both are genuine server-side sorts sent via
`classifiedSearchArgs.filters.sortOrder`. `--desc` with `newest` reverses the
fetched pages client-side (Nextdoor exposes no oldest-first order). Nextdoor's
classifieds API has **no price sort**, so `--sort price` is rejected rather than
silently returning arbitrary order.

### Notifications

```bash
# View notifications
nextdoor notifications --table
```

### Me

```bash
# View current user profile
nextdoor me --table
```

### Search

Nextdoor's real content search (the `search` GraphQL operation behind
<https://nextdoor.com/search/>). It returns results from every content section —
For Sale & Free listings, neighbors, events, businesses and posts — each with a
direct URL.

```bash
# Search everything
nextdoor search "lego" --limit 25 --table

# Only For Sale & Free listings
nextdoor search "lego" --limit 50 --filter "section:eq:CLASSIFIED"

# Only posts
nextdoor search "roof repair" --filter "type:eq:post" --properties "title,url"
```

The `search` operation accepts no sort or paging arguments, so the command
exposes no `--sort`/`--desc`; `--limit` caps the flattened result list.

## Output Formats

- JSON is the default output format.
- Add `--table` / `-t` for human-readable table output.

## AI Instruction Results

Commands that reach a non-deterministic boundary may return an AI instruction result instead of normal resource data. This is JSON on stdout with `type: "ai_instruction"` and tells the calling AI agent what objective to complete, what context is available, what tools are allowed, and what success means.

The CLI must not call an LLM or include required pre-action command lists. Optional `verification_commands` and `follow_up_commands` may appear only for actions to run after the agent completes the instruction.

### JSON Output Example

```bash
nextdoor feed --limit 2
```

```json
[
  {
    "id": "497961402",
    "type": "POST",
    "post_type": "USER",
    "title": "Yard sale 805 e Iowa st happening now til noon",
    "price": null,
    "author": "Dee Franey",
    "created_at": "2026-07-25T13:26:26.453000+00:00",
    "url": "https://nextdoor.com/p/Wg398DknXZ_z?view=detail",
    "body": "Lots of items, come take a look."
  },
  {
    "id": "7126943074266908920",
    "type": "PROMO",
    "post_type": null,
    "title": "Mad City Showers",
    "price": null,
    "author": null,
    "created_at": null,
    "url": null,
    "body": null
  }
]
```

```bash
nextdoor classifieds list --limit 1
```

```json
[
  {
    "id": "e0a5a7da-7c11-410a-b185-930cca2a1818",
    "type": "ORGANIC",
    "title": "Pokemon Card Tins Collection",
    "price": "$150",
    "original_price": null,
    "variant": null,
    "subtitle": "9 hr ago · 8.7 mi · Evansville",
    "image_url": "https://us1-photo.nextdoor.com/post_photos/fc/0c/fc0c10ef47365f4aeba0911d9dff05f6.jpeg",
    "url": "https://nextdoor.com/for_sale_and_free/e0a5a7da-7c11-410a-b185-930cca2a1818/?init_source=search"
  }
]
```

### Table Output Example

```bash
nextdoor feed --limit 5 --table
nextdoor classifieds list --limit 5 --table
```

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display data as a table |
| `--limit` | `-l` | Maximum number of results |
| `--sort` | `-s` | Sort field: `newest` (default) or `relevance` (`feed`, `classifieds list`) |
| `--desc` | `-d` | Reverse the sort's natural direction (`feed`, `classifieds list`) |
| `--filter` | `-f` | Filter results using `field:op:value` syntax |
| `--properties` | `-p` | Restrict output to selected fields |
| `--version` | `-v` | Show version and exit |
| `--no-cache` |  | Bypass cached read responses for this execution |

`--sort`/`--desc` apply to `feed` and `classifieds list`, the two commands whose
upstream operations accept a server-side sort argument. Nextdoor's global
`search` operation takes no sort or paging arguments — results come back grouped
by its own relevance ranking — so `search` intentionally exposes no
`--sort`/`--desc`. `notifications` (dashboard badges) and `me` (user profile) are
not listing collections and take no sort options either.

## Configuration

Non-authentication configuration is stored in `~/.local/share/cli-tools/nextdoor/.env`. CLI-managed runtime auth state is stored in the active profile at `~/.local/share/cli-tools/nextdoor/authentication_profiles/<profile>/.env`. The source repo only carries `.env.example`.

Reusable CLI credentials that agents or scripts need to store/retrieve are governed by the user-level `cli-tool` skill's `references/secrets.md`.

Do not put reusable credentials in any `.env` file. Store and retrieve them through `<cli-tools-root>/_repo/_secret-manager/secrets.sh`. `.env` files are limited to non-secret config and CLI-managed runtime auth state.

Root config variables:

```bash
# Optional: override the default API base URL
BASE_URL=https://nextdoor.com/api/gql

# Optional: response cache settings
CACHE_ENABLED=true
CACHE_TTL=3600
```

### Authentication (browser session)

This is a browser-session CLI. `nextdoor auth login` opens a persistent
Chromium profile; the logged-in Nextdoor session lives entirely in that profile
under
`~/.local/share/cli-tools/nextdoor/authentication_profiles/<profile>/browser-data/chromium-profile/`.
There are no API keys, passwords, or tokens to store. Data commands read the
live session cookies from that profile and replay them as GraphQL POST
requests.

Authentication is verified by a real server check, not by cookie presence:
Nextdoor sets a `ndp_session_id` cookie even for logged-out visitors, so
`auth status` loads an auth-required page and treats a redirect to `/login/` as
not authenticated, and `auth test` makes a live `getMe` call. If the session is
stale, data commands fail loudly with `session is not authenticated ... run
'nextdoor auth login --force'` (exit code 2 on `auth test`).

The profile `.env` carries only `ACTIVE=true` — no reusable credentials. Do not
put credentials in any `.env` file.


## Cache

```bash
# Clear cached read responses
nextdoor cache clear

# Bypass the cache for one execution
nextdoor --no-cache feed --limit 10
```


## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Client/config/authentication error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### List Feed and Filter with jq

```bash
nextdoor feed --properties "id,title,url" | jq '.[].url'
```

### Export Feed to JSON File

```bash
nextdoor feed --limit 200 > feed.json
```

### Collect Newest Classifieds With Verified Listing URLs

```bash
nextdoor classifieds list --limit 100 --filter "type:eq:ORGANIC" \
  --properties "title,price,url" > listings.json
```

## Output Contract

Commands return plain JSON records (a JSON array for list commands, a JSON
object for `me`). Each list command has a stable normalized record shape and a
matching default table column order; both are defined together in
`nextdoor_cli/client.py` so they cannot drift.

`feed` — personalized feed items (GraphQL `PersonalizedFeed`). Items are
heterogeneous (POST, PROMO ads, ...), so a field is `null` when the item
genuinely does not carry it:

| Field | Description |
|-------|-------------|
| `id` | Item `contentId` |
| `type` | `feedItemType` (e.g. `POST`, `PROMO`) |
| `post_type` | POST subtype (`USER`, `NEWS_ARTICLE`); `null` for PROMO |
| `title` | Classified post → `post.classified.title`; plain post → `post.subject`; PROMO → sponsor name |
| `price` | Listing price when the post is a For Sale & Free classified; otherwise `null` |
| `author` | `post.author.displayName` |
| `created_at` | ISO-8601 UTC timestamp from `post.createdAt.epochMillis` |
| `url` | Absolute post permalink from `post.detailLink.href` (an opaque slug, never derived from `id`); `null` for PROMO |
| `body` | Classified description, or the post body |

`classifieds list` — For Sale & Free listings (GraphQL `searchClassifiedV2`):

| Field | Description |
|-------|-------------|
| `id` | Listing `contentId` (UUID) |
| `type` | Grid node type: `ORGANIC` for real listings, `CLASSIFIEDS_GAM_ITEM`/`CLASSIFIEDS_NAMPLUS_ITEM` for sponsored slots |
| `title` | Listing title |
| `price` | Current price display (`$150`, `FREE`); `null` when the listing shows no price |
| `original_price` | Struck-through pre-discount price; `null` when not discounted |
| `variant` | Selected variant line under the title, e.g. `Color: Rescue Red/Navy/White`; `null` when the listing has none |
| `subtitle` | Nextdoor's own summary line, e.g. `9 hr ago · 8.7 mi · Evansville` |
| `image_url` | Primary listing photo |
| `url` | **Direct listing URL** |

Sponsored grid slots carry no listing identity, so all of their listing fields
are `null`. Filter them out with `--filter "type:eq:ORGANIC"`.

`classifieds get <id>` — one listing's full detail (GraphQL
`ClassifiedFeedItem`), returned as a JSON object:

| Field | Description |
|-------|-------------|
| `id` | Listing UUID |
| `title` | Listing title |
| `price` | Raw numeric price string (e.g. `150`); `null` when the listing has no price |
| `original_price` | Pre-discount price; `null` when not discounted |
| `currency` | ISO currency code (e.g. `USD`) |
| `status` | Listing status (e.g. `ACTIVE`) |
| `is_sold` | Whether the seller marked it sold |
| `category` | Named Nextdoor category (e.g. `Toys & games`) |
| `seller` | Seller display name |
| `distance_miles` | Distance from your neighborhood |
| `location` | Nextdoor location name |
| `created_at` / `expires_at` | ISO-8601 UTC timestamps |
| `photo_urls` | All listing photos |
| `url` | Canonical listing URL from Nextdoor's own `shareText` |
| `description` | Full listing description |

`search` — global content search (GraphQL `search`):

| Field | Description |
|-------|-------------|
| `id` | Result `contentId` |
| `section` | Result view: `CLASSIFIED`, `USER`, `LOCAL_EVENT`, `BUSINESS`, `POST` |
| `type` | Item `contentType` (`classified`, `user`, `localEvent`, `business`, `post`); `null` for sponsored slots |
| `title` | Result title (price split off for classified results) |
| `price` | Listing price for classified results; `null` otherwise |
| `subtitle` | Nextdoor's own summary line for the result |
| `url` | Direct URL to the listing, profile, event, page or post |

`notifications` — dashboard badge/shortcut entries (GraphQL `dashboardBadges`):

| Field | Description |
|-------|-------------|
| `id` | Shortcut `type` slug (e.g. `saved_bookmarks`, `events`) |
| `label` | Display title (e.g. `Bookmarks`) |
| `badges` | Unread badge value (`null` when none) |

`me` — the raw authenticated user object (GraphQL `getMe`, `data.me.user`),
returned as a JSON object. Top-level fields include `id`, `legacyUserId`,
`secureUserId`, `name` (`{displayName, ...}`), `avatar`, `hasUnverifiedFeed`,
`feedOrderingModePreferences`, and various NUX-state arrays. `--table` renders
it as a field/value table, summarizing nested objects/lists for readability
(use default JSON output for the full structure).

When a request hits a logged-out session, the affected command fails loudly
(exit code 1, error on stderr; `auth test` exits 2) rather than returning empty
or wrong data.

## Requirements

- Python 3.11+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests

## License

MIT
