---
name: whop-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute Whop operations using the `whop` CLI tool.
  Read participant Content Rewards data and explicitly submit verified published clips.
  Triggers: whop, whop cli
---

<objective>
Execute Whop operations using the `whop` CLI. All Whop interactions should use this CLI.
</objective>

<project_overrides>
Before acting on this skill, run:

```bash
~/.agents/skills/skill-expert/scripts/load-skill-overrides.sh whop-cli
```

Apply any printed instructions alongside this skill's own workflow: they extend it and
never repeal its limits. No output means no project override is in effect. A non-zero
exit means the project's override file is broken -- report it and stop rather than
silently running unmodified.
</project_overrides>

<quick_start>
The `whop` CLI follows this pattern:
```bash
whop <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Get the current Whop participant account and observed account balances | `whop account get` |
| Configure authentication credentials | `whop auth login` |
| Clear stored credentials and browser sessions | `whop auth logout` |
| Create a new profile from .env.example template | `whop auth profiles create <NAME>` |
| Delete a profile and its data | `whop auth profiles delete <NAME>` |
| Get details for a specific profile | `whop auth profiles get <NAME>` |
| List all profiles and show their auth types and active state | `whop auth profiles list` |
| Delete a profile and its data | `whop auth profiles remove <NAME>` |
| Rename a profile, re-keying its secrets to the new profile name | `whop auth profiles rename <OLD> <NEW>` |
| Activate a profile within its auth type | `whop auth profiles select <NAME>` |
| Seed an empty shared Chromium profile from this CLI's default profile | `whop auth seed-shared-chromium-profile` |
| Check authentication status across profiles | `whop auth status` |
| Test authentication by verifying credentials work across profiles | `whop auth test` |
| Remove all cached responses | `whop cache clear` |
| Read existing applications; fail explicitly on partial upstream results | `whop campaigns applications` |
| Get a discovered campaign including its complete rules and payout fields | `whop campaigns get <CAMPAIGN_ID>` |
| Browse Content Rewards campaigns with server pagination | `whop campaigns list` |
| Read creator analytics for an explicit range | `whop earnings get --start <ISO_DATE> --end <ISO_DATE> --profile <NAME>` |
| Read creator payout records with server pagination | `whop earnings payouts` |
| Advance one shared resumable individual payout scan | `whop earnings sync` |
| Read allocations for an owned exact submission/campaign | `whop earnings submission <SUBMISSION_ID> <CAMPAIGN_ID>` |
| Get a linked Content Rewards account by its registry ID | `whop linked-accounts get <ACCOUNT_ID>` |
| List Content Rewards linked accounts; active bio verification is not OAuth | `whop linked-accounts list` |
| Find a submission in at most 1000 rows per verified list; no detail route is assumed | `whop submissions get <SUBMISSION_ID>` |
| Read submissions; history uses the observed deleted-record filter | `whop submissions list` |
| Verify submission readiness and current campaign requirements | `whop submissions readiness <CAMPAIGN_ID> --expected-account-id <WHOP_ID> --expected-tiktok-account-id <TIKTOK_ID>` |
| Submit one verified receipt with explicit authority and a stable UUID | `whop submissions create <REQUEST_UUID> <CAMPAIGN_ID> --publication-receipt <FILE> --requirements-digest <DIGEST> --expected-account-id <WHOP_ID> --expected-tiktok-account-id <TIKTOK_ID> --confirm` |
| Reconcile an owned submission request without resending | `whop submissions reconcile <REQUEST_UUID>` |
| Read server submission counts for clip and retainer records | `whop submissions status` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `whop` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `whop --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Participant Session and Read Boundary">
Use an explicit named profile. `whop auth login --profile <NAME>` opens CLI-owned manual Chrome and prompts for the embedded Content Rewards URL; complete Whop sign-in and open the Rewards experience before confirming. A browser storage export is not a supported profile import. Reusable secrets belong in the CLI-tools secret manager, not `.env` files.

Account output whitelists identity, balance and earnings fields and adds profile/time/provenance; session, token and verification-risk fields are excluded. Participant reads and one explicitly authorized submission action exist. Before upload and again immediately before Post, run readiness with the same actor/campaign/linked account and accepted requirements digest. Submit only the verified owning Studio receipt within the observed 30-minute window, using a stable request UUID and explicit `--confirm`. Never resend an uncertain request; use reconcile. The SDK persists this rule in a private indexed SQLite operation journal. Readback uses the supported campaign-only participant action, with bounded resumable pagination and head refresh; no truncated scan proves absence or permits resend. Honor structured SDK/provider Retry-After fields and durable cooldowns. A receipt is caller authority, not a cryptographic proof. Application-required campaigns fail explicitly. Never infer OAuth readiness from `verificationSource:bio`, or earnings from a publication, views, or CPM projection. Missing amounts remain unknown. General filters are local over the bounded fetched set. Submission get searches verified lists and can report only that its bounded inspection found no row; nonempty submission and payout records have not yet been observed. Changed action IDs/encodings fail explicitly. Individual revenue uses one private shared indexed payout ledger, separate pending/completed generations and explicit disappeared-allocation provenance. For batches, sync once then use submission revenue with `--no-refresh-payouts`; actual observation times remain unchanged. Incomplete pagination, missing currency/amounts, empty or disappeared allocations yield null, not zero. Pending, received and total cents are separate exact decimal strings. Preserve gross/net/fees/reversals and settlement dates separately; earning/exposure dates remain null until observed. Complete passes are observation intervals, not atomic snapshots. No nonempty payout has yet been verified.
</principle>

<principle name="Command Groups">
- **account** -- Read account (subcommands: get)
- **auth** -- Manage whop authentication (subcommands: login, logout, profiles, seed-shared-chromium-profile, status, test)
- **cache** -- Manage response cache (subcommands: clear)
- **campaigns** -- Read campaigns (subcommands: applications, get, list)
- **earnings** -- Read earnings (subcommands: get, payouts, submission, sync)
- **linked-accounts** -- Read linked accounts (subcommands: get, list)
- **submissions** -- Read and explicitly submit clips (subcommands: create, get, list, readiness, reconcile, status)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`whop --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
