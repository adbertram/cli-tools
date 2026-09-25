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
