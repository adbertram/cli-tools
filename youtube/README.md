# YouTube CLI

A command-line interface that combines:

1. **Public download commands** (no auth) for any YouTube video/transcript using `yt-dlp`.
2. **Channel management commands** (OAuth) for the authenticated user's own channel via the YouTube Data API v3 — list, get, upload, update, and delete videos.
3. **Owned-channel commands** (OAuth) to list every YouTube channel available under the authenticated Google account/profile, update the banner image for one owned channel, plus `youtube channels create` guidance for the unsupported channel-creation boundary.

## Installation

```bash
cd youtube
pip install -e .
```

After installation, the `youtube` command will be available in your terminal.

## Prerequisites

This CLI requires `yt-dlp` to be installed:

```bash
brew install yt-dlp
```

## Quick Start

```bash
# Download transcript for a single video
youtube transcripts download "https://www.youtube.com/watch?v=7usLf-LEcTA"

# Download multiple transcripts to specific folder
youtube transcripts download -o ./transcripts "https://www.youtube.com/watch?v=7usLf-LEcTA" "https://www.youtube.com/watch?v=2EpoUnx2oQY"

# Download with table output
youtube transcripts download "https://www.youtube.com/watch?v=7usLf-LEcTA"

# Get VTT format instead of SRT
youtube transcripts download --format vtt "https://www.youtube.com/watch?v=7usLf-LEcTA"

# Prefer manual subtitles if available
youtube transcripts download --manual-sub "https://www.youtube.com/watch?v=7usLf-LEcTA"
```

## Commands

### Transcripts Download

```bash
# Download transcript for single video (SRT format, English, auto-generated)
youtube transcripts download "VIDEO_URL"

# Download multiple transcripts
youtube transcripts download "URL1" "URL2" "URL3"

# Specify output directory
youtube transcripts download -o /path/to/output "VIDEO_URL"

# Change subtitle format (srt, vtt, txt)
youtube transcripts download --format vtt "VIDEO_URL"
youtube transcripts download --format txt "VIDEO_URL"

# Change language
youtube transcripts download --lang es "VIDEO_URL"

# Prefer manual subtitles over auto-generated
youtube transcripts download --manual-sub "VIDEO_URL"

# Display results as table
youtube transcripts download "VIDEO_URL"
```

### Videos Download

```bash
# Download a single video
youtube videos download "https://www.youtube.com/watch?v=VIDEO_ID"

# Download multiple videos
youtube videos download "URL1" "URL2"

# Download to specific directory
youtube videos download -o /path/to/output "VIDEO_URL"

# Change format (mp4, mkv, webm)
youtube videos download --format mkv "VIDEO_URL"

# Change quality (best, worst, or yt-dlp format code)
youtube videos download --quality worst "VIDEO_URL"

# Cap video resolution to keep downloads smaller
youtube videos download --max-resolution 480p "VIDEO_URL"
youtube videos download --max-resolution 360p "VIDEO_URL"
youtube videos download --max-resolution 240p "VIDEO_URL"

# Download all videos from a channel
youtube videos download --channel channelname

# Sync latest channel videos into an existing folder
youtube videos download --channel channelname --sync --folder-path ./videos

# Sync the latest 50 channel videos, skip IDs found on the Shorts tab, then download missing titles
youtube videos download --channel channelname --sync --folder-path ./videos --exclude-shorts

# Download channel videos to specific directory with table output
youtube videos download --channel channelname -o ./videos -t
```

### Auth (OAuth, required for `channel ...` and `channels ...` commands)

Channel management uses the YouTube Data API v3 with OAuth 2.0.

**One-time setup:**

1. Open https://console.cloud.google.com/apis/credentials and create an OAuth client ID of type **Desktop app**.
2. Enable the **YouTube Data API v3** for the same project: https://console.cloud.google.com/apis/library/youtube.googleapis.com
3. Run:

```bash
youtube auth login
# Paste the Client ID and Client Secret when prompted.
# A browser opens for the YouTube consent screen.
# Required scopes: youtube, youtube.upload, youtube.force-ssl.
```

The credentials and OAuth token are stored under `~/.local/share/cli-tools/youtube/authentication_profiles/<profile>/`.

**Other auth commands:**

```bash
youtube auth status                       # Inspect saved credentials/token
youtube auth test                         # Verify the token works (calls channels.list mine=True)
youtube auth refresh                      # Refresh the access token
youtube auth logout                       # Clear credentials/token for the active profile
youtube auth login --force                # Re-run consent (clears the token first)
youtube auth login --profile work         # Authenticate a named profile
```

**Profiles:**

```bash
youtube auth profiles list
youtube auth profiles create myprofile --auth-type google_oauth_desktop
youtube auth profiles create myprofile --auth-type google_oauth_desktop \
  --auth-param CLIENT_ID=your-client-id \
  --auth-param CLIENT_SECRET=your-client-secret
youtube auth profiles select myprofile
youtube auth profiles delete myprofile
```

### Channel Management (`youtube channel videos ...`)

All commands below operate on the authenticated user's own channel.

```bash
# List videos on your channel (paginates through the uploads playlist)
youtube channel videos list --table
youtube channel videos list --limit 100 --filter privacy_status:eq:public

# Get full metadata (snippet + status + statistics + contentDetails) for one video
youtube channel videos get VIDEO_ID

# Upload a local video file
youtube channel videos upload ./my-video.mp4 \
    --title "My new video" \
    --description "Long description..." \
    --tag tag1 --tag tag2 \
    --category-id 22 \
    --privacy private \
    --thumbnail ./thumb.png

# Schedule a video (must stay private until publish-at)
youtube channel videos upload ./video.mp4 \
    --title "Scheduled video" \
    --privacy private \
    --publish-at 2026-06-01T15:00:00Z

# Mark as made for kids
youtube channel videos upload ./video.mp4 --title "Kids video" --made-for-kids

# Update an existing video (provide at least one field)
youtube channel videos update VIDEO_ID --title "Updated title" --privacy public
youtube channel videos update VIDEO_ID --thumbnail ./new-thumb.jpg
youtube channel videos update VIDEO_ID --tag tagA --tag tagB   # replaces existing tags

# Delete a video (prompts for confirmation; use --yes/-y to skip)
youtube channel videos delete VIDEO_ID --yes
```

### Owned Channels (`youtube channels ...`)

These commands list the YouTube channels returned by `channels.list(mine=true)` for the authenticated profile.
`youtube channels update` inspects the banner image before any API call. Images smaller than 2048x1152 fail immediately. Every other valid jpg/png banner is normalized to YouTube's recommended 2560x1440 frame when needed, and oversize files are re-encoded under 6 MB before `channelBanners.insert` runs.
`youtube channels create` is intentionally non-mutating: the YouTube Data API v3 does not expose a channel-creation method, so the CLI exits with a clear error that points you to the official web flow.

```bash
# List every owned/available channel for the active authenticated profile
youtube channels list

# Standard list options
youtube channels list --table
youtube channels list --limit 10
youtube channels list --filter "title:contains:Brick"
youtube channels list --properties "id,title,subscriber_count"

# Get one owned channel by channel ID
youtube channels get CHANNEL_ID
youtube channels get CHANNEL_ID --table

# Update one owned channel's banner image
# The CLI rejects banners smaller than 2048x1152 before upload.
# Larger or oversize files are normalized to a 2560x1440 upload-ready copy under 6 MB.
youtube channels update CHANNEL_ID --banner-image ./banner.png
youtube channels update CHANNEL_ID --banner-image ./banner.png --properties "id,title,banner_external_url"

# Channel creation is not available in the API; the command explains the manual flow
youtube channels create
```

## Options Reference

### Download Command Options

| Option | Short | Description | Default |
|--------|-------|-------------|---------|
| `--output-dir` | `-o` | Output directory for transcripts | Current directory (`.`) |
| `--format` | `-f` | Subtitle format: `srt`, `vtt`, `txt` | `srt` |
| `--lang` | `-l` | Subtitle language code | `en` |
| `--auto-sub/--no-auto-sub` | | Download auto-generated subtitles | `--auto-sub` |
| `--manual-sub` | | Prefer manual subtitles over auto-generated | `False` |
| `--version` | `-v` | Show version and exit | |

## Output Formats

### Table Output

```bash
youtube transcripts download "VIDEO_URL"
```

Displays results in a formatted table with:
- Title
- Duration
- Filename
- File size
- Format

### List Output (default)

```bash
youtube transcripts download "VIDEO_URL"
```

Displays detailed information for each transcript:
- Video title
- Duration
- Full file path
- File size
- Format and language

## Examples

### Download Multiple Transcripts

```bash
youtube transcripts download \
  "https://www.youtube.com/watch?v=7usLf-LEcTA" \
  "https://www.youtube.com/watch?v=2EpoUnx2oQY" \
  -o ~/Documents/transcripts \

```

### Get VTT Format for Spanish Subtitles

```bash
youtube transcripts download \
  --format vtt \
  --lang es \
  "https://www.youtube.com/watch?v=7usLf-LEcTA"
```

### Download Text Format Only

```bash
youtube transcripts download \
  --format txt \
  -o ./text-transcripts \
  "https://www.youtube.com/watch?v=7usLf-LEcTA"
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
