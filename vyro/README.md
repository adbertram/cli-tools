# Vyro CLI

## DESCRIPTION

Use this CLI to read Vyro clipping campaigns, account details, linked social accounts, and campaign eligibility through Vyro's authenticated web API. This adapter is read-only: it does not enroll in campaigns, link accounts, publish videos, or submit posts.

## Authentication

```bash
vyro auth login
vyro auth status
vyro auth profiles list
```

Login uses the shared browser engine and Vyro's emailed verification code. Runtime browser state is stored in the private CLI profile. Reusable CLI credentials, if introduced, belong in the CLI-tools secret manager; never put secrets in source files or `.env.example`.

Named profiles use `--profile NAME` on every data command. `vyro auth profiles select NAME` makes a profile active. The shared `auth session-export`, `auth session-import`, and `auth session-import-recover` commands provide identity-checked portable session transfer; consult their `--help` for private-file and expected-identity requirements. An expired session fails explicitly and requires `vyro auth login`.

## Commands

```bash
vyro account get
vyro account get --table
vyro account get --properties id,username,status --profile adam
vyro campaigns list --limit 12
vyro campaigns list --filter 'status.id:eq:active' --properties id,slug,name --table
vyro campaigns get 5-guys-face-their-crush-4YWRQEx1
vyro campaigns get 5-guys-face-their-crush-4YWRQEx1 --table
vyro campaigns eligibility 5-guys-face-their-crush-4YWRQEx1
vyro campaigns eligibility 5-guys-face-their-crush-4YWRQEx1 --properties eligibleAccounts,inviteMode
vyro social-accounts list --limit 100
vyro social-accounts list --filter 'platform:eq:tiktok' --table
```

All data commands return JSON by default and support `--table/-t`, `--properties/-p`, and `--profile`. List commands also support `--filter/-f` and `--limit/-l` (1–1000). Filters are applied locally after the limit. Campaign limits are sent to the API in pages of at most 12. The observed linked-accounts endpoint returns its entire collection; its limit is applied locally. No undocumented server filter parameters are assumed.

## Native output contract

`account get` returns the full `/auth/me` object, including `id`, `username`, `email`, `status`, `verificationStatus`, `hasAcceptedCurrentTerms`, and `workspaces`.

`campaigns list` returns an array of full campaign objects, unwrapping the API's `data` list and traversing `meta.page.next`. `campaigns get` takes the exact **slug**, not the campaign ID, and returns the full campaign object. Native fields include:

- `id`, `slug`, `name`, `status.id`, `enrolled`, `isLocked`, `startDate`, `endDate`.
- `targeting.platforms` and `targeting.languages`.
- `budget.value`, `budget.spent`, and `budget.remaining` in dollars.
- `payoutModel.model` and `payoutModel.payRate` (dollars per 1,000 views for CPM).
- `requirements`, including the full HTML `brief`, hashtags, disclosure hashtags, platform rules, and minimum video length.
- `media.links[].url`, preserved as provided. This CLI does not download media.

`campaigns eligibility` returns the full eligibility object, including `eligibleAccounts` and `inviteMode`. An empty eligibility list does not itself prove that every platform is forbidden; callers must inspect linked accounts and the service's requirements.

`social-accounts list` returns native linked-account records, including `platform`, `platformUserId`, `platformUsername`, `status`, and `requiresScopeUpgrade` when present.

A successful read is not permission to submit a post. No TikTok link, campaign enrollment, or publication readiness is inferred. In October 2026 the UI described a YouTube audience-insights upgrade while explicitly saying its current connection would continue to work; `requiresScopeUpgrade` alone is not treated as a universal submission blocker.

## API scope and failures

Observed on October 13, 2026: `https://api.vyro.com/auth/me`, `/catalog/campaigns`, `/catalog/campaigns/slug/{slug}`, `/catalog/campaigns/slug/{slug}/eligibility`, and `/social-accounts/me`. Browser refresh uses the service's `/auth/refresh` route and HttpOnly cookie. Access tokens remain inside the browser. Requests use `x-realm: vyro-app` and the authenticated account's single clipper workspace; ambiguous or missing workspaces fail explicitly.

This is an internal web API and can change. Authentication failures, malformed responses, duplicate campaign IDs, and invalid pagination fail explicitly. No fallback to Whop or guessed data is used. JSON/data goes to stdout; errors go to stderr with a nonzero exit status.

## Tests

```bash
uv run --project vyro pytest vyro/tests
_repo/skills/cli-tool/scripts/validate-cli-tool.sh vyro
_repo/skills/cli-tool/scripts/test-cli-tool.sh --cli-name vyro --profile adam
```
