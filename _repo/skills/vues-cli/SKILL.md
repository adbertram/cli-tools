---
name: vues-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute Vues operations using the `vues` CLI tool.
  CLI interface for Vues.
  Triggers: vues, vues cli
---

<objective>
Execute Vues operations using the `vues` CLI. All Vues interactions should use this CLI.
</objective>

<quick_start>
The `vues` CLI follows this pattern:
```bash
vues <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Get the signed-in creator (identity and balance, exactly as /users/me returns them) | `vues account get` |
| Configure authentication credentials | `vues auth login` |
| Clear stored credentials and browser sessions | `vues auth logout` |
| Create a new profile from .env.example template | `vues auth profiles create <NAME>` |
| Delete a profile and its data | `vues auth profiles delete <NAME>` |
| Get details for a specific profile | `vues auth profiles get <NAME>` |
| List all profiles and show their auth types and active state | `vues auth profiles list` |
| Delete a profile and its data | `vues auth profiles remove <NAME>` |
| Rename a profile, re-keying its secrets to the new profile name | `vues auth profiles rename <OLD> <NEW>` |
| Activate a profile within its auth type | `vues auth profiles select <NAME>` |
| Seed an empty shared Chromium profile from this CLI's default profile | `vues auth seed-shared-chromium-profile` |
| Export scoped cookies/localStorage after live exact-account checks | `vues auth session-export` |
| Restore, verify, close, and exclusively publish an absent profile | `vues auth session-import` |
| Recover owned closed transfer state or finalize it after exact actor proof | `vues auth session-import-recover` |
| Check authentication status across profiles | `vues auth status` |
| Test authentication by verifying credentials work across profiles | `vues auth test` |
| Get one campaign in full (CPM/rate, minimum views, budget, brief and rules, exactly as the API returns it) | `vues campaigns get <CAMPAIGN_ID>` |
| Apply to / join a campaign (the join endpoint is resolved from the API's own OpenAPI document) | `vues campaigns join <CAMPAIGN_ID>` |
| List campaigns the signed-in creator can see (requires auth; Vues gates all campaign data behind login) | `vues campaigns list` |
| Get balance, pending, paid and withdrawal minimum (whatever the earnings/balance endpoint exposes) | `vues earnings get` |
| List linked social accounts (handle, platform, verification/eligibility, as the API returns them) | `vues social-accounts list` |
| Submit a TikTok post once; an already-submitted URL returns status existing (never double-submits) | `vues submissions create <CAMPAIGN_ID>` |
| Get one submission by ID | `vues submissions get <SUBMISSION_ID>` |
| List this account's submissions (status, tracked views, earnings, as the API returns them) | `vues submissions list` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `vues` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `vues --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Authentication">
Vues signs in only with Google or Apple (Supabase); there is no API key or
password. `vues auth login` opens a browser for the one-time provider sign-in,
then captures the Supabase session; later commands run over HTTP and refresh the
session automatically. A Vues account and a linked TikTok account must exist
first (sign up at https://vues.app/login). If `vues auth status` shows no
authenticated profile, the account/linking step has not been done and no
service command will work until it is.
</principle>

<principle name="No Double Submission">
`vues submissions create` never submits the same TikTok URL twice: it checks
existing submissions for the same video id first and returns `status: existing`.
Use `--dry-run` to preview the request and `--yes` to actually submit.
</principle>

<principle name="Command Groups">
- **account** -- Current Vues creator account (subcommands: get)
- **auth** -- Manage vues authentication (subcommands: login, logout, profiles, seed-shared-chromium-profile, session-export, session-import, session-import-recover, status, test)
- **campaigns** -- Vues campaigns (subcommands: get, join, list)
- **earnings** -- Balance and earnings (subcommands: get)
- **social-accounts** -- Linked social accounts (subcommands: list)
- **submissions** -- Campaign submissions (subcommands: create, get, list)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`vues --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
