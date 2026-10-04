# Whop CLI

## DESCRIPTION

Read Whop participant accounts and Content Rewards linked accounts, campaigns, submissions, and earnings. Use it to inspect campaign rules and actual creator performance through an isolated saved browser profile.

## Read-only scope

The CLI uses observed participant endpoints through the shared browser engine. It offers read operations only. It cannot connect accounts, apply to campaigns, submit clips, withdraw funds, or change settings.

## Authentication

```bash
whop auth profiles create rewards
whop auth login --profile rewards
whop auth status --profile rewards
whop auth profiles list
```

Login prompts for your explicit embedded Content Rewards URL (`https://YOUR_APP.apps.whop.com/c/exp_YOUR_EXPERIENCE`). No personal app or experience is configured by default. Complete Whop sign-in manually in the CLI-owned Chrome window, then open your Content Rewards experience in that same window before confirming login. This persists Whop and embedded-app sessions in the selected CLI profile. MFA and human challenges stay manual. Storage exported by another browser is not a supported CLI auth import.

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
