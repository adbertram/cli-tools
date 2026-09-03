# TikTok CLI

## DESCRIPTION

The `tiktok` CLI provides tikTok transcript downloader using yt-dlp, plus commands to list and look up your saved (favorited) TikTok videos.

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

This CLI does not store TikTok credentials itself. The shared `auth` commands
exist so the wrapper exposes the standard profile surface and can report whether
the upstream `yt-dlp` dependency is available.

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
