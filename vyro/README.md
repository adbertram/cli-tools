# Vyro CLI

## DESCRIPTION

Use this CLI to read Vyro clipping campaigns, account details, linked social accounts, and campaign eligibility through Vyro's authenticated web API. It can enroll in campaigns and submit already published, owned TikTok posts using explicit account bindings and campaign-rule approval. It does not link accounts or publish videos.

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

A successful read is not permission to submit a post. Readiness verifies the linked TikTok record, campaign dates/platform/budget/enrollment, eligibility, rate limits and throttle state. It cannot verify an unpublished video; submission additionally requires the native pre-check and campaign rules approval. In October 2026 the UI described a YouTube audience-insights upgrade while explicitly saying its current connection would continue to work; `requiresScopeUpgrade` alone is not treated as a universal submission blocker.

## API scope and failures

Observed on October 13, 2026: `https://api.vyro.com/auth/me`, `/catalog/campaigns`, `/catalog/campaigns/slug/{slug}`, `/catalog/campaigns/slug/{slug}/eligibility`, and `/social-accounts/me`. Browser refresh uses the service's `/auth/refresh` route and HttpOnly cookie. Access tokens remain inside the browser. Requests use `x-realm: vyro-app` and the authenticated account's single clipper workspace; ambiguous or missing workspaces fail explicitly.

This is an internal web API and can change. Authentication failures, malformed responses, duplicate campaign IDs, and invalid pagination fail explicitly. No fallback to Whop or guessed data is used. JSON/data goes to stdout; errors go to stderr with a nonzero exit status.

## Tests

```bash
uv run --project vyro pytest vyro/tests
_repo/skills/cli-tool/scripts/validate-cli-tool.sh vyro
_repo/skills/cli-tool/scripts/test-cli-tool.sh --cli-name vyro --profile adam
```

## Guarded submissions

```bash
vyro submissions readiness CAMPAIGN_SLUG --expected-account-id VYRO_ACCOUNT_ID --expected-social-account-id VYRO_SOCIAL_ID --expected-username TIKTOK_HANDLE --profile adam
vyro campaigns join CAMPAIGN_SLUG --expected-account-id VYRO_ACCOUNT_ID --expected-social-account-id VYRO_SOCIAL_ID --expected-username TIKTOK_HANDLE --yes --profile adam
vyro submissions create CAMPAIGN_SLUG --url https://www.tiktok.com/@HANDLE/video/POST_ID --requirements-digest DIGEST_FROM_READINESS --expected-account-id VYRO_ACCOUNT_ID --expected-social-account-id VYRO_SOCIAL_ID --expected-username TIKTOK_HANDLE --yes --profile adam
vyro submissions reconcile CAMPAIGN_SLUG --url https://www.tiktok.com/@HANDLE/video/POST_ID --expected-account-id VYRO_ACCOUNT_ID --expected-social-account-id VYRO_SOCIAL_ID --expected-username TIKTOK_HANDLE --profile adam
vyro submissions list --campaign-slug CAMPAIGN_SLUG --limit 100
vyro submissions get NATIVE_RECEIPT_ID
```

Vyro social-account IDs and `platformUserId` values are not TikTok Studio numeric account IDs. Bind the exact Vyro account, social record and handle. `--yes` explicitly authorizes the operation and affirms the full campaign rules. The requirements digest covers native rules, sources, platform targeting, dates, creator preferences and payout terms; live spend is excluded. Missing required checks fail explicitly.

Create sends the observed `{videoUrl, socialAccountId, campaignId}` payload to `/clips/pre-check` and then `/clips/v2`. Vyro’s write protocol encodes UTF-8 JSON as base64 inside a CBOR text item with `application/octet-stream`; plain JSON writes are rejected. It checks current rules again after pre-check, does not retry writes, and returns `created`, `existing` or `uncertain` with the native receipt in `submission` when verified. Reconcile returns `existing` or `not_found` after an exhaustive bounded read of `/clips/me`, matching campaign, canonical URL and the linked account's opaque platform ID. More than 1,000 receipts fails explicitly rather than claiming absence.

Before dispatch, a private, fsynced, exclusive-create marker persists under the authentication profile's `vyro-submissions` directory. Concurrent or repeated create calls for that same actor/campaign/post cannot dispatch twice. An ambiguous failure keeps the marker; reconcile may find a receipt later. `not_found` after an uncertain write does not authorize retry, and there is intentionally no automatic marker reset. A legitimate owned TikTok post was submitted and reconciled successfully on October 13, 2026; smoke tests never submit unrelated posts.

Native receipt UI fields verified from the service client include `id`, `campaignId`, `platform`, `platformUserId`, `videoUrl`, `videoRawUrl`, `status.id`, `earnings.totalEarnings`, `earnings.cpm` (dollars), and `metrics.totalViews`. No zero earnings or receipt is fabricated when fields are absent.

## Clip analytics

```bash
vyro analytics list --profile adam --limit 100
vyro analytics list --profile adam --properties id,post_url,views,likes,comments,shares,metrics_updated_at,observed_at --table
vyro analytics get SUBMISSION_ID --profile adam
```

Every call queries the authenticated provider directly, without a response cache or Trawler data. `observed_at` records when the response was read; it does not promise that the provider refreshed social metrics at that instant. Missing metrics remain `null`; reported zero values and numeric strings are preserved. `native` retains every provider field, including additional metrics, payout terms and review status. Lists are bounded by `--limit`; filters run locally over the fetched rows.

Use `analytics list --campaign-slug SLUG` to scope clips to one campaign. Views, likes and comments come from `metrics.totalViews`, `metrics.totalLikes` and `metrics.totalComments`; `metrics_updated_at` is `metrics.lastMetricsUpdatedAt`. Shares are not exposed in the observed response and remain null. `earnings` preserves native `totalEarnings`, `cpm` and `updatedAt` when present. `analytics get` verifies the receipt belongs to the currently authenticated account before returning metrics.
