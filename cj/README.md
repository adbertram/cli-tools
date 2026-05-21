# CJ Affiliate CLI

`cj` is a publisher-side command-line interface for [CJ Affiliate](https://www.cj.com/) (Commission Junction). It enables bulk discovery of CJ advertiser programs through the public REST/GraphQL API and bulk application to those programs through the publisher Marketplace UI.

## Why two auth mechanisms

CJ splits its public surface across two systems:

- The **REST API** at `advertiser-lookup.api.cj.com` and the **GraphQL API** at `ads.api.cj.com/query` expose the full advertiser catalogue, relationship status, link inventory, and reports. They authenticate with a **Personal Access Token (PAT)** generated at <https://members.cj.com/member/PersonalAccessTokens/tokens.cj> and sent as `Authorization: Bearer <token>`.
- The **publisher Marketplace** (apply / join an advertiser program, manage applications) lives only in the authenticated web UI at <https://members.cj.com/member/{publisher-id}/publisher/marketplace/>. CJ exposes no public mutation for the join action.

`cj` uses both: PAT for everything `advertisers ...` and `relationships list`/`get`, and a persistent Playwright browser session for `relationships apply` and `relationships apply-bulk`.

## Installation

```bash
uv tool install -e <cli-tools-root>/cj
```

The `cj` executable is then on `$PATH`.

## Quick start

```bash
# 1. Configure auth (PAT prompt + interactive browser login).
cj auth login

# 2. List the publisher's current relationships.
cj relationships list --status joined --table

# 3. Discover programs you have NOT joined yet.
cj advertisers list --relationship notjoined --keywords "hosting" --table

# 4. Apply to one program (idempotent — skips if already joined/pending/declined).
cj relationships apply 1234567

# 5. Apply to many programs from a file.
cj relationships apply-bulk targets.txt --delay 4
```

## Configuration

Per-profile environment variables live under `~/.local/share/cli-tools/cj-cli/authentication_profiles/<profile>/.env`. `cj auth login` writes them for you.

| Variable | Purpose |
|----------|---------|
| `CJ_PERSONAL_ACCESS_TOKEN` | Bearer token for the REST/GraphQL APIs |
| `CJ_PUBLISHER_ID` | Your CJ company id (e.g. `7955906`); appears as `requestor-cid` in API calls |
| `CJ_BROWSER_SESSION` | Optional override for the playwright-cli session name (default `cj`) |

## Commands

### Authentication (`cj auth`)

```bash
cj auth login                  # Interactive PAT + browser login
cj auth login --force          # Re-run the login even if a session already exists
cj auth status                 # JSON report of every profile's credential state
cj auth logout                 # Clear PAT and browser session for the active profile
cj auth profiles list          # Inspect/switch named profiles
```

### Advertisers (`cj advertisers`)

Read-only discovery on top of the CJ Advertiser Lookup REST API.

```bash
# Generic list — defaults to relationship=joined.
cj advertisers list
cj advertisers list --relationship notjoined --limit 50 --table
cj advertisers list --keywords "wordpress" --category "Computer & Electronics"
cj advertisers list --name "Bluehost"
cj advertisers list --filter "primary_category:eq:Software"
cj advertisers list --page 2 --limit 100

# Wildcard search.
cj advertisers search "*hosting*"
cj advertisers search "Bluehost" --table

# Full record for one advertiser.
cj advertisers get 1234567 --table
cj advertisers get 1234567 --properties "advertiser_name,primary_category,actions"
```

### Relationships (`cj relationships`)

```bash
# List/inspect.
cj relationships list                       # joined relationships (default)
cj relationships list --status pending
cj relationships list --status declined --table
cj relationships get 1234567 --table

# Apply (browser-driven; idempotent).
cj relationships apply 1234567              # Submit a join request
cj relationships apply 1234567 --dry-run    # Check status only

# Bulk apply.
cj relationships apply-bulk targets.txt --delay 4
cj advertisers list --relationship notjoined \
  --properties advertiser_id | jq -r '.[].advertiser_id' \
  | cj relationships apply-bulk - --delay 3
cj relationships apply-bulk targets.txt --stop-on-error --table
```

`apply` calls the REST API first to detect an existing relationship and skip the click when the publisher is already joined, pending, or declined. Failures capture a Playwright screenshot under `~/.local/share/cli-tools/cj-cli/authentication_profiles/<profile>/apply-screenshots/`.

### Links (`cj links`)

```bash
# List creatives for one advertiser.
cj links list 4837117 --limit 20
cj links list 4837117 --type "Text Link" --filter "promotion_type:eq:coupon" --table
cj links list 4837117 --properties "link_id,link_name,click_url"

# Inspect one creative.
cj links get 14729571 --table

# Build a deep-link tracking URL without calling the API.
cj links deeplink 4837117 "https://www.example.com/product" --sid "blog-post-slug"
```

`links list` uses CJ's Link Search API and supports the standard CLI list flags: `--table`, `--limit`, `--filter`, and `--properties`. `links deeplink` is local URL generation and requires only `CJ_PUBLISHER_ACCOUNT_ID`.

### Cache (`cj cache`)

```bash
cj cache stats
cj cache clear
cj cache list
```

## Filters

`--filter` accepts the standard `field:op:value` syntax. Operators supported by the CJ filter map: `eq`, `ne`, `contains`, `exists`. Examples:

```bash
cj advertisers list --filter "relationship_status:eq:joined"
cj advertisers list --filter "primary_category:contains:Software"
cj advertisers list --filter "network_rank:exists"
```

Server-side translation happens automatically when CJ exposes a matching query parameter (`keywords`, `category`, `advertiser-name`, `advertiser-ids`). Anything else is applied client-side.

## Output

Every command obeys the project conventions: JSON on stdout by default, `--table` for human-readable Rich output, `--properties` for field selection (dot notation), `--limit` for capping result size. Diagnostics and progress go to stderr.

## API references

- REST advertiser lookup: <https://developers.cj.com/legacy/rest-apis/advertiser-lookup>
- GraphQL products: <https://developers.cj.com/graphql-resources/schema>
- Personal Access Tokens: <https://members.cj.com/member/PersonalAccessTokens/tokens.cj>
- Publisher Marketplace: <https://members.cj.com/member/{publisher-id}/publisher/marketplace/>
