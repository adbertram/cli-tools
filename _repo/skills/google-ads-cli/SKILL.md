---
name: google-ads-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute GoogleAds operations using the `google-ads` CLI tool.
  CLI interface for GoogleAds.
  Triggers: google-ads, google-ads cli
---

<objective>
Execute GoogleAds operations using the `google-ads` CLI. All GoogleAds interactions should use this CLI.
</objective>

<project_overrides>
Before acting on this skill, run:

```bash
~/.agents/skills/skill-expert/scripts/load-skill-overrides.sh google-ads-cli
```

Apply any printed instructions alongside this skill's own workflow: they extend it and
never repeal its limits. No output means no project override is in effect. A non-zero
exit means the project's override file is broken -- report it and stop rather than
silently running unmodified.
</project_overrides>

<quick_start>
The `google-ads` CLI follows this pattern:
```bash
google-ads <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Call any official SDK RPC | `google-ads api call <SERVICE> <METHOD>` |
| Export measured manifest of every reachable service/RPC | `google-ads api coverage` |
| Show every method and request/response type for a service | `google-ads api methods <SERVICE>` |
| Export complete request/response protobuf fields, nested types, enums and oneofs | `google-ads api schema <SERVICE> <METHOD>` |
| Show every generated service without authentication | `google-ads api services` |
| Show versions available in the pinned SDK without authentication | `google-ads api versions` |
| Copy explicitly named OAuth app secrets; clear prior Ads tokens; never import another tool's tokens | `google-ads auth client import` |
| Configure authentication credentials | `google-ads auth login` |
| Clear stored credentials | `google-ads auth logout` |
| Create a new profile from .env.example template | `google-ads auth profiles create <NAME>` |
| Delete a profile and its data | `google-ads auth profiles delete <NAME>` |
| Get details for a specific profile | `google-ads auth profiles get <NAME>` |
| List all profiles and show their auth types and active state | `google-ads auth profiles list` |
| Delete a profile and its data | `google-ads auth profiles remove <NAME>` |
| Rename a profile, re-keying its secrets to the new profile name | `google-ads auth profiles rename <OLD> <NEW>` |
| Activate a profile within its auth type | `google-ads auth profiles select <NAME>` |
| Refresh OAuth access token using stored refresh token | `google-ads auth refresh` |
| Check authentication status across profiles | `google-ads auth status` |
| Test authentication by verifying credentials work across profiles | `google-ads auth test` |
| Get customer identity, status, currency and timezone through GAQL | `google-ads customers get <CUSTOMER_ID>` |
| List directly accessible customer resource names; manager descendants require GAQL customer_client | `google-ads customers list` |
| Search all GAQL-supported resources, metrics, segments and fields | `google-ads query search <QUERY>` |
| Clear local cache | `google-ads cache clear` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `google-ads` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `google-ads --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **api** -- Offline SDK discovery and full RPC access (subcommands: call, coverage, methods, schema, services, versions)
- **auth** -- Manage google-ads authentication (subcommands: client, login, logout, profiles, refresh, status, test)
- **cache** -- Shared cache maintenance (subcommand: clear)
- **customers** -- Discover accessible Ads customer accounts (subcommands: get, list)
- **query** -- Run Google Ads Query Language queries (subcommands: search)
</principle>

<principle name="Pinned Complete API">
SDK33.0.0 uses APIv25 (includes v25.2), with 111 cataloged services and 174 RPCs including four official Operations methods. Use `api services`, `api methods SERVICE`, and `api schema SERVICE METHOD` for exact request fields. Generic `api call` reaches every cataloged RPC; RPC names use snake_case. Version selection must be explicit when overriding the pinned default.
</principle>
<principle name="Auth and Mutation Controls">
Developer tokens were sunset September9 2026 and are not required. Google Cloud project API access, Ads account permission, and adwords OAuth scope are required. Use shared `auth login`; reusable app secrets stay in the CLI-tools secret manager. `auth client import` copies only explicitly named app secrets and requires fresh Ads consent. Never reuse another tool's token without verified Ads scope. Mutating or unclassified RPCs require --yes, supported --validate-only, or offline --dry-run. No live mutation belongs in a smoke test.
</principle>
<principle name="Complete Output">
Single-page RPCs return their full envelope; --all-pages returns all full page envelopes. Streaming RPCs print full batches as JSONL. GAQL WHERE and LIMIT perform server filtering; customers list limit/filter are local because accessible-customer API supports neither. Partial failures retain the full response in stderr and exit nonzero. Long-running RPCs return operation envelopes; poll with OperationsService get_operation.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`google-ads --help` and subcommand `--help`** -- Live installed command tree and option list.
**`../../../google-ads/README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
