# Rakuten Advertising CLI

CLI for the [Rakuten Advertising Publisher API](https://developers.rakutenadvertising.com/).
Lists advertiser programs the publisher can apply to or has joined.

## Installation

```bash
uv tool install -e /Users/adam/Dropbox/GitRepos/cli-tools/rakuten
```

## Authentication

Rakuten uses OAuth 2.0 with the `password` grant. Five values are
required:

- **Client ID + Client Secret** — Add an Application in the Developer
  Portal at https://developers.rakutenadvertising.com/
  (Developer Portal -> Add Application). Copy the Client ID and Client
  Secret it generates.
- **Publisher SID** — your publisher Site/Scope ID, visible in the
  top-right of https://pubdashboard.rakutenadvertising.com.
- **Publisher dashboard username + password** — the credentials you use
  to log in to the publisher dashboard. They are required by the OAuth
  password grant.

```bash
rakuten auth login
```

You will be prompted for:

1. **Client ID**
2. **Client Secret**
3. **Publisher SID**
4. **Publisher dashboard username**
5. **Publisher dashboard password**

The CLI caches the resulting access token in the profile env until it
expires (60 minutes) and refreshes it automatically.

```bash
rakuten auth status
rakuten auth logout
```

## Commands

### `advertisers`

```bash
# List approved advertisers
rakuten advertisers list
rakuten advertisers list --table
rakuten advertisers list --status approved --limit 50

# Filter (eq only)
rakuten advertisers list --filter "category:eq:Apparel"

# Get one advertiser by merchant id (mid)
rakuten advertisers get 12345
```

### `auth`

```bash
rakuten auth login
rakuten auth status
rakuten auth logout
rakuten auth profiles list
```

### `cache`

```bash
rakuten cache stats
rakuten cache clear
```

## Output

All commands emit JSON to stdout by default. Pass `--table` / `-t` for a
formatted table. Use `--properties` / `-p` for a comma-separated field
selection.

## Filters

Every `list` command supports `--filter field:op:value` (repeatable).
Rakuten's API uses equality query params; pass `field:eq:value` to fold
them into the request.
