# G2 CLI

CLI for finding G2 products and mining negative reviews through the official G2 APIs at `https://data.g2.com`.

This tool uses the authenticated API at `https://data.g2.com`. It does not scrape public G2 review pages.

## Installation

```bash
cd <cli-tools-root>/g2
uv tool install -e . --force --refresh
```

The launcher is installed at `~/.local/bin/g2`.

## Authentication

The current live G2 API uses Bearer auth on the v2 endpoints:

```text
Authorization: Bearer <token>
Accept: application/json
```

Store a token with the shared auth flow:

```bash
g2 auth login
g2 auth login --personal-access-token YOUR_TOKEN
g2 auth login --force
g2 auth status
g2 auth logout
```

## Quick Start

```bash
# Find products
g2 products search "salesforce"
g2 products get salesforce-sales-cloud

# Mine negative reviews through Data Solutions reviews
g2 reviews list salesforce-sales-cloud --stars 1 --stars 2 --limit 25
g2 reviews search salesforce-sales-cloud "slow" --stars 1 --stars 2
g2 reviews get 50
```

## API Contract

- Products use `GET /api/v2/products` and `GET /api/v2/products/{product_id}`.
- Product search uses the official v2 filters such as `filter[query]` and `filter[slug][]`.
- Review discovery uses `GET /api/v2/data_solutions/reviews` with `filter[product_id][]`.
- Review data requires the G2 `ds_reviews.read` entitlement. If your token is authenticated but not entitled, G2 returns `HTTP 403` and the CLI surfaces that response directly.
- The CLI does not fall back to public-page scraping or browser automation.

## Command Reference

### Products

```bash
# List products
g2 products list
g2 products list --limit 25
g2 products list --filter "star_rating:gte:4"
g2 products list --table
g2 products list --properties id,name,slug,star_rating

# Get one product by slug
g2 products get salesforce-sales-cloud
g2 products get salesforce-sales-cloud --table

# Search products through the official API search filter
g2 products search "crm"
g2 products search "salesforce" --limit 10 --table
```

### Reviews

```bash
# List negative reviews for a product slug
g2 reviews list salesforce-sales-cloud --stars 1 --stars 2
g2 reviews list salesforce-sales-cloud --stars 1 --limit 20 --table
g2 reviews list salesforce-sales-cloud --filter "dislike_text:ilike:%slow%"
g2 reviews list salesforce-sales-cloud --properties id,title,star_rating,dislike_text

# Get one accessible review by ID, survey response ID, or review slug
g2 reviews get 50
g2 reviews get 50 --table

# Search reviews for a product slug
g2 reviews search salesforce-sales-cloud "slow"
g2 reviews search salesforce-sales-cloud "support" --stars 1 --stars 2 --limit 15 --table
```

### Authentication Profiles

```bash
g2 auth profiles list
g2 auth profiles get default
g2 auth profiles create research
g2 auth profiles select research
g2 auth profiles delete research
```

### Cache

```bash
g2 cache clear
```

## Output Contract

### Product records

`g2 products list`, `g2 products get`, and `g2 products search` return normalized product records with:

| Field | Description |
|-------|-------------|
| `id` | G2 product UUID |
| `name` | Product name |
| `slug` | Product slug used by this CLI |
| `product_type` | G2 product type from the v2 `type` attribute |
| `domain` | Product website domain |
| `detail_description` | Seller-provided description |
| `g2_url` | Canonical G2 product URL |
| `image_url` | Product logo URL |
| `pricing_tiers` | G2 pricing tier data |
| `review_count` | Published review count |
| `star_rating` | Average rating from 0-5 |
| `public_detail_url` | Public G2 reviews page |
| `write_review_url` | G2 write-a-review URL |

### Review records

`g2 reviews list`, `g2 reviews get`, and `g2 reviews search` return normalized review records with:

| Field | Description |
|-------|-------------|
| `id` | Survey response ID |
| `product_name` | Product name from the review payload |
| `product_slug` | Product slug passed to the CLI for list/search, or `product_id` from accessible review data for `reviews get` |
| `star_rating` | Review star rating |
| `title` | Review title |
| `dislike_text` | Text from Data Solutions `hate` |
| `recommendation_text` | Text from Data Solutions `recommendations` |
| `benefits_text` | Text from Data Solutions `benefits` |
| `review_source` | Data Solutions `source` |
| `submitted_at` | Review submission timestamp |
| `public_url` | Data Solutions `url` |

## Review Access Limits

- `g2 reviews list` and `g2 reviews search` only work when the token can access `/api/v2/data_solutions/reviews`.
- `g2 reviews get` does not use a separate by-ID endpoint because the current official docs available here only substantiate the Data Solutions list endpoint. The command scans accessible review data and matches `id`, `survey_response_id`, or review `slug`.
- If the token is not entitled for review data, review commands fail with the upstream `HTTP 403`.

## Filtering and Search

List and search commands support:

- `--filter` / `-f` with shared filter syntax such as `field:eq:value` or `field:ilike:%text%`
- `--limit` / `-l` to cap returned results
- `--table` / `-t` for table output
- `--properties` / `-p` to select a subset of fields

Search commands do case-insensitive wildcard matching across normalized output fields. If the query contains no `*`, the CLI wraps it as `*query*`.

## Configuration

Profile data is stored outside the repo under:

```text
~/.local/share/cli-tools/g2/authentication_profiles/<profile>/
```

The active profile `.env` contains:

```bash
ACTIVE=true
PERSONAL_ACCESS_TOKEN=
BASE_URL=https://data.g2.com
```

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `1` | General error |
| `2` | Authentication or credential error |
| `130` | User interrupted |
