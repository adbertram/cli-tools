---
name: garrul-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute Garrul operations using the `garrul` CLI tool.
  CLI interface for Garrul.
  Triggers: garrul, garrul cli
---

<objective>
Execute Garrul operations using the `garrul` CLI. All Garrul interactions should use this CLI.
</objective>

<quick_start>
The `garrul` CLI follows this pattern:
```bash
garrul <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| List audit rows, newest first | `garrul audit list` |
| Configure authentication credentials | `garrul auth login` |
| Clear stored credentials and browser sessions | `garrul auth logout` |
| Create a new profile from .env.example template | `garrul auth profiles create <NAME>` |
| Delete a profile and its data | `garrul auth profiles delete <NAME>` |
| Get details for a specific profile | `garrul auth profiles get <NAME>` |
| List all profiles and show their auth types and active state | `garrul auth profiles list` |
| Delete a profile and its data | `garrul auth profiles remove <NAME>` |
| Rename a profile, re-keying its secrets to the new profile name | `garrul auth profiles rename <OLD> <NEW>` |
| Activate a profile within its auth type | `garrul auth profiles select <NAME>` |
| Check authentication status across profiles | `garrul auth status` |
| Test authentication by verifying credentials work across profiles | `garrul auth test` |
| Remove all cached responses | `garrul cache clear` |
| Approve a comment so it is published | `garrul comments approve <COMMENT_ID>` |
| Apply one moderation action to up to 100 comments in a single request | `garrul comments bulk <ACTION> <COMMENT_IDS>` |
| Get approved-comment counts for one or more post slugs | `garrul comments counts <SLUGS>` |
| Delete a comment | `garrul comments delete <COMMENT_ID>` |
| Print the Atom feed of a post's latest approved comments | `garrul comments feed <SLUG>` |
| Get one comment with its markdown source, parent, replies, reports and audit history | `garrul comments get <COMMENT_ID>` |
| List the moderation queue, newest first | `garrul comments list` |
| Resolve a published comment's permalink to the page URL it lives on | `garrul comments permalink <COMMENT_ID>` |
| Render markdown exactly as Garrul would store it | `garrul comments preview` |
| Post a public reply as the signed-in moderator | `garrul comments reply <COMMENT_ID>` |
| Dismiss every open reader report on a comment | `garrul comments resolve-reports <COMMENT_ID>` |
| Restore a deleted or spam comment to approved | `garrul comments restore <COMMENT_ID>` |
| Mark a comment as spam | `garrul comments spam <COMMENT_ID>` |
| Read a post's public comment tree, as the widget sees it (approved comments only) | `garrul comments thread <SLUG>` |
| Show the public widget configuration the instance serves to embedding pages | `garrul instance config` |
| Check that the instance is up | `garrul instance health` |
| Show dashboard totals: comments, pending, spam, users, and per-domain counts | `garrul instance statistics` |
| Show the running Garrul version and the releases the instance knows about | `garrul instance status` |
| Show which Garrul user this CLI is signed in as | `garrul instance whoami` |
| Attach a note to a comment or a user | `garrul notes create <TARGET_KIND> <TARGET_ID>` |
| Permanently delete a note | `garrul notes delete <NOTE_ID>` |
| Irreversibly delete one batch of audit rows older than the configured window | `garrul ops audit-retention` |
| Import comments from another comment system | `garrul ops import <SOURCE> <FILE>` |
| Irreversibly clear one batch of stored IP hashes older than the configured window | `garrul ops ip-retention` |
| Re-render one batch of comments stored under an older markdown renderer | `garrul ops rerender` |
| Insert the demo `welcome` thread | `garrul ops seed-demo` |
| Show rerender backlog and the state of both retention sweeps | `garrul ops status` |
| Stop a post from accepting new comments | `garrul posts close <SLUG>` |
| Let a closed post accept comments again | `garrul posts open <SLUG>` |
| Create a saved reply | `garrul saved-replies create` |
| Permanently delete a saved reply you own | `garrul saved-replies delete <REPLY_ID>` |
| Get one saved reply | `garrul saved-replies get <REPLY_ID>` |
| List your saved replies plus every shared one | `garrul saved-replies list` |
| Replace a saved reply you own | `garrul saved-replies update <REPLY_ID>` |
| Get one runtime setting | `garrul settings get <KEY>` |
| List every runtime setting with its resolved value | `garrul settings list` |
| Clear every settings override so all values return to the instance defaults | `garrul settings reset` |
| Override runtime settings | `garrul settings update` |
| Get one active subscription | `garrul subscriptions get <SUBSCRIPTION_ID>` |
| List subscriptions, newest first | `garrul subscriptions list` |
| Email a fresh confirmation link to a subscriber who has not confirmed yet | `garrul subscriptions resend <SUBSCRIPTION_ID>` |
| Stop emailing a subscriber about a thread | `garrul subscriptions unsubscribe <SUBSCRIPTION_ID>` |
| Turn the daily operator digest on or off for your linked account | `garrul telegram digest <STATE>` |
| Issue a one-time link code | `garrul telegram link` |
| Show bot configuration and whether your account is linked | `garrul telegram status` |
| Unlink your Telegram account | `garrul telegram unlink` |
| Ban a user | `garrul users ban <USER_ID>` |
| Irreversibly erase a user's personal data (GDPR erasure request) | `garrul users erase <USER_ID>` |
| Print everything the instance holds about a user (GDPR access request) | `garrul users export <USER_ID>` |
| Get one user with role, ban state, notes, audit history and their latest 50 comments | `garrul users get <USER_ID>` |
| List users, newest first | `garrul users list` |
| Sign a user out everywhere | `garrul users revoke-sessions <USER_ID>` |
| Change a user's role | `garrul users role <USER_ID> <ROLE>` |
| Lift a ban | `garrul users unban <USER_ID>` |
| Create a webhook endpoint | `garrul webhooks create` |
| Permanently delete a webhook endpoint | `garrul webhooks delete <WEBHOOK_ID>` |
| Get one webhook endpoint | `garrul webhooks get <WEBHOOK_ID>` |
| List webhook endpoints | `garrul webhooks list` |
| Replace a webhook endpoint's url, adapter, events and enabled state | `garrul webhooks update <WEBHOOK_ID>` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `garrul` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `garrul --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **audit** -- Read the moderation audit log (subcommands: list)
- **auth** -- Manage garrul authentication (subcommands: login, logout, profiles, status, test)
- **cache** -- Manage response cache (subcommands: clear)
- **comments** -- Moderate comments and read threads (subcommands: approve, bulk, counts, delete, feed, get, list, permalink, preview, reply, resolve-reports, restore, spam, thread)
- **instance** -- Inspect the Garrul instance (subcommands: config, health, statistics, status, whoami)
- **notes** -- Write and remove internal moderator notes (subcommands: create, delete)
- **ops** -- Run operator maintenance jobs (subcommands: audit-retention, import, ip-retention, rerender, seed-demo, status)
- **posts** -- Open or close a post's comment thread (subcommands: close, open)
- **saved-replies** -- Manage saved replies (subcommands: create, delete, get, list, update)
- **settings** -- Read and change runtime settings (subcommands: get, list, reset, update)
- **subscriptions** -- Manage email subscriptions (subcommands: get, list, resend, unsubscribe)
- **telegram** -- Manage your Telegram operator link (subcommands: digest, link, status, unlink)
- **users** -- Manage commenter accounts (subcommands: ban, erase, export, get, list, revoke-sessions, role, unban)
- **webhooks** -- Manage webhook endpoints (subcommands: create, delete, get, list, update)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`garrul --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
