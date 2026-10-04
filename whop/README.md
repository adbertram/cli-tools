# Whop CLI

## DESCRIPTION

Read Whop participant accounts and Content Rewards linked accounts, campaigns, submissions, and earnings, and explicitly submit verified published clips. Use it to inspect campaign rules and actual creator performance through an isolated saved browser profile.

## Scope

The CLI uses observed participant endpoints through the shared browser engine. Reads remain separate from the explicit journaled submission operation. The CLI cannot connect accounts, apply to campaigns, withdraw funds, or change settings.

## Authentication

```bash
whop auth profiles create rewards
whop auth login --profile rewards
whop auth status --profile rewards
whop auth profiles list
```

Login prompts for your explicit embedded Content Rewards URL (`https://YOUR_APP.apps.whop.com/c/exp_YOUR_EXPERIENCE`). No personal app or experience is configured by default. Complete Whop sign-in manually in the CLI-owned Chrome window, then open your Content Rewards experience in that same window before confirming login. This persists Whop and embedded-app sessions in the selected CLI profile. MFA and human challenges stay manual. Portable import is supported only through the owning CLI commands documented below.

Reusable human-supplied credentials belong in the CLI-tools secret manager (`_repo/_secret-manager/secrets.sh`), never `.env` files. Only CLI-managed runtime session state and non-secret setup belong in profile configuration. Prefer a named profile to isolate this participant session.

## Read commands

```bash
whop account get --profile rewards
whop linked-accounts list --profile rewards --limit 10 --table
whop linked-accounts get LINKED_ACCOUNT_ID --profile rewards
whop campaigns list --profile rewards --limit 20 --sort newest
whop campaigns get CAMPAIGN_ID --profile rewards
whop campaigns applications --profile rewards
whop submissions list --profile rewards --status approved --limit 20
whop submissions list --profile rewards --status pending --retainer
whop submissions list --profile rewards --status history
whop submissions get SUBMISSION_ID --profile rewards
whop submissions status --profile rewards
whop earnings get --profile rewards --start 2026-10-01T00:00:00Z --end 2026-10-02T00:00:00Z
whop earnings payouts --profile rewards --limit 20
```

List operations support `--limit/-l` (1–1000), `--filter/-f` (`field:op:value`), `--properties/-p`, and `--table/-t`. Get/status operations support `--table`. JSON is the default stdout format; progress and errors go to stderr. For example:

```bash
whop campaigns list --profile rewards --limit 10 --filter 'status:eq:active' --properties id,name,status --table
whop linked-accounts list --profile rewards --filter 'platform:eq:tiktok' --properties id,username,verificationSource
```

Campaigns, submissions, and payouts pass limits and cursors to the server. Linked accounts have no observed pagination or server limit, so that finite read applies its limit locally. General `--filter` is explicitly local because these participant endpoints do not expose the shared filter syntax. Filters apply to the fetched, bounded set and may return fewer rows. Complete reward API row fields are retained unless properties are explicitly selected. Account output whitelists observed identity, profile, balance and earnings fields; authentication/session and risk-verification payloads are excluded. It adds measurement time and endpoint provenance.

Submission `get` searches the verified approved/pending/history lists for clips and retainers, bounded at 1000 rows per list. There is no observed submission-detail endpoint or nonempty record schema. Failure means the record was not found in that bounded inspection, not proof that no record exists. History sends `isDeleted:true`; it never invents a history status. Server action IDs are discovered from current page bundles and only the three verified read actions are permitted. Changed or unsupported action encodings fail explicitly.

Earnings require an explicit timezone-aware date range no longer than 366 days and one unambiguous Content Rewards creator ID from the linked registry. Currency, string amounts, nulls, and measured fields remain exactly as returned. No missing amount is replaced with zero, and views or CPM forecasts are not labeled earned money. Whop account balances and Content Rewards creator analytics are separate surfaces. Active bio verification of a linked account is not proof of OAuth authorization.

## Verified clip submissions

```bash
whop submissions readiness CAMPAIGN_ID --profile rewards --expected-account-id EXPECTED_WHOP_ID --expected-tiktok-account-id EXPECTED_TIKTOK_NUMERIC_ID
whop submissions create REQUEST_UUID CAMPAIGN_ID --profile rewards --expected-account-id EXPECTED_WHOP_ID --expected-tiktok-account-id EXPECTED_TIKTOK_NUMERIC_ID --requirements-digest ACCEPTED_DIGEST --publication-receipt RECEIPT_JSON --confirm
whop submissions reconcile REQUEST_UUID --profile rewards
```

Run readiness before private TikTok upload, then immediately before public Post with `--requirements-digest` set to the originally accepted digest. It verifies the exact authenticated Whop actor, one active linked numeric TikTok account, active public campaign with remaining TikTok funds, open campaign/platform intake, no creator cap, the current requirements, and the dynamically discovered create action. Application-required campaigns fail explicitly. Loading the observed Submit clip dialog obtains its dynamic action bundle without entering a URL, accepting a checkbox, or submitting anything. Requirements include the campaign description, reference materials, platforms and TikTok payout terms. Spend totals are checked fresh but excluded from the digest.

The receipt is the owning Studio SDK runtime bridge object: `publication_id`, exact canonical `publication_url`, numeric `account_id`, `handle`, UTC `published_at`, and canonical JSON `provenance` containing `kind:studio_verified`, `request_id`, `post_project_id`, `asset_sha256`, `policy_digest`, and exact Studio items readback endpoint. The timestamp must come from the verified provider publication time. A receipt is explicit caller authority, not a cryptographic attestation; the trusted runtime constructs it from the owning SDK and coordinator journal. Whop independently validates the linked account, duplicate post and 30-minute freshness window.

`create` requires `--confirm`. SDK `create_submission` accepts either explicit `True` authority or a confirmation callback called after fresh readiness immediately before dispatch. A private profile-owned SQLite journal binds UUID, actor, campaign, post, receipt and accepted brief before any mutation. Indexed request lookup and a unique actor/experience/campaign/post constraint have no operation-count cutoff. FULL synchronous commits precede dispatch. A request can dispatch at most once, with no read-transport retry loop. Repeated identical UUIDs reconcile existing state; changed bindings and another UUID for the same owned publication are refused. The states `dispatching`, `uncertain`, and `created_unverified` never authorize another write. A timeout, 429/5xx, malformed response or missing readback keeps recoverable uncertainty. Reconcile uses the observed unfiltered campaign-only participant action. A known create-response ID can verify on its exact ID/campaign/platform/post row without scanning all history. Unknown-ID recovery retains a bounded cursor/match, refreshes the head on each pass, continues across calls, and restarts after provider end-of-list. A pass reads at most eleven pages of fifty rows; no fixed total-history cutoff exists. An empty or partial inspection never authorizes another write. The denied generic submission REST-detail route is not used. Remote duplicates fail explicitly. `submitted_verified` retains an exact participant readback, while `submission.status` keeps moderation separate. Later read misses or errors may preserve this historical state with `readback_fresh:false` and the original `observed_at`; `inspection_observed_at` records the later attempt. Never use a historical result as a new earnings/moderation measurement. Missing individual earnings remain null. SDK errors expose sanitized `code`, `category`, `status`, and `retry_after_seconds` (`retry_after` alias). Uncertain/rejected operation receipts retain these in `failure`; valid Retry-After seconds or HTTP dates are preserved even beyond 24 hours. A persisted `retry_not_before` prevents immediate reconciliation reads during a provider cooldown.

No real nonempty create response or submission record has yet been observed; the first valid published clip must verify this boundary before end-to-end completion is claimed.

## Cache and profile maintenance

```bash
whop cache clear
whop auth profiles get rewards
whop auth profiles select rewards
whop auth logout --profile rewards
```

Read commands do not cache API data. Profile activation, logout and cache clearing are explicit local maintenance commands, not remote account changes. They are unnecessary for normal reads with `--profile`.

## Development

```bash
uv run --project whop python -m pytest whop/tests -q
_repo/skills/cli-tool/scripts/validate-cli-tool.sh whop
_repo/skills/cli-tool/scripts/test-cli-tool.sh --cli-name whop
```

The full live compliance run requires a saved authenticated profile. Source/parser tests do not prove live authentication or a nonempty submission/payout schema.

## Portable named sessions

Provision the explicit nonsecret root Rewards URL before importing a profile:

```bash
whop config set-rewards-url https://YOUR_APP.apps.whop.com/c/exp_YOUR_EXPERIENCE
whop auth session-export --profile rewards --expected-account-id EXPECTED_USER_ID --output PRIVATE_RUNTIME_FILE
whop auth session-import --profile rewards --expected-account-id EXPECTED_USER_ID --stdin < PRIVATE_RUNTIME_FILE
```

The URL command sets a missing value, preserves other root fields, and refuses a different existing URL. It does not create or select an authentication profile. Session bundles contain only cookies for whop.com and the configured app host, plus localStorage from https://whop.com and that exact app origin. They do not include whop.tw, raw Chrome profiles, keychains, passwords, or unrelated browser state.

Bundles must remain in private CLI runtime storage. Import requires an absent named destination on macOS, restores into private inactive staging, reopens the browser for an exact live account check, publishes exclusively, and checks identity again. It never activates a profile. Existing profiles are refused. Device verification or another failure retains private recovery state; after the browser closes, `whop auth session-import-recover --profile rewards` recovers only importer-owned state. Successful import removes its private transfer backup. IndexedDB, sessionStorage, service workers, and hardware-bound state are not transferred.
