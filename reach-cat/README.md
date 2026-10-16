# ReachCat CLI

## DESCRIPTION

Use ReachCat public campaign discovery to inspect native view thresholds, rates, remaining budgets and campaign rules. This read-only CLI exposes sanitized Firebase campaign records without claiming signed-in eligibility or supporting submissions.

## Commands

```bash
reach-cat campaigns list --limit 1000
reach-cat campaigns list --platform tiktok --table
reach-cat campaigns list --filter 'minViewsForPayout:lte:2000' --properties id,name,minViewsForPayout
reach-cat campaigns list --status INACTIVE --limit 10
reach-cat campaigns get 1881f79e-70ae-4613-9c17-762aa487854d
reach-cat campaigns get 1881f79e-70ae-4613-9c17-762aa487854d --table
reach-cat cache clear
reach-cat --version
reach-cat --help
```

`list` supports `--limit/-l` (1–1000), `--table/-t`, `--filter/-f`, `--properties/-p`, `--status` (default `ACTIVE`) and `--platform`. Firebase key pagination limits each server page; native status and platform filters run locally while scanning pages until the requested matching result count or collection end. General filters apply locally to that bounded result. An empty `--status ''` includes all statuses. `get` accepts a native campaign ID and `--table/-t`. All reads are live; `cache clear` manages the shared cache directory.

## Output and missing values

Records preserve native names for displayed campaign data: `id`, `name`, `status`, `networks`, `minViewsForPayout`, `amountRemaining`, `amountCredited`, `amountConsumed`, rate/cap fields, and public `settings` requirements. An explicit allowlist removes payment records, blocked-user identities, role/member maps and wallet addresses. Missing values remain missing; no floor, budget or eligibility is invented.

`minViewsForPayout` is an integer view threshold per post. The campaign editor says a link earns nothing below this floor; once reached, all views are paid. It documents empty new-campaign input as no minimum, but this CLI preserves missing legacy values as unknown until backend defaults are verified.

The public join page displays `cpm` as dollars per 1,000 views, reading root `cpm` before `settings.cpm` when present. Rates may be numbers or decimal strings. Budget amounts are dollar display units, not cents. The UI advertises USDT payouts; that does not prove an ISO accounting currency for every record, so integrations must not invent a currency code or treat campaign amounts as earnings.

## Account checkpoint

No authenticated routes, joins, account linking, submissions or earnings have been measured. This public CLI has no `auth` group and never claims authentication. Complete the human account step before a later authenticated integration:

```bash
open https://reach.cat/signup
```

Create the account personally, then link TikTok @ata_clipper. Existing users can open https://reach.cat/signin. Agents must not create accounts, enter passwords or solve CAPTCHAs. No reusable credentials are stored by this CLI; future credentials belong in the CLI-tools secret manager.

## Source contract

Verified 2026-10-15 from official app assets `index-fzSh_eRr.js`, `public-BgNBWwh4.js`, `CampaignJoin-BMgRvH79.js`, and the campaign editor. The official Firebase deployment is `https://reachcat-api-default-rtdb.europe-west1.firebasedatabase.app`; public app reads `static/campaigns/{id}`. REST equivalents are GET `/static/campaigns.json` with key-order pagination and GET `/static/campaigns/{id}.json`. Campaign URL: `https://reach.cat/campaign/{id}/join`. Only query reads are implemented.
