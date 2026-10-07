# TikTok CLI

## DESCRIPTION

The `tiktok` CLI provides a TikTok transcript downloader using yt-dlp, commands to list and look up your saved (favorited) TikTok videos, and commands to publish, check, list, and delete your own TikTok videos.

Use it when you need scriptable reads, exports, or evidence collection without opening the service UI.

## Installation

```bash
cd tiktok
pip install -e .
```

After installation, the `tiktok` command will be available in your terminal.

## Prerequisites

This CLI requires `yt-dlp` to be installed:

```bash
brew install yt-dlp
```

## Quick Start

```bash
# Download transcript for a single video
tiktok transcripts download "https://www.tiktok.com/@user/video/1234567890"

# Download multiple transcripts to specific folder
tiktok transcripts download -o ./transcripts "https://www.tiktok.com/@user/video/111" "https://www.tiktok.com/@user/video/222"

# Download with table output
tiktok transcripts download --table "https://www.tiktok.com/@user/video/1234567890"

# Get VTT format instead of SRT
tiktok transcripts download --format vtt "https://www.tiktok.com/@user/video/1234567890"

# Prefer manual subtitles if available
tiktok transcripts download --manual-sub "https://www.tiktok.com/@user/video/1234567890"

# Check wrapper readiness and profile state
tiktok auth status
tiktok auth test

# List your saved (favorited) TikTok videos (requires a logged-in browser session)
tiktok auth login --credential-type browser_session
tiktok favorites list --table

# Look up one saved video's details by id or URL (no login required)
tiktok favorites get "https://www.tiktok.com/@user/video/1234567890"
```

## Own-account Studio readback

Studio reads use the named browser session and verify the requested handle and
optional exact numeric account ID before reading. The public profile mode stays
available without `--studio`; access errors never become empty profiles.

```bash
tiktok videos list --profile clipper --username ata_clipper --studio --expected-account-id 7692213003349443597 --limit 10
tiktok videos get 7692252984792681742 --profile clipper --username ata_clipper --studio --expected-account-id 7692213003349443597
tiktok videos metrics 7692252984792681742 --profile clipper --username ata_clipper --expected-account-id 7692213003349443597
```

The observed Studio Manage content feed supplies cumulative views, likes,
comments, shares, and favorites. Missing measurements remain `null`. Results
include local `observed_at`, optional server `server_timestamp_ms`, verified
owner ID, profile, and endpoint provenance. Richer analytics and earned revenue
are separate; this command does not estimate them from counts.

`--studio` lists by the live Views sorting control. Requests and pagination
reuse the browser's own read request with signing/session values kept in page
memory. Malformed, limited, cyclic, or inaccessible reads fail explicitly.
A complete terminal feed can report `studio_video_not_found`; a bounded scan
reports `studio_lookup_inconclusive` instead of asserting absence. The live
account currently has one post; multiple-page behavior is covered by fixtures.
These reads do not establish whether an attempted upload created a new post.

## Account check (post restrictions)

`account check` reports, for each recent post, whether TikTok restricted it,
the stated reason, and the appeal state. It is read-only: it never appeals,
answers the feedback prompt, or changes anything.

```bash
tiktok account check --profile clipper --username ata_clipper --expected-account-id 7692213003349443597
tiktok account check --profile clipper --username ata_clipper --expected-account-id 7692213003349443597 --limit 5 --table
# Also check uploads Studio accepted that may no longer exist
tiktok account check --profile clipper --username ata_clipper --expected-account-id 7692213003349443597 --video-id 7693639883012705549
```

| Option | Description |
|--------|-------------|
| `--username`, `-u` | Exact session owner handle (required) |
| `--expected-account-id` | Fail unless the session's numeric account ID matches |
| `--limit`, `-l` | Most recent posts to check (default 20, max 1000) |
| `--video-id` | Extra post ID to check, repeatable (max 100) |
| `--table`, `-t` | Show posts as a table |

Posts come from the Studio content feed; each one's penalty comes from
`GET /mod/v1/getPenaltyDetails/?vid=<id>`, the call Studio's own post analytics
page makes. Per post: `id`, `url`, `caption`, `posted_at`, `status`,
`visibility`, `in_review`, `in_studio_feed`, `eligibility` (`restricted`,
`no_penalty`, or `null`), `reasons` (`code` and TikTok's `title`),
`appeal_status` (`can_submit`, `cannot_submit`, `no_penalty`, `reviewing`,
`succeeded`, `failed`, `timeout`), `penalty_type` (`NR`: not eligible for the
For You feed and restricted in search; `NFF`: not eligible for the For You
feed), `penalized_at`, `penalty_issuer`, and `penalty_error`.

Anything TikTok did not return stays `null`. A penalty read that fails (TikTok
answers `status_code 4` for posts that no longer exist) leaves `eligibility`
`null` with the reason in `penalty_error`. A `--video-id` absent from the
complete feed has `in_studio_feed: false`; if the scan stopped early it is
`null`. `account.standing` is always `null`: TikTok's website has no Account
check page, so account-level standing is only visible in the phone app. Reason
code 10 ("Reproduced account") is the one account-level penalty that shows up
here, on the posts it affects.

## Pre-post check (Content check lite)

`studio check` asks TikTok Studio what it thinks of a local MP4 before anything
is posted. It uploads the file as a private draft, waits for the two checks
Studio runs by itself after an upload, returns their verdicts, and removes that
draft. It never clicks Post, never flips a check switch, and never starts a
check itself.

```bash
tiktok studio check clip.mp4 --profile clipper --username ata_clipper --account-id 7692213003349443597
tiktok studio check clip.mp4 --profile clipper --username ata_clipper --account-id 7692213003349443597 --timeout 300 --table
```

| Option | Description |
|--------|-------------|
| `--username` | Exact session owner handle (required) |
| `--account-id` | Exact numeric session owner ID (required) |
| `--timeout` | Seconds to wait for Studio's checks, 30 to 900 (default 900, Studio's own polling window) |
| `--table`, `-t` | Show status, verdict, issues, music verdict, and seconds as a table |

The result's `status` is `completed`, `not_finished` (no answer within
`--timeout`), `check_failed`, `limit_reached` (TikTok's daily check limit),
`unavailable`, `switch_off` (the account's automatic content check is off), or
`not_offered` (Studio showed no content check). `verdict` is `pass` or
`restricted` only when `status` is `completed`; otherwise it is `null`. Each
entry in `issues` carries TikTok's `code`, `type`, `result_code`, `text`, and
flagged `segments` in milliseconds. `content_check` holds the raw
`check_status`, `results`, check and video IDs, and the message Studio showed
(`ui_state`, `ui_text`). `music_copyright.verdict` is `no_issue`,
`copyright_violated`, or `null` when that check did not finish. `timings`,
`provenance`, and `draft` (`posted: false`, `removed: true`) complete it.
Anything Studio did not return stays `null`.

Studio's content check has one model, "unoriginal", with two results: pass or
not recommended. A not-recommended result is shown by Studio as "Content may be
restricted" with the reason "Unoriginal, low-quality, and QR code content", the
same reason `account check` reports on a restricted post. A pass is not a
guarantee: Studio's own message says the video can still be actioned later.

Observed on @ata_clipper (2026-10-06): Studio creates the check with
`POST /tiktok/v1/creator/content/check/create` (`{"video_id", "tasks": [0]}`),
polls `GET /tiktok/v1/creator/content/check/` every 10 seconds, and reads music
from `GET /tiktok/copyright/music/check/v1/`. The same clip passed five times in
about 22 seconds each. Another clip's check never finished in three tries (one
left running for 20 minutes), so `not_finished` is a real outcome. Only pass, checking, and a failed music
check were captured live; the restricted shape follows Studio's own code.

Every run uses one of the account's daily checks and leaves the uploaded video
on TikTok's servers unposted. The run is journaled (`studio status <request_id>`
shows `kind: content_check` and `draft_removed`). Removal closes the run's own
editor with Studio's Discard, deletes only its exact temporary draft row (or
confirms Studio already dropped it), and fails if any other draft changed. If the process is killed mid-check its draft
stays behind: the next time Studio's upload page loads, Studio offers that draft
to continue and drops any other unlocked draft, so do not kill a running check.

## Studio publishing

Studio publishing uses an explicit named browser profile and a version 1 JSON
policy. Required fields are `schema_version`, `profile`, `account_id` (string),
`username`, `caption`, `audience="Everyone"`, `timing="now"`,
`disclosure="branded_content"`, and `music_rights_confirmed=true`. Supply music
rights confirmation only after checking the rights for the actual asset's audio.
Unknown fields and omitted fields are rejected; the caption is used verbatim.
Policy JSON must be UTF-8 and at most 64 KiB.

```bash
tiktok studio prepare clip.mp4 --policy policy.json --request-id UUID --profile clipper
tiktok studio status UUID --profile clipper
tiktok studio publish UUID --yes --profile clipper
tiktok studio reconcile UUID --profile clipper
```

`prepare` stages the exact MP4 bytes under the profile's private runtime directory,
then verifies the account, uploaded media, caption, Everyone, Now, branded content,
and observed music consent. Files must be at most 30 GB and leave 1 GiB free after
staging. The bounded copy rechecks free space while writing and removes only its
owned temporary file on failure. Staged files must remain regular files with the
bound size, hash, and file identity; symlinks are refused. The request UUID binds the asset hash, policy, and actor. Repeating a
matching preparation returns its existing journal entry; changing that binding
is refused. `status` reads only the local operation journal.

The SDK supports `StudioPublisher(config, browser=None)`, `prepare(file, policy,
request_id)`, `publish(request_id, *, before_public_action)`, `status(request_id)`,
`reconcile(request_id)`, and `close()`. Keep one publisher instance for
prepare→publish so its owned editor stays open. The mandatory trusted Python
callback receives the request, asset hash, policy digest, actor, draft ID, and
editor project ID immediately before Post. An unattended coordinator must inspect
its own authoritative reservation and control state in that callback. It may
return `{"dispatch_deadline": epoch_seconds}` from its original lease and policy
cutoff. The SDK checks that deadline before click and in the native pre-send
guard; it never renews authorization. Bounded CDP request/response capture
survives renderer navigation and journals exact binding IDs, hashes, and the
native Post response body (first 64 KiB) for diagnosis.

Studio prepare, publish, and `studio check` always run in visible (headed)
Chrome, whatever `HEADLESS` says; a standalone `reconcile` and other reads stay
headless. Before
Post, the publisher journals what the page can read about the browser
(`browser_environment`: user agent, `navigator.webdriver`, screen size) and
refuses Post, leaving the request prepared, when the user agent says headless or
`navigator.webdriver` is true. Both posts made from headless Chrome
(`HeadlessChrome/155`, 800x600 screen) were accepted with an item ID and then
never existed, not even in the owner's Studio list (measured 2026-10-06).
The host must have a logged-in desktop session for headed Chrome, and the
caller must run in that user's session: on macOS a LaunchDaemon (n8n on
adam-server) cannot open it directly and must run the command through
`ssh localhost`.

A native request guard permits only the exact creation ID, uploaded video ID,
and one batch-zero request. The response allocates a separate `post_project_id`.
Accepted projects are persisted before polling, even when the response has no
item ID yet. `reconcile` reads that exact project through Studio project status,
then verifies its exact task item ID through the existing own-post Studio reader.
Pending, failed, unknown, and malformed results never trigger another Post. A
successful result requires the exact returned item ID and verified Studio readback. Verified publication removes only the operation's hash-matched
staged media, retaining its journal and receipt.

This account's local drafts can become unavailable after a normal browser exit.
Before any public dispatch, recovery can rebuild a missing private draft or
atomically remove only its exact journal-owned orphan, then reprepare the same
bytes and policy under the same UUID. Recovery checks native heartbeat state,
retains an audit, and preserves unknown drafts. Session transfer moves browser
authentication; local IndexedDB drafts and staged media stay on their source host.

Caption clearing uses the existing framework-input helper's native select-all
command, then whole-string native insertion to avoid TikTok's per-key hashtag
autocomplete. Saved caption and controls are checked after rendering and autosave.
Shared native-input and close repairs are tracked in agent-issues #1156 and #1154.

## Commands

### Auth

```bash
# Show profile state
tiktok auth status
tiktok auth profiles list
tiktok auth profiles get default

# Verify yt-dlp is installed and callable
tiktok auth test
```

TikTok has two profile types: `browser_session` (favorites list and the
`videos list/get/delete` commands) and `custom` (Content Posting API publish and
status; see below). `auth status` checks a browser session against TikTok's own
account endpoint, so an expired session reports `authenticated: false`.

For a visible login or recovery from an MFA/CAPTCHA step, explicitly opt into
manual login in an isolated named browser profile:

```bash
tiktok auth login --profile clipping --credential-type browser_session --manual
tiktok auth status --profile clipping
```

Finish login in the opened Chrome window, then press Enter in the terminal.
Without an interactive terminal, close that window within five minutes instead.
The shared engine closes only that profile's login browser, verifies live
authentication, and saves the same profile's session. Manual mode never reads or
submits stored login credentials. It requires an explicit non-default profile
and `browser_session` credential type; ordinary login behavior is unchanged.

Read the current account identity without exporting passport contact/session
fields. IDs stay strings so large TikTok account IDs keep their exact digits:

```bash
tiktok account get --profile clipping
tiktok account get --profile clipping --expected-username YOUR_HANDLE
```

Use `--expected-username` and/or `--expected-account-id` for an explicit account
guard. A mismatched, expired, or malformed identity fails without returning data.

### Transcripts Download

```bash
# Download transcript for single video (SRT format, English, auto-generated)
tiktok transcripts download "VIDEO_URL"

# Download multiple transcripts
tiktok transcripts download "URL1" "URL2" "URL3"

# Specify output directory
tiktok transcripts download -o /path/to/output "VIDEO_URL"

# Change subtitle format (srt, vtt, txt)
tiktok transcripts download --format vtt "VIDEO_URL"
tiktok transcripts download --format txt "VIDEO_URL"

# Change language
tiktok transcripts download --lang es "VIDEO_URL"

# Prefer manual subtitles over auto-generated
tiktok transcripts download --manual-sub "VIDEO_URL"

# Display results as table
tiktok transcripts download --table "VIDEO_URL"
```

### Favorites

`favorites list` reads your saved (favorited) TikTok videos — the bookmark
list, not "Liked" videos. It calls TikTok's own private favorites feed inside
an authenticated browser session, so it needs a logged-in `browser_session`
credential first. `favorites get` looks up one video's public details by id
or URL and needs no login (it reuses the same `yt-dlp` path as `transcripts
download`).

```bash
# One-time: log in with a real browser session (opens a browser for Adam to log in)
tiktok auth login --credential-type browser_session

# List all saved videos (JSON)
tiktok favorites list

# List as a table, limit results, filter, and select fields
tiktok favorites list --table --limit 25
tiktok favorites list --filter "author:eq:someuser"
tiktok favorites list --properties id,url,caption

# Look up one saved video's id, URL, caption, author (no login required)
tiktok favorites get "https://www.tiktok.com/@user/video/1234567890"
tiktok favorites get 1234567890
tiktok favorites get 1234567890 --table
```

Each record returned by `favorites list`/`favorites get` has this shape:

```json
{
  "id": "1234567890",
  "url": "https://www.tiktok.com/@user/video/1234567890",
  "caption": "video description text",
  "author": "user",
  "saved_at": null
}
```

`saved_at` is populated only if TikTok's API happens to include a
favorited/bookmarked-at timestamp on a given item; TikTok does not document
one, so it is commonly `null`.

## Options Reference

### Download Command Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--output-dir` | `-o` | Output directory for transcripts | Current directory (`.`) |
| `--format` | `-f` | Subtitle format: `srt`, `vtt`, `txt` | `srt` |
| `--lang` | `-l` | Subtitle language code | `en` |
| `--auto-sub/--no-auto-sub` | | Download auto-generated subtitles | `--auto-sub` |
| `--manual-sub` | | Prefer manual subtitles over auto-generated | `False` |
| `--table` | `-t` | Display results as a table | `False` |
| `--version` | `-v` | Show version and exit | |

### Favorites List Command Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--table` | `-t` | Display results as a table | `False` |
| `--limit` | `-l` | Maximum number of results | `100` |
| `--filter` | `-f` | Filter: `field:op:value` (repeatable) | None |
| `--properties` | `-p` | Comma-separated fields to display | None |

### Favorites Get Command Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--table` | `-t` | Display result as a table | `False` |
| `--properties` | `-p` | Comma-separated fields to display | None |

## Output Formats

### Table Output

```bash
tiktok transcripts download --table "VIDEO_URL"
```

Displays results in a formatted table with:
- Title
- Duration
- Filename
- File size
- Format

### List Output (default)

Displays detailed information for each transcript:
- Video title
- Duration
- Full file path
- File size
- Format and language

## Examples

### Download Multiple Transcripts

```bash
tiktok transcripts download \
  "https://www.tiktok.com/@user/video/111" \
  "https://www.tiktok.com/@user/video/222" \
  -o ~/Documents/transcripts
```

### Get VTT Format for Spanish Subtitles

```bash
tiktok transcripts download \
  --format vtt \
  --lang es \
  "https://www.tiktok.com/@user/video/1234567890"
```

### Download Text Format Only

```bash
tiktok transcripts download \
  --format txt \
  -o ./text-transcripts \
  "https://www.tiktok.com/@user/video/1234567890"
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error (video not found, no subtitles available, etc.) |
| 130 | User interrupted (Ctrl+C) |

## Requirements

- Python 3.9+
- yt-dlp (install via Homebrew: `brew install yt-dlp`)
- Dependencies (installed automatically):
  - typer
  - python-dotenv

## Supported Subtitle Formats

- **SRT** (`.srt`) - SubRip format (default)
- **VTT** (`.vtt`) - WebVTT format
- **TXT** (`.txt`) - Plain text format

## Language Codes

Use standard ISO 639-1 language codes:
- `en` - English
- `es` - Spanish
- `fr` - French
- `de` - German
- `ja` - Japanese
- `ko` - Korean
- `zh` - Chinese

For full list of supported languages, check yt-dlp documentation.

## License

MIT


## Content Posting API

Use a separate custom auth profile for Direct Post. Existing favorites-list browser
profiles remain independent. Transcript downloads and favorites get need no CLI auth.

```bash
tiktok auth profiles create posting --auth-type custom
tiktok auth login --profile posting --credential-type custom

tiktok videos publish short.mp4 --title "Caption" --privacy SELF_ONLY --profile posting
tiktok videos status PUBLISH_ID --profile posting
```

The Direct Post API requires video.publish. TikTok can restrict unaudited apps to
private visibility until the app passes TikTok review. `videos publish` returns the
`publish_id`, upload status, and the posting account's `creator_username`.

## Listing and Deleting Videos

TikTok's official APIs cannot delete videos (no scope grants it), and a private
(`SELF_ONLY`) Direct Post never returns a post id. `videos list`, `videos get`, and
`videos delete` therefore use TikTok's own web API inside the logged-in
`browser_session` profile, the same way the favorites commands do.

```bash
tiktok auth login --credential-type browser_session

# List a profile's posts (your own private posts appear only for your own session)
tiktok videos list --username yourhandle
tiktok videos list --username yourhandle --table --limit 10
tiktok videos list --username yourhandle --filter "caption:contains:launch" --properties id,caption

# Get one post by id
tiktok videos get 7300000000000000001 --username yourhandle
tiktok videos get 7300000000000000001 --username yourhandle --table

# Permanently delete one of your videos (refuses to run without --yes)
tiktok videos delete 7300000000000000001 --yes
```

`videos list`/`videos get` records have this shape:

```json
{
  "id": "7300000000000000001",
  "url": "https://www.tiktok.com/@yourhandle/video/7300000000000000001",
  "caption": "video description text",
  "author": "yourhandle",
  "created_at": 1700000000
}
```

`videos delete` prints `{"video_id": "<id>", "deleted": true}`.

### Videos Command Options

| Command | Option | Short | Description |
|---------|--------|-------|-------------|
| `list`, `get` | `--username` | `-u` | Profile whose posts to read (required) |
| `list` | `--table` | `-t` | Display results as a table |
| `list` | `--limit` | `-l` | Maximum number of results (default `100`) |
| `list` | `--filter` | `-f` | Filter: `field:op:value` (repeatable) |
| `list`, `get` | `--properties` | `-p` | Comma-separated fields to display |
| `get` | `--table` | `-t` | Display result as a table |
| `delete` | `--yes` | `-y` | Confirm permanent deletion (required) |

## Live E2E Test

`tests/test_videos_e2e.py` publishes a generated 5-second private clip, polls
`videos status` until `PUBLISH_COMPLETE`, finds the post id with `videos list`,
and always deletes it (and proves it is gone) in fixture teardown, pass or fail.
It is skipped unless `TIKTOK_E2E=1` and needs `ffmpeg`, an authenticated custom
API profile (`TIKTOK_E2E_API_PROFILE`, default `posting`), and an authenticated
browser profile (`TIKTOK_E2E_BROWSER_PROFILE`, default `default`). It checks the
browser profile can list videos before publishing anything.

```bash
TIKTOK_E2E=1 uv run --project tiktok --with pytest python -m pytest tiktok/tests/test_videos_e2e.py -v -s
```

## Portable named browser sessions

```bash
tiktok auth session-export --profile clipper --expected-account-id EXPECTED_NUMERIC_ID --expected-username EXPECTED_HANDLE --output PRIVATE_RUNTIME_FILE
tiktok auth session-import --profile clipper --expected-account-id EXPECTED_NUMERIC_ID --expected-username EXPECTED_HANDLE --stdin < PRIVATE_RUNTIME_FILE
```

Export verifies exact live identity before and after collecting cookies scoped to tiktok.com, www.tiktok.com, and tiktokw.us plus localStorage from exactly https://www.tiktok.com. It accepts only a named browser_session profile. Keep bundles private inside CLI runtime storage; never place them in a repository.

Import requires an absent named destination on macOS. It restores into private inactive staging, reopens for an exact live identity check, publishes exclusively, and verifies the final profile again. It never activates a profile or replaces an existing destination. Challenges and failures retain private recovery state; after the browser closes, `tiktok auth session-import-recover --profile clipper` recovers only importer-owned state. Raw Chrome profiles, keychains, reusable credentials, IndexedDB, sessionStorage, service workers, and hardware-bound state are not transferred.

## Batch Studio inventory

Read a set of exact owned publication IDs through one shared native Studio feed
scan, instead of scanning independently for each post:

```bash
printf '["7692252984792681742"]\n' > owned-post-ids.json
tiktok studio inventory owned-post-ids.json --profile clipper --username ata_clipper --account-id 7692213003349443597
```

The SDK method is `get_studio_videos(username, video_ids, *, expected_account_id,
continuation=None, max_pages=20)`. Inputs allow 1–1000 unique positive string IDs
and at most 64 KiB of JSON. A call reads at most 20 pages of 50 items; responses
stream within an 8 MB byte limit. The caller retains records and the returned
`continuation`, passing it to the next call (or a regular JSON file with the CLI's
`--continuation`). Resume needs at least two pages, including a fresh head read.
There is no total history limit of 1000 items.

A continuation binds the exact actor/profile, requested ID set, and stable
observed request semantics: native `post_time` descending order, no conditions,
and `is_recent_posts=false`. Fresh signing material stays in browser memory and
does not invalidate continuation. Changed bindings or malformed pagination fail
explicitly. The first successful native capture is frozen for that invocation.

`records` contains only matched posts actually measured during this call. The
caller keeps earlier records with their original `observed_at` and
`server_timestamp_ms`; continuation does not refresh them. `requested_complete`
means every requested ID has been observed during this pass, including prior
calls, rather than every ID being freshly measured now. `provider_end` means
this observed pass ended. `unresolved_ids` remain unknown, including at provider
end; they never imply deletion or nonexistence. Start a new pass without a
continuation to revisit previously missing posts. No denied public-feed fallback
is used, and revenue/watch-time measurements are unavailable.

SDK failures expose sanitized `ClientError.code`, `category`, `status`, and
`retry_after_seconds` (also `retry_after`). HTTP 429 is `rate_limit`, HTTP 401/403
is `auth`, transport timeouts/network failures and 5xx responses are `transient`.
Valid numeric or HTTP-date Retry-After values retain the provider minimum,
including delays longer than 24 hours. The actor preflight preserves this
metadata without passport response bodies and refuses an internal retry when
the provider minimum exceeds its local delay bound. Before any browser read,
manifest validation reserves enough space for every found ID and the complete
actor binding, so a request that cannot fit a 64 KiB continuation fails upfront.
