---
name: facebook-ads-cli
description: >-
  Use for Meta/Facebook Marketing API service operations using facebook-ads CLI:
  accounts, campaigns, ad sets, ads, creatives, audiences, pixels, catalogs,
  targeting, insights, reporting, images, videos, uploads, and Graph batches.
  DO NOT use for CLI implementation, testing, updating, troubleshooting,
  validation or removal; route lifecycle work through cli-tool.
---

<objective>
Execute Meta Marketing API operations through the installed facebook-ads CLI,
with complete generated Business SDK dispatch and versioned Graph access.
</objective>

<project_overrides>
Before acting, run:
```bash
~/.agents/skills/skill-expert/scripts/load-skill-overrides.sh facebook-ads-cli
```
Apply printed instructions. No output means no override; nonzero means stop and
report the broken override rather than silently proceeding.
</project_overrides>

<quick_start>
Read adjacent `usage.json` before executing commands. It is the authoritative
argument/option map; inspect only the relevant command node. Run command help
when syntax is unclear, never invent flags or API parameters.

```bash
facebook-ads sdk coverage
facebook-ads sdk resources list --filter 'name:contains:Audience'
facebook-ads sdk methods list AdAccount
facebook-ads sdk methods get AdAccount get_campaigns
facebook-ads sdk schema AdAccount --method get_insights
facebook-ads auth status --profile default
facebook-ads accounts list --limit 1 --fields id,name
facebook-ads campaigns list --parent act_123 --limit 10
facebook-ads sdk call AdAccount get_campaigns act_123 --fields id,name --all-pages --limit 100
facebook-ads graph request GET act_123/campaigns --params '{"limit":10,"fields":"id,name"}'
facebook-ads insights start act_123 --params @insights.json
facebook-ads insights wait 123 --timeout 600
facebook-ads insights results 123 --limit 100
```
</quick_start>

<essential_principles>
- Public API first. Do not substitute browser account cookies for Marketing API access.
- SDK is pinned to facebook-business 26.0.2; default Graph version v26.0. Catalog
  contains 1105 Graph resource/schema classes, 362 callable resource classes and
  1503 generated FacebookRequest operations.
  Discovery/schema/dispatch coverage does not mean every endpoint was tested live.
- Use `sdk schema RESOURCE --method METHOD` for complete parameter types/enums.
  Generic inherited helpers and endpoints absent from the SDK use `graph request`.
- `--params` accepts inline object JSON, @file, or stdin -. Files use repeatable
  `--file FIELD=path`; raw Graph video uploads may use `--video-host`.
- Use read-only calls for verification. Advertising changes require explicit
  user authorization, then --yes; --dry-run constructs requests without network
  or credentials. Do not launch ads or spend as a test.
- Batch returns all individual results, including failed bodies/codes, with
  nonzero exit on failure. Omitted successful responses remain null.
- Named list output is a plain array; get output is the resource object.
  All returned fields are preserved unless --properties selects fields.
  Graph requests preserve envelopes; credential values in paging URLs are redacted.
- Lists support --filter/-f, --limit/-l, --properties/-p and --table/-t.
  Native filters translate supported operators; unsupported syntax fails explicitly.
- Every network command accepts --profile. Token needs ads_read/ads_management
  and ad-account asset access. Other SDK resources have their own permissions.
- Use owning CLI-tools secret-manager skill for reusable credentials. auth login
  stores token through shared manager, never raw .env values. Optional app secret
  is saved with facebook-ads app-secret and enables appsecret_proof.
- Top-level method/_method override parameters (including batch URL/body) require
  --yes or --dry-run and disable GET retries; provider override support is unverified.
- GET retries use shared exponential backoff; mutations/batch POST are never
  retried automatically. Async insights start creates a reporting job only.
</essential_principles>

<reference_index>
- `usage.json`: installed CLI command tree, options, arguments and defaults.
- [Official SDK](https://github.com/facebook/facebook-python-business-sdk)
- [Marketing API](https://developers.facebook.com/docs/marketing-api/)
</reference_index>

<success_criteria>
Use documented commands, honor auth and mutation requirements, return complete
API data, and verify requested service outcome without claiming untested coverage.
</success_criteria>
