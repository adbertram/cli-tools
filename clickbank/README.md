# ClickBank CLI

CLI for the documented ClickBank REST APIs at `https://api.clickbank.com/rest/1.3`.

Implemented endpoint families:
- `orders2`
- `products`
- `quickstats`
- `marketplace` (browser-driven; see [Marketplace](#marketplace) below)

## Install

```bash
cd <cli-tools-root>/clickbank
uv tool install -e . --force --refresh
```

## Authenticate

```bash
clickbank auth login
clickbank auth status
```

`auth login` stores the raw ClickBank API key used in the `Authorization` header. The CLI does not use Bearer tokens for these commands.

## Commands

### Orders

```bash
clickbank orders get <receipt> [--sku SKU] [--table] [--properties field1,field2]
clickbank orders list [--limit 100] [--page 1] [--filter "field:eq:value"] [--table] [--properties field1,field2]
clickbank orders count [--filter "field:eq:value"] [--table]
clickbank orders upsells <receipt> [--table] [--properties field1,field2]
```

Documented order filters:
- `affiliate`
- `amount` (`orders list` only)
- `email`
- `item`
- `lastName`
- `postalCode` (`orders list` only)
- `role`
- `startDate`
- `endDate`
- `tid`
- `type`
- `vendor`

Examples:

```bash
clickbank orders get 6X5W8DF2
clickbank orders list --filter "vendor:eq:mysite" --filter "startDate:eq:2026-05-01" --filter "endDate:eq:2026-05-09"
clickbank orders count --filter "type:eq:SALE"
clickbank orders upsells 6X5W8DF2 --table
```

### Products

```bash
clickbank products get <sku> --site <nickname> [--table] [--properties field1,field2]
clickbank products list --site <nickname> [--limit 100] [--page 1] [--filter "field:eq:value"] [--table] [--properties field1,field2]
clickbank products create <sku> --param key=value [--param key=value ...]
clickbank products delete <sku> --site <nickname>
```

`products create` uses documented query parameters only. Repeat `--param` for each field you want to send. The CLI validates the documented required parameter sets instead of inventing a wider schema.

Minimum one-time digital example:

```bash
clickbank products create ABC123 \
  --param site=mysite \
  --param currency=USD \
  --param language=EN \
  --param price=49.95 \
  --param title="Example Product" \
  --param digital=true \
  --param categories=EBOOK \
  --param pitchPage=https://example.com/pitch \
  --param thankYouPage=https://example.com/thanks
```

Product list examples:

```bash
clickbank products get ABC123 --site mysite
clickbank products list --site mysite --filter "status:eq:ACTIVE"
clickbank products delete ABC123 --site mysite
```

### Quickstats

```bash
clickbank quickstats accounts [--table] [--properties field1,field2]
clickbank quickstats get <account> [--table] [--properties field1,field2]
clickbank quickstats count [--filter "field:eq:value"] [--table]
clickbank quickstats list [--limit 100] [--page 1] [--filter "field:eq:value"] [--table] [--properties field1,field2]
```

Documented quickstats filters:
- `account`
- `startDate`
- `endDate`

Examples:

```bash
clickbank quickstats accounts
clickbank quickstats get mysite --table
clickbank quickstats count --filter "account:eq:mysite"
clickbank quickstats list --filter "startDate:eq:2026-04-01" --filter "endDate:eq:2026-04-30" --table
```

### Marketplace

The `marketplace` subcommand group searches the public ClickBank affiliate
marketplace — used to **discover products to promote**, NOT to manage your
own products. ClickBank does not publish a REST endpoint for marketplace
search, so this group talks to the private GraphQL endpoint at
`https://accounts.clickbank.com/graphql` from inside a persistent
Playwright session. The session is the same one `clickbank auth login` boots
(credential type `browser_session`); the marketplace is public so you do not
have to sign in to ClickBank — just dismiss any cookie banner and press
Enter at the prompt.

```bash
clickbank marketplace categories [--flat] [--limit 100] [--filter ...] [--table] [--properties ...]
clickbank marketplace search [--category NAME] [--subcategory NAME] [--query KW]
                              [--min-gravity N] [--max-gravity N]
                              [--min-avg-sale N] [--max-avg-sale N]
                              [--recurring] [--sort gravity|rank|popularity|avg-sale|new]
                              [--ascending] [--limit 25] [--page 1]
                              [--filter ...] [--table] [--properties ...]
clickbank marketplace product <VENDOR> [--table] [--properties ...]
clickbank marketplace hoplink <VENDOR>
```

Examples:

```bash
# Discover categories (cached aggressively; ~10s cold, instant warm).
clickbank marketplace categories --flat --table

# Top-gravity Health & Fitness recurring offers.
clickbank marketplace search --category 'Health & Fitness' --recurring \
  --sort gravity --limit 10 --table

# Keyword search.
clickbank marketplace search --query keto --min-gravity 20 --table

# Full record for one vendor (combines search snapshot + historical metrics).
clickbank marketplace product BRAINSONGX --table

# Build an affiliate tracking URL offline.
clickbank marketplace hoplink BRAINSONGX
```

Hoplinks of the form `https://hop.clickbank.net/?affiliate=<your-nick>&vendor=<vendor>`
are included on every search hit and on the `product` command. Set
`CLICKBANK_AFFILIATE_NICKNAME` in your profile env file to have your
affiliate nickname auto-injected; otherwise the URL embeds a literal
`{affiliate}` placeholder.

Valid `--sort` values (ClickBank's GraphQL accepts only these): `rank`,
`gravity`, `popularity`. `avg-sale` and `new` are aliases that map onto
`popularity` (the closest signal the endpoint exposes); ClickBank does not
support sorting by raw $/sale or activation date despite what the UI
might suggest.

### Cache

```bash
clickbank cache clear
```

## Notes

- List commands support the standard CLI-tool flags `--limit`, `--filter`, `--properties`, and `--table`.
- ClickBank returns up to 100 rows per request. When ClickBank responds with `206 Partial Content`, the CLI continues by sending the documented `Page` header.
- `orders count` and `quickstats count` only accept filters that map directly to documented ClickBank query parameters.
