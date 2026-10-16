# Promote.fun CLI

## DESCRIPTION

Read PromoteFun public clipping campaigns and native details through the official application’s read-only Convex queries. Use it to discover campaigns; rules, minimum views and private operations remain unavailable until authenticated contracts are measured.

## Commands

```bash
promote-fun campaigns list --limit 1000
promote-fun campaigns list --platform tiktok --search audio --table
promote-fun campaigns list --filter 'costPer1kViews:gte:1' --properties _id,title,costPer1kViews
promote-fun campaigns get silva-bumpa-audio
promote-fun campaigns get silva-bumpa-audio --table
promote-fun --version
promote-fun --help
```

`list` supports `--limit/-l` (1–1000), `--table/-t`, `--filter/-f`, `--properties/-p`, `--status` (default `active`), `--platform`, `--search` and `--sort` (default `newest`). Status/platform/search/sort and cursor pagination run on the server. General filters and properties apply locally to the bounded fetched set. `get` accepts a native ID or slug and `--table/-t`. Both accept `--profile` for workflow compatibility; public reads do not send authentication. JSON stdout contains native records without invented fields.

## Money and missing rules

`costPer1kViews` is USD dollars per 1,000 views. `totalBudget` is the total campaign budget in USD dollars, not remaining budget or earnings. The official campaign UI renders those values as dollars and labels the rate `per 1k`.

Public detail reports `rulesAccess.canViewRules` and may omit `campaignRules`. Missing rules, minimum views, payout caps, remaining budget, or eligibility are unknown. They must never become zero, approval, or a claim that a clip can earn. The frontend schema has `postingRequirements.minViewsPerPost` and `minViewsForPayout`, but this CLI has not observed actual values while signed out.

## Authentication checkpoint

```bash
promote-fun auth profiles list
promote-fun auth profiles create clipper
promote-fun auth login --profile clipper
promote-fun auth status --profile clipper
promote-fun auth test --profile clipper
promote-fun auth logout --profile clipper
promote-fun auth profiles get clipper
promote-fun auth profiles select clipper
promote-fun auth profiles rename clipper creator
promote-fun auth profiles remove creator
promote-fun auth seed-shared-chromium-profile
```

`auth login --force/-F` opens the official campaign page, https://www.promote.fun/campaigns. Sign in or register using its Clerk sign-in control, then link TikTok @ata_clipper in the app. Authorized signup and sign-in use the provider’s normal browser flow; human-only verification gates must be handed off. The CLI saves the browser profile; `auth status` performs a live read against `users:current` using Clerk's Convex session token. It prints the standard `profiles[].authenticated` JSON. Live saved-session authentication and current-account readback were verified on 2026-10-16. Public list/get do not use that saved authentication; authenticated campaign/membership/submission support is a future measured extension.

Website login passwords belong in LastPass. Reusable CLI tokens belong in the CLI-tools secret manager, never `.env`. Browser session state is CLI-managed. No private bearer tokens are printed.

## Cache commands

```bash
promote-fun cache clear
```

Public reads are live and are not cached; the shared cache command manages any existing tool cache.

## Contract provenance

Verified 2026-10-15 from official app assets `index-7nSc8Q1i.js`, `campaigns-LeAe9k8B.js`, `_id-14NKefzw.js` and the Convex client asset. Deployment: `https://dapper-duck-781.convex.cloud`; read-only transport is `POST /api/query`, with `{path, format:"convex_encoded_json", args:[object]}`. Campaign queries are `campaigns:listCampaigns` and `campaigns:getCampaignBySlugOrId`. HTTP POST here invokes a query, never a mutation. Failures are sanitized, retries bounded, pagination/schema failures explicit.

## Saved account identity

```bash
promote-fun auth login
promote-fun auth status
promote-fun account get
```

Sign in through the provider website in the CLI-owned Chrome window, then press Enter to save. Website passwords belong in LastPass; this CLI persists its browser session. Account output excludes tokens.
