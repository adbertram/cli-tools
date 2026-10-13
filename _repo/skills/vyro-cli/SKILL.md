---
name: vyro-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute Vyro operations using the `vyro` CLI tool.
  Vyro clipping campaigns, linked accounts, and guarded post submissions.
  Triggers: vyro, vyro cli
---

<objective>
Execute Vyro operations using the `vyro` CLI. All Vyro interactions should use this CLI.
</objective>

<project_overrides>
Before acting on this skill, run:

```bash
~/.agents/skills/skill-expert/scripts/load-skill-overrides.sh vyro-cli
```

Apply any printed instructions alongside this skill's own workflow: they extend it and
never repeal its limits. No output means no project override is in effect. A non-zero
exit means the project's override file is broken -- report it and stop rather than
silently running unmodified.
</project_overrides>

<quick_start>
The `vyro` CLI follows this pattern:
```bash
vyro <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Read the current account, including workspace and verification fields | `vyro account get` |
| Configure authentication credentials | `vyro auth login` |
| Clear stored credentials and browser sessions | `vyro auth logout` |
| Create a new profile from .env.example template | `vyro auth profiles create <NAME>` |
| Delete a profile and its data | `vyro auth profiles delete <NAME>` |
| Get details for a specific profile | `vyro auth profiles get <NAME>` |
| List all profiles and show their auth types and active state | `vyro auth profiles list` |
| Delete a profile and its data | `vyro auth profiles remove <NAME>` |
| Rename a profile, re-keying its secrets to the new profile name | `vyro auth profiles rename <OLD> <NEW>` |
| Activate a profile within its auth type | `vyro auth profiles select <NAME>` |
| Seed an empty shared Chromium profile from this CLI's default profile | `vyro auth seed-shared-chromium-profile` |
| Export scoped cookies/localStorage after live exact-account checks | `vyro auth session-export` |
| Restore, verify, close, and exclusively publish an absent profile | `vyro auth session-import` |
| Recover owned closed transfer state or finalize it after exact actor proof | `vyro auth session-import-recover` |
| Check authentication status across profiles | `vyro auth status` |
| Test authentication by verifying credentials work across profiles | `vyro auth test` |
| Read native eligibleAccounts and inviteMode without enrolling | `vyro campaigns eligibility <SLUG>` |
| Read every native campaign field, including requirements and media links | `vyro campaigns get <SLUG>` |
| List newest campaigns | `vyro campaigns list` |
| List linked accounts; limit and filters are local for this endpoint | `vyro social-accounts list` |
Mutation commands require exact `--expected-account-id`, `--expected-social-account-id`, and `--expected-username` bindings plus `--yes`. `submissions readiness SLUG` returns the current `requirements_digest`; pass it to `submissions create SLUG --url URL --requirements-digest DIGEST`. `submissions reconcile SLUG --url URL` only reads. Create returns status `created`, `existing`, or `uncertain`; reconcile returns `existing` or `not_found`. Never retry an uncertain dispatch blindly. A durable per-profile marker prevents duplicate dispatch for the same actor/campaign/post. `--yes` affirms the post follows the full campaign rules.
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `vyro` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `vyro --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **account** -- Current Vyro account (subcommands: get)
- **auth** -- Manage vyro authentication (subcommands: login, logout, profiles, seed-shared-chromium-profile, session-export, session-import, session-import-recover, status, test)
- **campaigns** -- Native campaign catalog and eligibility (subcommands: eligibility, get, list)
- **social-accounts** -- Connected social accounts (subcommands: list)
</principle>
<principle name="Read-only scope and native contract">
This CLI supports guarded campaign enrollment and submission of existing owned TikTok posts. It cannot connect social accounts or publish videos.
`campaigns get` and `campaigns eligibility` take the exact campaign slug, not its ID.
List output is an array of full native objects. Campaign rules live in `requirements`,
platforms in `targeting.platforms`, source links in `media.links`, and dollar amounts in
`budget`. Preserve all campaign instructions. Never reinterpret the data as Whop fields.
Use `social-accounts list` to prove the exact linked platform account. Successful catalog
reads do not prove publication readiness. A YouTube `requiresScopeUpgrade` notice alone
is not evidence of a blocked connection.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`vyro --help` and subcommand `--help`** -- Live installed command tree and option list.
**[README.md](../../../vyro/README.md)** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
