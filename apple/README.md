# Apple CLI

Read-only Apple purchase and subscription history lookup using the private
`reportaproblem.apple.com/api/purchase/search` endpoint with a persisted Apple
browser session.

## Installation

```bash
cd <cli-tools-root>/apple
uv tool install -e . --force --refresh
```

## Authentication

```bash
apple auth login
apple auth status
apple auth test
apple auth logout
```

`apple auth login` stores the browser session in the shared profile directory.
It also captures the first live
`POST https://reportaproblem.apple.com/api/purchase/search` request from the
authenticated browser session and persists the replay context needed for
`apple purchases list/get/match`.

During Apple two-factor authentication, the CLI watches the open browser for
Apple verification screens. When Apple offers a trusted-phone option through
`Didn't Get a Code?` or `Can't get to your devices?`, the CLI requests the
text-message path first. It then prompts for the six-digit Apple verification
code and waits up to five minutes before timing out. If Apple requires a
trusted-device approval, security key, or device passcode instead, complete
that step in the browser or provide the displayed six-digit code when prompted.
Locked, disabled, not-active, and account-recovery states stop the login flow
with an actionable error instead of continuing to poll.

If Apple rotates the browser session or purchase-search context, rerun
`apple auth login`. If purchase commands report missing request context, the
last login did not reach the authenticated purchase-history page far enough to
capture the request.

## Profiles

```bash
apple auth profiles list
apple auth profiles get default
apple auth profiles create work
apple auth profiles select work
apple auth profiles delete work
```

## Purchases

```bash
apple purchases list
apple purchases list --limit 25 --table
apple purchases list --filter "media_type:eq:Subscription"
apple purchases list --properties "id,purchase_date,name,signed_amount_paid_value,subscription_info"

apple purchases get purchase-1:item-1
apple purchases get purchase-1:item-1 --table

apple purchases match --amount -4.99
apple purchases match --date 2026-05-16
apple purchases match --query "Apple One" --limit 5 --table
apple purchases match --amount 9.99 --query "Premier" --properties "id,name,score,matched_terms"
```

## Export

```bash
apple purchases list --properties "id,purchase_date,name,signed_amount_paid_value,currency_symbol,media_type" > apple-purchases.json
apple purchases match --query "subscription" --properties "id,name,subscription_info,localized_pots_end_of_commitment_date" > apple-subscriptions.json
```

## Cache

```bash
apple cache clear
apple --no-cache purchases list --limit 10
```

## Output Contract

`apple purchases list` returns a JSON array of normalized purchase line-item
records. `apple purchases get` returns one normalized record. `apple purchases
match` returns the same record shape plus match metadata.

Common record fields:

| Field | Description |
|-------|-------------|
| `id` | Stable line-item id in `<purchase_id>:<item_id>` format |
| `purchase_id` | Apple purchase id |
| `item_id` | Apple line-item id |
| `purchase_date` | Purchase timestamp from the parent purchase |
| `invoice_date` | Invoice timestamp from the parent purchase |
| `pli_date` | Line-item timestamp |
| `name` | Display name from `localizedContent.nameForDisplay` |
| `detail` | Display detail from `localizedContent.detailForDisplay`; `null` when Apple omits or empties it |
| `title` | Apple title field from the line item |
| `media_type` | Localized media type; `null` when Apple omits or empties it |
| `line_item_type` | Apple line item type |
| `amount_paid` | Raw Apple display amount; `null` when Apple omits or empties it |
| `amount_paid_value` | Parsed unsigned decimal amount; `null` when Apple omits or empties `amountPaid` |
| `signed_amount_paid_value` | Parsed amount with credits/refunds negated; `null` when Apple omits or empties `amountPaid` |
| `currency_symbol` | Currency symbol parsed from Apple display amounts; `null` when Apple omits or empties `amountPaid` |
| `is_free_purchase` | Whether the line item was free |
| `is_credit` | Whether the line item is a credit/refund |
| `subscription_info` | Subscription info from the API when present |
| `subscription_coverage_description` | Localized subscription coverage text when present |
| `localized_pots_end_of_commitment_date` | Localized end-of-commitment text when present |

Additional `match` fields:

| Field | Description |
|-------|-------------|
| `score` | Match score used for ranking |
| `matched_amount` | Whether the requested amount matched |
| `matched_terms` | Matched date/query terms |

## Requirements

- Python 3.11+
- `cli-tools-shared`
- `requests`
- `browser-harness` through `cli-tools-shared`
