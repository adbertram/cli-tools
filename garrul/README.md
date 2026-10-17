# Garrul CLI

## DESCRIPTION

Moderate and operate a self-hosted Garrul comment system from the command line. Review the pending queue, approve, spam, delete, restore and reply to comments, manage users, saved replies, moderator notes, webhooks, email subscriptions and runtime settings, read the audit log, and run operator maintenance jobs.

## Docs

- Garrul: https://github.com/KingPin/Garrul
- Default instance: https://comments.adamtheautomator.com (comments for https://adamtheautomator.com)

Built and verified against Garrul v2.26.1.

## How it works

Garrul has no API keys. Its only admin credential is a session cookie that an OAuth sign-in mints, so:

1. `garrul auth login` opens the CLI-owned browser profile on Garrul's GitHub sign-in. You sign in once.
2. Every command after that is a plain HTTP request to Garrul carrying that cookie. No page is driven and no browser window opens.

The session lasts 30 days and slides forward while it is used. Garrul's JSON endpoints are used wherever they exist. The admin pages that only render HTML (queue, comment, users, audit, subscriptions, settings, webhooks) are parsed. Each parser was validated against real pages and fails with a clear error if Garrul's markup changes, so you never get a silently empty result.

## Installation

```bash
~/Dropbox/GitRepos/cli-tools/_repo/skills/cli-tool/scripts/install-cli-tool.sh garrul
```

## Quick Start

```bash
garrul auth login                       # one-time GitHub sign-in in a browser window
garrul auth status                      # proves the session with a real authenticated request
garrul comments list --status pending   # the moderation queue
garrul comments approve 01K5ZZPEND0000000000000001 --yes
garrul comments reply 01K5ZZPEND0000000000000001 --body-md "Thanks, fixed." --yes
```

## Changing anything requires --yes

Every command that changes state refuses to run unless you pass `--yes`. Pass `--dry-run` instead to print the exact request without sending it. `--dry-run` needs no sign-in.

```bash
garrul comments spam 01K5ZZPEND0000000000000001
# Error: Refusing to spam comment 01K5ZZPEND0000000000000001 without --yes or --dry-run.

garrul comments spam 01K5ZZPEND0000000000000001 --dry-run    # shows method, path and body
garrul comments spam 01K5ZZPEND0000000000000001 --yes        # does it
```

These cannot be undone: `users erase`, `notes delete`, `saved-replies delete`, `webhooks delete`, `settings reset`, `ops ip-retention`, `ops audit-retention`, `ops import`, `ops seed-demo`. A deleted comment can be brought back with `comments restore`.

A failed change is never re-sent automatically. Only reads are retried.

## Commands

### Authentication

```bash
garrul auth login             # sign in with GitHub in the CLI browser profile
garrul auth login --force     # discard the saved state and sign in again
garrul auth status            # per-profile JSON; authenticated only if Garrul accepts the session
garrul auth logout
garrul auth profiles list
```

### comments

```bash
garrul comments list --status pending
garrul comments list --status spam --post-slug powershell-version --table
garrul comments list --q "free trial" --from 2026-09-01 --to 2026-09-17
garrul comments list --user-id 01K5ZZRDR00000000000000001 --host adamtheautomator.com
garrul comments list --reported                          # open reader reports, any status
garrul comments list --filter "open_reports:gt:0" --properties id,author_name,open_reports
garrul comments list --limit 50 --before "1789100006000|01K5ZZBVLK0000000000000006"

garrul comments get 01K5ZZPEND0000000000000001           # markdown source, parent, replies, reports, notes, audit
garrul comments get 01K5ZZPEND0000000000000001 --table

garrul comments approve 01K5ZZPEND0000000000000001 --yes
garrul comments spam    01K5ZZPEND0000000000000001 --reason "link farm" --yes
garrul comments delete  01K5ZZPEND0000000000000001 --yes
garrul comments restore 01K5ZZPEND0000000000000001 --yes
garrul comments bulk spam 01K5ZZBVLK0000000000000001 01K5ZZBVLK0000000000000003 --yes   # at most 100 ids

garrul comments reply 01K5ZZPEND0000000000000001 --body-md "Thanks, **fixed**." --yes
garrul comments reply 01K5ZZPEND0000000000000001 --body-md "Dupe, see above." --no-notify --yes
garrul comments reply 01K5ZZPEND0000000000000001 --body-md "Thanks!" --saved-reply-id 01M2R5BCGRKT8F2B1NHZ5N7FW6 --yes
garrul comments preview --body-md "Some *markdown*"      # render only, nothing saved
garrul comments resolve-reports 01K5ZZREPT0000000000000001 --yes

garrul comments thread powershell-version                # public tree, exact timestamps, approved only
garrul comments thread powershell-version --sort old
garrul comments counts powershell-version install-ubuntu-on-a-partition
garrul comments counts powershell-version --include votes --include reactions
garrul comments feed powershell-version                  # Atom XML
garrul comments permalink 01K5ZZAPPR0000000000000001
```

A reply publishes immediately under your own name and, unless you pass `--no-notify`, emails everyone subscribed to that thread.

`parent_id` and `body_md` exist only on a comment's own page, so they cost one extra request per row. They are fetched when you ask for every field (no `--properties`) or name either one. `--properties id,status,author_name,body_text` needs no extra requests, which matters for a scheduled job against a Cloudflare request quota.

Each listed comment includes `id`, `status`, `post_slug`, `post_title`, `post_url`, `host`, `author_name`, `author_user_id`, `author_provider`, `author_is_admin`, `author_is_banned`, `created_at`, `score_up`, `score_down`, `open_reports`, `comment_notes`, `user_notes`, `last_action`, `body_html`, `body_text`, `parent_id` and `body_md`.

### posts

```bash
garrul posts close powershell-version --yes    # stop new comments on one thread
garrul posts open  powershell-version --yes
```

### users

```bash
garrul users list --q "Adam" --table
garrul users get 01K5ZZRDR00000000000000001
garrul users ban 01K5ZZRDR00000000000000001 --reason "spam ring" --from-comment 01K5ZZSPAM0000000000000001 --yes
garrul users unban 01K5ZZRDR00000000000000001 --yes
garrul users role 01K5ZZRDR00000000000000001 mod --yes        # user, mod or admin
garrul users revoke-sessions 01K5ZZRDR00000000000000001 --yes
garrul users export 01K5ZZRDR00000000000000001 > export.json  # personal data; handle like a database dump
garrul users erase 01K5ZZRDR00000000000000001 --redact-bodies --reason "GDPR request" --yes
```

### saved-replies

```bash
garrul saved-replies list --table
garrul saved-replies get 01M2R5BCGRKT8F2B1NHZ5N7FW6
garrul saved-replies create --title "Thanks" --body-md "Thanks for the **comment**!" --scope shared --yes
garrul saved-replies update 01M2R5BCGRKT8F2B1NHZ5N7FW6 --title "Thanks" --body-md "Thank you!" --scope private --yes
garrul saved-replies delete 01M2R5BCGRKT8F2B1NHZ5N7FW6 --yes
```

Only the owner of a saved reply can change or delete it. An update must send all three fields.

### notes

```bash
garrul notes create comment 01K5ZZPEND0000000000000001 --body "Repeat poster, check the links." --yes
garrul notes create user 01K5ZZRDR00000000000000001 --body "Asked for erasure on 2026-09-17." --yes
garrul notes delete 01K5ZZNOTE0000000000000001 --yes
```

Read notes, with their ids, in the `notes` field of `comments get` and `users get`.

### webhooks

```bash
garrul webhooks list --table
garrul webhooks get 01M2R5BCGA193VTCQWK6921ETC
printf '%s' "$SIGNING_SECRET" | garrul webhooks create --url https://example.com/hooks/garrul --adapter generic --event comment.posted --event comment.reported --secret-stdin --yes
garrul webhooks update 01M2R5BCGA193VTCQWK6921ETC --url https://example.com/hooks/garrul --adapter generic --event comment.posted --disabled --yes
garrul webhooks update 01M2R5BCGA193VTCQWK6921ETC --url https://example.com/hooks/garrul --adapter generic --clear-secret --yes
garrul webhooks delete 01M2R5BCGA193VTCQWK6921ETC --yes
```

Adapters: `generic`, `slack`, `discord`, `telegram`. Events: `comment.posted`, `comment.edited`, `comment.deleted`, `comment.approved`, `comment.spam`, `comment.reported`. No `--event` means every event.

Garrul treats an update as a full replacement of url, adapter, events and enabled state, so `update` asks for them every time. The signing secret is kept unless you pass `--secret-stdin` or `--clear-secret`. It is read from stdin so it stays out of your shell history, and Garrul never returns it.

### subscriptions

```bash
garrul subscriptions list --post-slug powershell-version --table
garrul subscriptions list --q "@example.com" --confirmed no
garrul subscriptions list --unsubscribed yes
garrul subscriptions get 01K5ZZSUBS0000000000000002
garrul subscriptions unsubscribe 01K5ZZSUBS0000000000000002 --reason "asked by email" --yes
garrul subscriptions resend 01K5ZZSUBS0000000000000002 --yes    # new confirmation email
```

### audit

```bash
garrul audit list --limit 20 --table
garrul audit list --action approve --from 2026-09-01
garrul audit list --target-kind user --target-id 01K5ZZRDR00000000000000001
garrul audit list --admin-id 01K5ZZADMN0000000000000001 --filter "action:startswith:bulk"
```

An `--action` or `--target-kind` that the instance does not know is an error, and so is a `--from`, `--to` or `--before` that Garrul could not parse. Garrul itself would quietly ignore each of these and return unfiltered or first-page rows.

### settings

```bash
garrul settings list --table
garrul settings get comments_per_page
garrul settings update --flag comments_enabled=false --yes
garrul settings update --number comments_per_page=25 --string default_sort=old --text security_contact=security@example.com --yes
garrul settings reset --yes            # clears every override
```

Garrul itself silently ignores an unknown key and silently clamps an out-of-range number. This CLI does not: an unknown key, or a key under the wrong group, is rejected before anything is changed, and a value Garrul stored differently from what you sent is reported as an error.

`settings list` shows which group each key belongs to: `flags` use `--flag`, `numbers` use `--number`, `strings` use `--string`, `texts` use `--text`.

### telegram

```bash
garrul telegram status
garrul telegram link --yes             # prints a one-time code; send "/start <code>" to the bot within 10 minutes
garrul telegram digest on --yes
garrul telegram unlink --yes
```

### ops

```bash
garrul ops status                                   # rerender backlog and retention state
garrul ops rerender --batch 100 --yes
garrul ops rerender --batch 100 --cursor-created-at 1789100006000 --cursor-id 01K5ZZBVLK0000000000000006 --yes
garrul ops ip-retention --yes                       # destroys stored IP hashes past the configured window
garrul ops audit-retention --yes                    # deletes audit rows past the configured window
garrul ops import disqus export.xml.gz --plan --yes # ask Garrul for the plan only, nothing inserted
garrul ops import disqus export.xml.gz --include-spam --yes
garrul ops import comentario export.json --domain example.com --yes
garrul ops import isso dump.json --site https://example.com --yes
garrul ops seed-demo --yes                          # Garrul allows this only on an ENV=dev instance
```

Import sources: `disqus`, `remark42`, `comentario`, `isso`, `cusdis`. Re-uploading the same file inserts nothing new. Note the two different previews: `--dry-run` prints the request and sends nothing, while `--plan` sends the file and asks Garrul to report what it would import.

### instance

```bash
garrul instance health         # no sign-in needed
garrul instance config         # public widget configuration
garrul instance status         # running Garrul version and known releases
garrul instance statistics     # totals: comments, pending, spam, users, per-domain counts
garrul instance whoami         # which Garrul user this CLI is signed in as
```

### cache

```bash
garrul cache clear
```

## Output Formats

JSON on stdout by default. Add `--table` (`-t`) for a table. Messages, paging hints and errors go to stderr, so stdout is always safe to pipe.

```bash
garrul comments list --status pending | jq -r '.[] | "\(.id)\t\(.author_name)\t\(.body_text)"'
garrul comments list --status pending --properties id,author_name,created_at --table
```

## Options Reference

| Option | Short | Where | Meaning |
|--------|-------|-------|---------|
| `--table` | `-t` | every `list` and `get` | Table instead of JSON |
| `--limit` | `-l` | every `list` | Maximum rows (default 100) |
| `--filter` | `-f` | every `list` | `field:op:value`, for example `status:eq:spam` |
| `--properties` | `-p` | every `list` and `get` | Comma-separated fields to keep |
| `--before` | | paged lists | Cursor for the next page |
| `--yes` | `-y` | every change | Apply the change |
| `--dry-run` | | every change | Print the request, send nothing |
| `--profile` | | every command | Auth profile name |

### Filtering and paging

Garrul applies `--status`, `--q`, `--post-slug`, `--user-id`, `--from`, `--to`, `--host`, `--reported` and the audit and subscription options itself. A single `--filter` whose every clause is `eq` on `status`, `post_slug`, `author_user_id`, `host`, `action` or `target_kind` is also sent to Garrul as a query parameter, and that page is already exact.

Anything a `--filter` cannot translate that way (a different operator, a different field, or more than one `--filter` flag, since separate flags OR together and a single query string cannot express that) is applied by this CLI after fetching. In that case pagination itself keeps requesting pages until `--limit` matching rows have been collected or Garrul's own pages run out, so `--limit` always bounds the filtered result, not just the raw page window. A scan that still has not found `--limit` matches after 400 pages (20,000 rows) fails with a clear error instead of paging forever or silently returning fewer rows than actually exist; narrow `--filter` or lower `--limit` when that happens.

A `--filter` on a field that does not exist is an error, not an empty result. An unknown `--properties` field comes back `null`, as in every cli-tools CLI, with a warning on stderr naming the valid fields. Filters are applied before `--limit` cuts the result to size, and that is now true of the total matching count, not just of whichever rows happened to be fetched already.

Garrul serves 50 rows per page and only issues a cursor at a page boundary. When more rows exist, a hint on stderr gives the `--before` value, or tells you to raise `--limit` when the rows you asked for end mid-page.

## Configuration

Non-secret settings live in `~/.local/share/cli-tools/garrul/.env`:

```bash
BASE_URL=https://comments.adamtheautomator.com   # any Garrul instance, including http://127.0.0.1:8787 from wrangler dev
EMBED_ORIGIN=https://adamtheautomator.com        # a site listed in the instance's ALLOWED_ORIGINS
```

`EMBED_ORIGIN` is needed because Garrul rejects any request to its public `/api/` routes whose `Origin` is not a site allowed to embed the widget. `comments thread`, `comments counts`, `instance health`, `instance config` and `instance whoami` use it.

The session itself lives in the CLI browser profile under `~/.local/share/cli-tools/`. This CLI has no API key, password or token to store. If a future Garrul release adds reusable credentials, they belong in the CLI-tools secret manager (`_repo/_secret-manager/secrets.sh`), never in a `.env` file.

## Known limits of Garrul's admin surface

These come from Garrul v2.26.1 itself, not from this CLI:

- Timestamps from admin pages are minute precision (`2026-09-10T00:31Z`). `comments thread` returns exact millisecond timestamps for approved comments.
- Audit rows have no id, so there is no `audit get`. A full `target_id` is present only for comment and user targets; other kinds expose the first 8 characters as `target_id_prefix`.
- A subscription's id is only rendered while it is still subscribed. Unsubscribed rows list with `"id": null` and cannot be fetched with `subscriptions get`.
- `comments bulk` returns `HTTP 404: not_found` on v2.26.1. Garrul registers the single-comment route before the bulk route, so the server treats the word "bulk" as a comment id. The command sends the documented request and will work once Garrul fixes the route order. Until then, moderate comments one at a time.
- `comments thread --before` takes Garrul's opaque `next_cursor`. Its format depends on the sort, so the CLI cannot validate it, and Garrul answers a cursor it cannot read with the first page.
- `--table` output replaces control characters in comment text with visible escapes such as `\x1b`, so a hostile comment cannot drive your terminal. JSON output escapes them as JSON does.
- API keys are a design document in Garrul, not a feature. Browser sign-in is the only way in.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | Error: an invalid value, a refused change, a Garrul error, or changed page markup |
| 2 | Not signed in, or the signed-in account lacks the role. Also a malformed command line (unknown option, missing argument, wrong type), which the option parser rejects before the command runs |
| 130 | Interrupted |

## Examples

### Work the pending queue

```bash
garrul comments list --status pending --table
garrul comments get 01K5ZZPEND0000000000000001
garrul comments approve 01K5ZZPEND0000000000000001 --yes
garrul comments reply 01K5ZZPEND0000000000000001 --body-md "Good catch, the post is updated." --yes
```

### Handle a spammer

```bash
garrul comments list --user-id 01K5ZZRDR00000000000000001 --properties id,status,body_text
garrul comments spam 01K5ZZSPAM0000000000000001 --yes
garrul users ban 01K5ZZRDR00000000000000001 --from-comment 01K5ZZSPAM0000000000000001 --yes
```

### Answer a GDPR request

```bash
garrul users export 01K5ZZRDR00000000000000001 > subject-access.json
garrul users erase 01K5ZZRDR00000000000000001 --reason "erasure request" --dry-run
garrul users erase 01K5ZZRDR00000000000000001 --reason "erasure request" --yes
```

## Requirements

- Python 3.11+
- A Garrul account with the `admin` role (or `mod` for moderation-only commands)

## Tests

```bash
uv run --project ~/Dropbox/GitRepos/cli-tools/garrul pytest ~/Dropbox/GitRepos/cli-tools/garrul/tests
```

`tests/fixtures/` holds real admin pages captured from a local Garrul instance seeded with test data only.

## License

Apache-2.0, the same as Garrul.
