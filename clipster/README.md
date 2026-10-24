# Clipster CLI

## DESCRIPTION

A command-line interface for Clipster, the creator clipping platform. Read the public campaign catalog, sign in to a creator account unattended (emailed passcode read from Gmail), read campaign rules and eligibility, list linked social accounts and their recent posts, submit TikTok posts to campaigns without double-submitting, and read submissions, balances and earnings.

Use this CLI when you need scriptable, JSON-first access to Clipster from agents, automation, or terminal workflows.

## Docs

- Web app: https://www.clipster.gg/discover
- Base URL: https://api.clipster.gg (internal web-app API; no public docs)

## Installation

```bash
<cli-tools-root>/_repo/skills/cli-tool/scripts/install-cli-tool.sh --force-refresh clipster
```

After installation, the `clipster` command will be available in your terminal.

## Quick Start

```bash
# Public catalog (no login)
clipster campaigns list --limit 10 --table

# Sign in (emailed passcode is read from Gmail automatically)
clipster auth login
clipster auth status

# Creator reads
clipster account get
clipster social-accounts list
clipster campaigns get c2a1d9e0-562c-47e8-82e7-c87f8b4aafc3
clipster submissions list

# Prove a submission without sending it
clipster submissions create c2a1d9e0-562c-47e8-82e7-c87f8b4aafc3 \
  --url https://www.tiktok.com/@ata_clipper/video/7696592655307787533 --dry-run
```

## Authentication

```bash
# Sign in (first run prompts once for the account email; later runs reuse it)
clipster auth login

# Sign in again even when the saved session works
clipster auth login --force

# Live check (refreshes an expired session, never sends a passcode)
clipster auth status
clipster auth test

# Clear the saved session and email
clipster auth logout
```

Login is fully unattended and HTTP-only:

1. `POST /auth/initialize` with `{"email", "user_kind": "Creator"}` makes Clipster email a 6-digit passcode from `no-reply@clipster.gg`.
2. The CLI runs `google gmail search` / `google gmail read` (the `google` CLI, as a subprocess) and takes the code from the first passcode email that was not already in the inbox.
3. `POST /auth/finalize` with `{"auth_id", "code"}` returns an access token (7 days) and a single-use refresh token (about 100 days), saved in the active profile.

Every command refreshes the access token automatically (`POST /auth/refresh`) when it is within 5 minutes of expiry or the API answers 401. Refresh and login hold a per-profile file lock, so parallel commands never reuse a rotated refresh token. When refresh is rejected, commands sign in again through the same passcode path; `auth status` / `auth test` never do. The `google` CLI must be signed in to the Gmail inbox that receives the passcode.

## Commands

### Campaigns

```bash
# Public catalog: every API field plus web_url (no login, cached 5 minutes)
clipster campaigns list
clipster campaigns list --limit 200 --filter "type:eq:CAMPAIGN_TYPE_CLIPPING" --properties "id,name,allowed_platforms"

# Authenticated detail: guidelines, sounds, caption_requirements.required_tags,
# minimum_submission_duration_seconds, minimum_views_for_earnings, limits,
# user_earnings, requirement_changes, plus account_eligibility
clipster campaigns get c2a1d9e0-562c-47e8-82e7-c87f8b4aafc3
clipster campaigns get c2a1d9e0-562c-47e8-82e7-c87f8b4aafc3 --table
clipster campaigns get c2a1d9e0-562c-47e8-82e7-c87f8b4aafc3 --properties "name,guidelines,account_eligibility"

# Join: open campaigns need nothing (status not_required); application-only
# campaigns get an application (status applied, or existing)
clipster campaigns join 989c8f2a-51ca-4ad6-9db4-dc49685d2a85 --dry-run
clipster campaigns join 989c8f2a-51ca-4ad6-9db4-dc49685d2a85 --yes
```

### Account

```bash
# Signed-in creator: id, email, username, permissions, account_type, bio_linking_enabled
clipster account get
clipster account get --table
```

### Social Accounts

```bash
# Linked accounts: account_id, platform, username, follower_count, oauth_connected, linked_at
clipster social-accounts list
clipster social-accounts list --filter "platform:eq:SOCIAL_MEDIA_PLATFORM_TIKTOK" --table

# One linked account by account_id
clipster social-accounts get 365109a0-fc0b-458b-a49a-012edc220d71

# Recent posts Clipster sees on a linked account (post_id, post_url, published_at)
clipster social-accounts posts 365109a0-fc0b-458b-a49a-012edc220d71 --limit 5

# Bio-code linking (only when account get shows bio_linking_enabled: true)
clipster social-accounts link --platform tiktok --username ata_clipper --dry-run
clipster social-accounts link --platform tiktok --username ata_clipper --yes
clipster social-accounts verify <LINK_ID> --yes
```

`link` returns Clipster's `verification_code`, `expires_at` and `link_id`; put the code in the account bio, then run `verify`. Otherwise accounts link through TikTok OAuth in the web app (Connect Account).

### Submissions

```bash
# This account's submissions: id, campaign_id, campaign_name, status, post_url,
# view_count, eligible_view_count, potential_earnings, paid_out_earnings, created_at
clipster submissions list
clipster submissions list --campaign-id c2a1d9e0-562c-47e8-82e7-c87f8b4aafc3 --table
clipster submissions list --filter "status:eq:processing"

# One submission
clipster submissions get <SUBMISSION_ID>

# Submit once (dry run first)
clipster submissions create c2a1d9e0-562c-47e8-82e7-c87f8b4aafc3 \
  --url https://www.tiktok.com/@ata_clipper/video/7696592655307787533 --dry-run
clipster submissions create c2a1d9e0-562c-47e8-82e7-c87f8b4aafc3 \
  --url https://www.tiktok.com/@ata_clipper/video/7696592655307787533 --yes
```

`submissions create` takes a full `https://www.tiktok.com/@<user>/video/<id>` URL (short links are refused; query strings are dropped). Before sending it:

1. Looks for a submission of the same video in that campaign; if one exists it returns `status: existing` with that record and sends nothing.
2. Checks the TikTok handle is a linked account, the campaign is `CAMPAIGN_STATUS_ACTIVE`, accepts TikTok, has dashboard submissions open, has an approved application when application-only, and lists the account as eligible.
3. `--dry-run` stops here and returns the exact request. `--yes` sends `POST /campaigns/<id>/submissions-async` with `{"campaign_id", "content_list": [{"content_url"}]}` and returns `status: created` with the native submission record and Clipster's response.

`--yes` affirms the post follows the campaign's guidelines (length, sound, tags, niche); Clipster reviews submissions asynchronously.

### Earnings

```bash
# campaign_balance, referral_balance, pending_balance, lifetime_earnings,
# money_earned, total_videos, total_views, total_actual_views, total_balance
clipster earnings get

# Balance transactions
clipster earnings transactions --table
```

## Output Formats

- JSON is the default output format.
- Add `--table` / `-t` for human-readable table output.

## AI Instruction Results

Commands that reach a non-deterministic boundary may return an AI instruction result instead of normal resource data. This is JSON on stdout with `type: "ai_instruction"` and tells the calling AI agent what objective to complete, what context is available, what tools are allowed, and what success means.

The CLI must not call an LLM or include required pre-action command lists. Optional `verification_commands` and `follow_up_commands` may appear only for actions to run after the agent completes the instruction.

### JSON Output Example

```bash
clipster submissions create c2a1d9e0-562c-47e8-82e7-c87f8b4aafc3 \
  --url https://www.tiktok.com/@ata_clipper/video/7696592655307787533 --dry-run
```

```json
{
  "status": "dry_run",
  "submission": null,
  "url": "https://www.tiktok.com/@ata_clipper/video/7696592655307787533",
  "request": {
    "method": "POST",
    "url": "https://api.clipster.gg/campaigns/c2a1d9e0-562c-47e8-82e7-c87f8b4aafc3/submissions-async",
    "body": {
      "campaign_id": "c2a1d9e0-562c-47e8-82e7-c87f8b4aafc3",
      "content_list": [{"content_url": "https://www.tiktok.com/@ata_clipper/video/7696592655307787533"}]
    }
  }
}
```

### Table Output Example

```bash
clipster social-accounts list --table
```

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display data as a table |
| `--limit` | `-l` | Maximum number of results |
| `--filter` | `-f` | Filter results using `field:op:value` syntax |
| `--properties` | `-p` | Restrict output to selected fields |
| `--yes` |  | Authorize a change (join, link, verify, submit) |
| `--dry-run` |  | Run every check and print the request without sending it |
| `--version` | `-v` | Show version and exit |
| `--no-cache` |  | Bypass cached catalog reads for this execution |

## Configuration

Non-authentication configuration is stored in `~/.local/share/cli-tools/clipster/.env`. The active profile `~/.local/share/cli-tools/clipster/authentication_profiles/<profile>/.env` (mode 600) holds the session tokens written by login and refresh, and `EMAIL=secret://clipster-email`; the email itself lives in the CLI-tools secret manager:

```bash
<cli-tools-root>/_repo/_secret-manager/secrets.sh set clipster-email
```

Do not put reusable credentials in any `.env` file. `.env` files are limited to non-secret config and CLI-managed runtime auth state.

Root config variables:

```bash
# Optional: override the default API base URL
BASE_URL=https://api.clipster.gg

# Optional: response cache settings (catalog reads are cached 5 minutes regardless of CACHE_TTL)
CACHE_ENABLED=true
CACHE_TTL=3600
```

## Cache

```bash
# Clear cached read responses
clipster cache clear

# Bypass the cache for one execution
clipster --no-cache campaigns list --limit 10
```

Only the public catalog is cached; authenticated reads are always live.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error (API error, refused mutation, failed check) |
| 2 | Authentication error (no session, passcode not received) |
| 130 | User interrupted (Ctrl+C) |

## Examples

### Submit only when not already submitted

```bash
clipster submissions create "$CAMPAIGN_ID" --url "$POST_URL" --yes | jq -r '.status'   # created | existing
```

### Total views across submissions

```bash
clipster submissions list --limit 1000 | jq '[.[].view_count // 0] | add'
```

## Output Contract

All commands print JSON on stdout; messages go to stderr.

| Command | Shape |
|---------|-------|
| `campaigns list` | array of native public campaign rows plus `web_url` |
| `campaigns get` | native campaign detail object plus `web_url` and `account_eligibility` |
| `campaigns join` | `{status: not_required\|existing\|applied\|dry_run, campaign_id, application\|request}` |
| `account get` | native `user` object plus `show_oauth_modal`, `bio_linking_enabled` |
| `social-accounts list` / `posts` | arrays of native rows |
| `social-accounts get` | one native linked-account row |
| `social-accounts link` / `verify` | native response `data`, or `{status: dry_run, request}` |
| `submissions list` / `get` | native submission rows / one row |
| `submissions create` | `{status: created\|existing\|dry_run, submission, url, request?, response?}` |
| `earnings get` | `/balance` and `/users/statistics` fields merged |
| `earnings transactions` | array of native transaction rows |

## Requirements

- Python 3.11+
- The `google` CLI, signed in to the Gmail inbox that receives Clipster passcodes (login only)
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - requests

## License

MIT
