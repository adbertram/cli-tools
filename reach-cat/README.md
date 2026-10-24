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

Browser login and current Firebase identity are measured. Joins, account linking, submissions and earnings remain unsupported. On 2026-10-16 Google sign-in succeeded, but the provider displayed “Registration temporarily unavailable” and paused new creator registrations. A saved Firebase identity does not prove a usable creator profile.

## Source contract

Verified 2026-10-15 from official app assets `index-fzSh_eRr.js`, `public-BgNBWwh4.js`, `CampaignJoin-BMgRvH79.js`, and the campaign editor. The official Firebase deployment is `https://reachcat-api-default-rtdb.europe-west1.firebasedatabase.app`; public app reads `static/campaigns/{id}`. REST equivalents are GET `/static/campaigns.json` with key-order pagination and GET `/static/campaigns/{id}.json`. Campaign URL: `https://reach.cat/campaign/{id}/join`. Only query reads are implemented.

## Saved account identity

```bash
reach-cat auth login
reach-cat auth status
reach-cat account get
```

Sign in through the provider website in the CLI-owned Chrome window, then press Enter to save. Website passwords belong in LastPass; this CLI persists its browser session. Account output excludes tokens.

Firebase identity alone does not prove creator onboarding. On 2026-10-16 the site paused new creator registrations; `account get` reports `onboarding_complete: false` on the signup route. No bypass or business-account substitution is supported.

The identity probe uses the measured Firebase module `/assets/firebase-Df3M1fEi.js` from the current official app. A provider asset change fails closed until that contract is rechecked; it never guesses a new export. `onboarding_complete` is false when the observed route is signup and null elsewhere. Firebase authentication alone does not mark the creator account usable.
