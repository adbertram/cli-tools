# PartnerStack CLI

## DESCRIPTION

The `partnerstack` CLI provides a command-line interface for Partnerstack API.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Installation

```bash
uv tool install -e . --force --refresh
```

The `partnerstack` command is installed at `~/.local/bin/partnerstack`.

## Authentication

This CLI uses both PartnerStack auth schemes because the documented endpoints do:

| Commands | Auth | Profile fields |
|----------|------|----------------|
| `rewards`, `marketplace`, `partnerships` | Bearer | `API_KEY` |
| `form-templates`, `applications` | Basic | `USERNAME` = public key, `PASSWORD` = secret/private key |

```bash
partnerstack auth login
partnerstack auth login --force
partnerstack auth status
partnerstack auth logout
```

## Profiles

```bash
partnerstack auth profiles list
partnerstack auth profiles get default
partnerstack auth profiles select PROFILE_NAME
partnerstack auth profiles create PROFILE_NAME
```

## Rewards

```bash
partnerstack rewards list
partnerstack rewards list --table
partnerstack rewards list --limit 10
partnerstack rewards list --starting-after rwrd_123
partnerstack rewards list --ending-before rwrd_123
partnerstack rewards list --filter "payment_status:eq:withdrawn"
partnerstack rewards list --filter "created_at:gte:1711034344078"
partnerstack rewards list --filter "created_at:lte:1748902440427"
partnerstack rewards list --properties "key,company.name,amount,currency,payment_status"
partnerstack rewards list --properties "id,name"
partnerstack rewards list --properties "key,customer.email,transaction.amount" --table
partnerstack rewards get rwrd_JiquWSZIPLGEXx
partnerstack rewards get rwrd_JiquWSZIPLGEXx --table
partnerstack rewards get rwrd_JiquWSZIPLGEXx --properties "key,company.name,amount"
```

Supported reward filters are sent to the PartnerStack API as query parameters:

```text
company_key
customer_key
currency
decline_reason
description
distinct_decline_reason
distinct_description
empty_line_id
exclude_drip_rewards
group_key
hide_archived_rewards
invoice_key
invoiceable
keywords
order_by
payment_status
status
created_at:gte -> min_created
created_at:lte -> max_created
```

## Output

JSON is the default output and contains the full reward objects returned by the API.

```bash
partnerstack rewards list --limit 1 | jq '.[0].key'
partnerstack rewards list --limit 50 > rewards.json
```

Use `--table` for human-readable output.

## Marketplace (program discovery)

The `marketplace` command group wraps `GET /api/v2/marketplace/programs` and `GET /api/v2/marketplace/programs/{company_key}`. These return programs the partner has *not* necessarily joined yet.

```bash
partnerstack marketplace list
partnerstack marketplace list --limit 50
partnerstack marketplace list --table
partnerstack marketplace list --filter "category:eq:artificial-intelligence"
partnerstack marketplace list --filter "created_at:gte:1711034344078"
partnerstack marketplace list --filter "created_at:lte:1748902440427"
partnerstack marketplace list --properties "key,name,category,website"
partnerstack marketplace list --starting-after co_o0m479WyGfnZ7w
partnerstack marketplace get co_o0m479WyGfnZ7w
partnerstack marketplace get co_o0m479WyGfnZ7w --table
```

Each item exposes `id` (the marketplace `company_key`, mirroring `key`), `name`, `category` (a list), `website`, `description`, `offers`, and `promotions`. Extra fields the API returns are preserved on the JSON output.

> `marketplace get` pages through `marketplace list` to find the requested company_key. PartnerStack's documented `GET /api/v2/marketplace/programs/{company_key}` endpoint returns 404 in practice for keys returned by the list endpoint, so the list-scan path is more reliable.

## Form templates and applications

PartnerStack's current API reference pages for [`GET /api/v2/form-templates`](https://docs.partnerstack.com/reference/get_v2-form-templates) and [`POST /api/v2/applications`](https://docs.partnerstack.com/reference/post_v2-applications) both show `Credentials: Basic`, not Bearer.

`GET /api/v2/form-templates` returns the form templates that describe the dynamic `meta` field set required by `POST /api/v2/applications` for a given `group`.

```bash
partnerstack form-templates list
partnerstack form-templates list --table
partnerstack form-templates list --limit 50
partnerstack form-templates list --filter "group:eq:affiliates"
partnerstack form-templates list --filter "target_type:eq:<value>"
partnerstack form-templates list --filter "mold_keys:eq:<value>"
partnerstack form-templates list --filter "created_at:gte:1711034344078"
partnerstack form-templates list --filter "updated_at:lte:1748902440427"
partnerstack form-templates list --properties "key,name,group,target_type"
partnerstack form-templates list --starting-after ft_123
partnerstack form-templates list --ending-before ft_123
```

Supported filters map onto PartnerStack query params:

```text
group:eq:<slug>              -> group
target_type:eq:<value>       -> target_type
mold_keys:eq:<value>         -> mold_keys
created_at:gte:<epoch_ms>    -> min_created
created_at:lte:<epoch_ms>    -> max_created
updated_at:gte:<epoch_ms>    -> min_updated
updated_at:lte:<epoch_ms>    -> max_updated
```

The form-template's `group` value is the valid `group_slug` to pass to `applications create`.

`POST /api/v2/applications` requires `group_slug` and a `meta` object whose required fields are vendor-defined per program. Common required fields are `first_name`, `last_name`, `email`, and `business_name`.

```bash
partnerstack applications create \
  --group-slug affiliates \
  --meta '{"first_name":"Jane","last_name":"Doe","email":"jane@example.com","business_name":"Example LLC"}'

partnerstack applications create \
  --group-slug affiliates \
  --meta-field first_name=Jane \
  --meta-field last_name=Doe \
  --meta-field email=jane@example.com \
  --meta-field business_name="Example LLC"
```

`--meta` and `--meta-field` can be combined; `--meta-field` overrides matching keys in `--meta`.

## Partnerships (post-approval relationships)

`GET /api/v2/partnerships` lists programs the partner has already joined.

```bash
partnerstack partnerships list
partnerstack partnerships list --table
partnerstack partnerships list --limit 50
partnerstack partnerships list --filter "order_by:eq:-updated_at"
partnerstack partnerships list --filter "has_sub_id:eq:true"
partnerstack partnerships list --filter "include_offers:eq:true"
partnerstack partnerships list --filter "include_archived:eq:true"
partnerstack partnerships list --properties "key,company.name,status"
partnerstack partnerships list --starting-after part_3YEsXYIA6ndzzD
partnerstack partnerships get part_3YEsXYIA6ndzzD
partnerstack partnerships get part_3YEsXYIA6ndzzD --table
partnerstack partnerships get part_3YEsXYIA6ndzzD --properties "key,company.name,status"
```

Supported filters:

```text
order_by:eq:<value>       (-created_at | created_at | -updated_at | updated_at)
has_sub_id:eq:<value>     (true | false | null)
include_offers:eq:<bool>
include_archived:eq:<bool>
```

## Cache

```bash
partnerstack cache clear
```

## Configuration

Credentials are stored in the CLI profile files managed by `partnerstack auth`.
The local `.env` file can also define:

```bash
# Bearer-auth commands: rewards, marketplace, partnerships
API_KEY=your_api_key

# Basic-auth commands: form-templates, applications
USERNAME=your_basic_public_key
PASSWORD=your_basic_secret_key

BASE_URL=https://api.partnerstack.com/api/v2
```

## Models

This CLI uses Pydantic models for type-safe data handling. Reward models preserve extra fields returned by PartnerStack so API additions are not dropped from JSON output.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication or credential error |
| 130 | User interrupted |
