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
| Check authentication status across profiles | `vues auth status` |
| Test authentication by verifying credentials work across profiles | `vues auth test` |
| Get one campaign in full (CPM, max payout, budget, platforms, brief and rules, exactly as the API returns it) | `vues campaigns get <CAMPAIGN_ID>` |
| Read back the applications gating a campaign as {campaign_id, teaser, applications} (empty list: none) | `vues campaigns applications <CAMPAIGN_ID>` |
| Reach a campaign: a member gets status existing; a gated one applies to its organization once | `vues campaigns join <CAMPAIGN_ID>` |
| List the clipper campaigns the signed-in creator can see (all pages up to --limit) | `vues campaigns list` |
| Get the wallet balance (micro-dollars) and lifetime clipper stats as {balance, stats} | `vues earnings get` |
| Get one discoverable organization (description, auto_approve_applications, is_member) | `vues organizations get <ORG_ID>` |
| List organization applications and their status (pending/approved/denied, as /clipper/applications returns them) | `vues organizations applications` |
| Join an auto-approve org (status joined) or apply to a manual one (status applied); never applies twice (status existing) | `vues organizations join <ORG_ID>` |
| List discoverable organizations with is_member (--member: only joined ones, from /clipper/orgs) | `vues organizations list` |
| List linked social accounts (handle, platform, status, verification and per-account earnings) | `vues social-accounts list` |
| Submit a TikTok post once; an already-submitted URL returns status existing (never double-submits) | `vues submissions create <CAMPAIGN_ID>` |
| Get one submission by ID (Vues has no single-submission route, so this scans the list) | `vues submissions get <SUBMISSION_ID>` |
| List this account's submissions (status, tracked views, earnings, as the API returns them) | `vues submissions list` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `vues` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `vues --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Authentication">
Vues signs in only with Google or Apple (Supabase); there is no API key or
password. `vues auth login` is the standard cli-tools browser sign-in: it opens
the shared Chrome profile at vues.app/login, the person signs in (Continue with
Google, or nothing when the shared profile is already signed in) and presses
Enter; the CLI saves the Supabase session from the vues.app session cookie.
Every other command, including `auth status` and `auth test`, runs over HTTP and
refreshes the session itself, never opening a browser. Run the login through the
cli-tool skill's Browser-Session Auth Completion Surface rule. A Vues creator
account with a linked TikTok account must exist (sign up at
https://vues.app/login); the login error says so when it does not.
</principle>

<principle name="No Double Submission">
`vues submissions create` never submits the same TikTok URL twice: it checks
existing submissions for the same video id first and returns `status: existing`.
Use `--dry-run` to preview the request and `--yes` to actually submit.
</principle>

<principle name="Organizations Gate Campaigns">
A clipper sees only public campaigns plus campaigns of organizations they belong
to. `vues organizations list` shows discoverable orgs with `is_member`;
`vues organizations join ORG_ID --dry-run` previews and `--yes` sends
`POST /api/v1/organizations/{id}/apply`. It returns `joined` (auto-approve org),
`applied` (manual approval, pending) or `existing` (already a member or already
applied, nothing sent), so it never applies twice. Join only the organizations
the task names; `--yes` on a manual-approval org also affirms the Terms of
Service and that org's rules.
</principle>

<principle name="Campaign Applications Are Organization Applications">
Vues has no per-campaign application: a campaign is reachable when it is public
or its organization admitted the creator, and otherwise is gated behind that
organization. `vues campaigns applications CAMPAIGN_ID` reads back
`{campaign_id, teaser, applications}`: `teaser.outcome` is `member` or `teaser`,
and `applications` holds the creator's application rows (`id`, `status`
pending/approved/denied, `created_at`, `reviewed_at`, `organization`) for the
campaign's organization. An empty list with exit 0 means no application; exit 1
means the read failed (including teaser outcome `not_available`), never "none".
`vues campaigns join CAMPAIGN_ID` returns `status: existing` for a reachable
campaign and otherwise applies once to its organization, like
`organizations join`.
</principle>

<principle name="Command Groups">
- **account** -- Current Vues creator account (subcommands: get)
- **auth** -- Manage vues authentication (subcommands: login, logout, profiles, seed-shared-chromium-profile, status, test)
- **campaigns** -- Vues campaigns (subcommands: applications, get, join, list)
- **earnings** -- Balance and earnings (subcommands: get)
- **organizations** -- Vues organizations (a clipper only sees campaigns of orgs they belong to) (subcommands: applications, get, join, list)
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
