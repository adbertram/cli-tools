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
```

**Options:**
| Option | Description |
|--------|-------------|
| `-p, --page` | Page number (default: 1) |
| `-c, --category` | Category filter (art, jewelry, clothing, etc.) |
| `-s, --sort` | Sort by: ending, newest, oldest, price_low, price_high |
| `--type` | Listing type: auction or fixed_price |
| `--status` | Listing status: active, completed, or any |
| `--min-price` | Minimum price filter |
| `--max-price` | Maximum price filter |

### Get Item Details

```bash
shopsalvationarmy search get <item-id>
shopsalvationarmy search get <item-id>
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
