---
name: clipster-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute Clipster operations using the `clipster` CLI tool.
  Clipster clipping campaigns, creator account, linked social accounts, duplicate-safe TikTok submissions, submissions and earnings.
  Triggers: clipster, clipster cli, clipster campaigns, clipster submission, submit clip to clipster, clipster earnings, clipster balance, clipster discover
---

<objective>
Execute Clipster operations using the `clipster` CLI. All Clipster interactions should use this CLI.
</objective>

<project_overrides>
Before acting on this skill, run:

```bash
~/.agents/skills/skill-expert/scripts/load-skill-overrides.sh clipster-cli
```

Apply any printed instructions alongside this skill's own workflow: they extend it and
never repeal its limits. No output means no project override is in effect. A non-zero
exit means the project's override file is broken -- report it and stop rather than
silently running unmodified.
</project_overrides>

<quick_start>
The `clipster` CLI follows this pattern:
```bash
clipster <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List the public catalog (no login, cached 5 minutes) | `clipster campaigns list --limit 200` |
| Full campaign rules, sounds, tags, limits, your earnings and account_eligibility | `clipster campaigns get <CAMPAIGN_ID>` |
| Apply to an application-only campaign (open ones return not_required) | `clipster campaigns join <CAMPAIGN_ID> --yes` |
| Sign in unattended (passcode email read from Gmail) | `clipster auth login` |
| Check the session live (never sends a passcode) | `clipster auth status` |
| Signed-in creator identity | `clipster account get` |
| Linked accounts | `clipster social-accounts list` |
| One linked account | `clipster social-accounts get <ACCOUNT_ID>` |
| Recent posts Clipster sees on a linked account | `clipster social-accounts posts <ACCOUNT_ID>` |
| Bio-code linking (only when bio_linking_enabled) | `clipster social-accounts link --platform tiktok --username <HANDLE> --yes`, then `clipster social-accounts verify <LINK_ID> --yes` |
| Prove a submission without sending | `clipster submissions create <CAMPAIGN_ID> --url <TIKTOK_POST_URL> --dry-run` |
| Submit a TikTok post once | `clipster submissions create <CAMPAIGN_ID> --url <TIKTOK_POST_URL> --yes` |
| List submissions (status, post_url, view_count, earnings) | `clipster submissions list [--campaign-id <ID>]` |
| One submission | `clipster submissions get <SUBMISSION_ID>` |
| Balances and lifetime totals | `clipster earnings get` |
| Balance transactions | `clipster earnings transactions` |

`submissions create` returns `status` `existing` (same video already submitted to that campaign; nothing sent), `created`, or `dry_run`. It refuses before sending when the handle is not a linked TikTok account or the campaign is inactive, closed to dashboard submissions, not TikTok, application-only without an approved application, or lists the account as ineligible. `--yes` affirms the post follows the campaign guidelines.
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `clipster` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `clipster --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **account** -- Current Clipster creator account (subcommands: get)
- **auth** -- Manage clipster authentication (subcommands: login, logout, profiles, status, test)
- **cache** -- Manage response cache (subcommands: clear)
- **campaigns** -- Clipster campaigns (subcommands: get, join, list)
- **earnings** -- Balance, earnings and transactions (subcommands: get, transactions)
- **social-accounts** -- Linked social accounts (subcommands: get, link, list, posts, verify)
- **submissions** -- Campaign submissions (subcommands: create, get, list)
</principle>

<principle name="Auth and native contract">
Login is unattended: the CLI emails a passcode to the saved account email (secret `clipster-email`), reads it through the `google` CLI, and stores the session. Commands refresh automatically and sign in again by passcode when refresh fails; `auth status` only refreshes. Exit code 2 means sign-in failed (for example the `google` CLI is not signed in).
Rows are Clipster's native objects. Campaign rules live in `guidelines`, `sounds`, `caption_requirements.required_tags`, `minimum_submission_duration_seconds`, `minimum_views_for_earnings`, `max_submissions_per_day_per_social_media_account`, `niche_data`, and `geo_rules`; read them all before submitting. Submission `status` is `processing`, `eligible`, `ineligible`, `paid_out`, or `rejected`; earnings are `potential_earnings` (eligible) or `paid_out_earnings`. Open campaigns need no join; the web app links TikTok by OAuth, and bio-code linking only works when `account get` shows `bio_linking_enabled: true`.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`clipster --help` and subcommand `--help`** -- Live installed command tree and option list.
**[README.md](../../../clipster/README.md)** -- Login flow, submission checks, output contract, and examples.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
