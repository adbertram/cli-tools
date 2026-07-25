# ShopSalvationArmy CLI Guide

## DESCRIPTION

The `shopsalvationarmy` CLI provides a command-line interface for Shop The Salvation Army auction site.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Overview

The ShopSalvationArmy CLI provides access to:
- **Search** - Query for items with filters
- **Auth** - Authenticate for potentially more features (though search is typically public)

## Authentication

### Login

```bash
shopsalvationarmy auth login
shopsalvationarmy auth login -u user -p pass
```

### Check Status

```bash
shopsalvationarmy auth status
```

### Logout

```bash
shopsalvationarmy auth logout
```

---

## Search Commands

Search for items.

### Query Items

```bash
shopsalvationarmy search query "camera"
shopsalvationarmy search query "vintage" --category "jewelry"
shopsalvationarmy search query "" --sort newest --limit 25          # newest listings first (default)
shopsalvationarmy search query "lego" --sort price                  # price low -> high
shopsalvationarmy search query "lego" --sort price --desc           # price high -> low
shopsalvationarmy search query "" --sort ending                     # ending soonest first
```

**Options:**
| Option | Description |
|--------|-------------|
| `-p, --page` | Page number (default: 1) |
| `-l, --limit` | Maximum number of results (default: 100) |
| `-c, --category` | Category filter (art, jewelry, clothing, etc.) |
| `-s, --sort` | Sort field: `newest` (default), `price`, `ending` |
| `-d, --desc` | Reverse the sort field's natural direction |
| `--type` | Listing type: auction or fixed_price |
| `--status` | Listing status: active, completed, or any |
| `--min-price` | Minimum price filter |
| `--max-price` | Maximum price filter |

**Sorting (Source-CLI Sort Standard):** the sort surface follows the canonical,
direction-aware vocabulary. Each field has a *natural* order (used when `--desc`
is absent); `--desc` reverses it. Unknown `--sort` values fail with a clear error
and a non-zero exit — there is no silent fallback.

| `--sort` | Natural (no `--desc`) | With `--desc` |
|----------|-----------------------|---------------|
| `newest` (default) | most recently listed first | oldest first |
| `price` | price low -> high | price high -> low |
| `ending` | ending soonest first | *not supported* — the site has no "latest ending" order, so `--sort ending --desc` is rejected with a clear error |

### Get Item Details

```bash
shopsalvationarmy search get <item-id>
shopsalvationarmy search get <item-id> --table
```

Returns the full listing detail as JSON, including a top-level `image_urls`
array of absolute, directly-fetchable listing photo URLs (full-resolution
`_largesize` images from the listing's photo gallery). The `--table` view shows
the photo count in an `Images` row.

```json
{
  "id": "561473103",
  "title": "2 Kodak EasyShare C813 Digital Cameras ...",
  "image_urls": [
    "https://shopsalvationarmyblob.blob.core.windows.net/assets/media/69d0175f-271e-4962-9cbe-d7a88b7ea3bd_largesize.jpg",
    "https://shopsalvationarmyblob.blob.core.windows.net/assets/media/506b4064-de9d-411a-a7e2-3729265445df_largesize.jpg"
  ],
  "current_price": 24.0,
  "url": "https://www.shopthesalvationarmy.com/Listing/Details/561473103"
}
```

### List Categories

```bash
shopsalvationarmy search categories
```

## Additional Commands

### Cache

```bash
shopsalvationarmy cache --help
```
