---
name: "youtube-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Use this skill for ALL YouTube video, transcript, and channel-management operations. DO NOT use yt-dlp or the YouTube Data API directly. YouTube downloader (yt-dlp) PLUS YouTube Data API v3 channel management -- download videos/subtitles/transcripts AND list/get/upload/update/delete videos on the authenticated user's own channel. Triggers: youtube, youtube cli, youtube transcript, youtube subtitles, youtube captions, download youtube video, youtube channel download, youtube upload, upload to youtube, youtube channel videos, list my youtube videos, schedule youtube upload, delete youtube video, update youtube video, youtube oauth, youtube data api"
---

<objective>
Execute youtube operations using the `youtube` CLI. All youtube video and transcript interactions should use this CLI.
</objective>

<quick_start>
The `youtube` CLI follows this pattern:
```bash
youtube <group> <action> [args] [options]
```

| Task | Command |
|------|---------|
| Download video | `youtube videos download "URL"` |
| Download channel videos | `youtube videos download --channel channelname` |
| Download transcript | `youtube transcripts download "URL"` |
| Download as text | `youtube transcripts download "URL" --format txt` |
| Download to folder | `youtube videos download "URL" -o ~/videos/` |
| Multiple videos | `youtube videos download "URL1" "URL2"` |
| OAuth login (one-time) | `youtube auth login` (prompts for Client ID/Secret, opens browser) |
| List my channel videos | `youtube channel videos list -t` |
| Get my video metadata | `youtube channel videos get VIDEO_ID` |
| Validate video chapters | `youtube videos chapters validate --description $'00:00 Intro\n00:12 Setup\n02:05 Demo'` |
| Upload a video | `youtube channel videos upload PATH --title "T" --privacy private` |
| Ask AI to add chapters before upload | `youtube channel videos upload PATH --title "T" --description "D" --include-recommended-chapters` |
| Schedule a video | `youtube channel videos upload PATH --title "T" --privacy private --publish-at 2026-06-01T15:00:00Z` |
| Update a video | `youtube channel videos update VIDEO_ID --title "New" --privacy public` |
| Delete a video | `youtube channel videos delete VIDEO_ID --yes` |
| Post a channel message | `youtube channel posts create --message "Text" --profile brickbuddy` |
| List ALL my channels (every profile) | `youtube channels list -t` |
| List one profile's channel | `youtube channels list --profile brickbuddy` |
| Get a channel by ID | `youtube channels get CHANNEL_ID` |
| Set a channel banner | `youtube channels update CHANNEL_ID --banner-image banner.png` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `youtube` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **videos** — Download public YouTube videos (single URLs, multiple URLs, or entire channels) via yt-dlp. Includes `videos list` and `videos get` for any public channel.
- **transcripts** — Download YouTube video transcripts/subtitles in various formats (srt, vtt, txt) via yt-dlp.
- **channel** — Manage the authenticated user's OWN channel. Subgroup `channel videos` uses the YouTube Data API v3 for `list`, `get`, `upload`, `update`, `delete` and requires `youtube auth login` first. Subgroup `channel posts` derives the owned channel from the selected profile, then uses the authenticated YouTube web UI because Google's current Data API no longer supports channel bulletin/community-post creation; the same profile must have both `youtube auth login` and `youtube auth login --credential-type browser_session`.
- **channels** — Discover owned channels. `channels list` aggregates across EVERY authenticated profile (each OAuth token is bound to one channel, so this is the only way to see all channels you manage, e.g. personal plus brand channels). Each row is annotated with its source `profile` and channels reachable from multiple profiles are deduped. Pass `--profile` to restrict to one profile. `channels get` fetches one by ID (searching all profiles), `channels update` sets a banner, and `channels create` explains that the create API is unsupported. A profile with an invalid/expired token is reported on stderr and the command exits non-zero while still returning the channels that succeeded.
- **auth** — OAuth login/logout/status/test plus `auth profiles ...` (list/get/create/select/delete) for multi-account workflows. Uses Google OAuth Desktop client credentials and stores token.json per profile.
</principle>

<principle name="Authentication">
Public download commands (`videos download`, `videos list`, `videos get`, `transcripts download`) require NO auth.
Channel video-management commands (`channel videos ...`) require OAuth: run `youtube auth login` once, paste a Client ID + Secret from a Google Cloud "Desktop app" OAuth client, and complete the browser consent flow. Required scopes: `youtube`, `youtube.upload`, `youtube.force-ssl`.

Channel post commands (`channel posts create ...`) require both OAuth and a browser session on the same profile: run `youtube auth login` plus `youtube auth login --credential-type browser_session` once for that profile and sign into the YouTube account that can manage the target channel. Use `--dry-run` to validate the composer without publishing.
</principle>

<principle name="Channel Video Get Output">
`youtube channel videos get VIDEO_ID` returns flattened JSON. Read fields such as `description`, `title`, `duration`, and `status.privacy_status` from the top level; do not expect a raw YouTube API `snippet.description` shape. When piping CLI JSON into another command, use separate validation steps or `set -o pipefail` so parser errors cannot be hidden by a later successful command.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** — Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>

## Domain Knowledge

### YouTube VTT Inline Word Timestamps

**Context:** Use this when a YouTube task needs word-level timing, such as removing filler words from a downloaded video.

**Key Facts:** Download captions as VTT with `youtube transcripts download "URL" --format vtt`. YouTube VTT captions can include inline karaoke timestamps like `<00:00:14.880><c> word</c>`; those inline markers provide word-level timing without running local speech-to-text. Treat standalone words only after stripping punctuation, so `um` and `uh` are matched as tokens rather than substrings.

**Gotchas:** Some YouTube VTT cues contain zero-duration words or final inline timestamps that are a few milliseconds beyond the cue end. Preserve the inline timestamp ordering and clamp only the final token end to at least its start; do not invent wider timings.

## Known Issues

### 1. FFmpeg Select Filters Exhaust Memory On Dense Filler Cut Lists

**Symptom:** Rendering hundreds of YouTube word-timestamp cuts with a single `select='not(between(t,...)+...)'` / `aselect` expression fails with `Error initializing filters` and `Error : Cannot allocate memory`.

**Cause:** Large ffmpeg select expressions with hundreds of `between()` clauses can exceed practical filter parser or graph memory limits.

**Fix:** For dense filler-word edits, create sorted remove intervals, split the source at every keep/remove boundary with the segment muxer while forcing keyframes at those boundaries, then concatenate only the kept segment files with the concat demuxer.

**Verification:** Confirm the segment file count matches the generated plan, concatenate with `ffmpeg -f concat -safe 0 -i concat_keep.txt -c copy`, probe the final file with `ffprobe`, and run `ffmpeg -v error -i final.mp4 -f null -` to catch decode errors.

**Recurrence Prevention:** Do not use one giant `select`/`aselect` expression for high-cardinality YouTube word cuts; use a segment-and-concat plan whenever the cut list has hundreds of intervals.

### 2. Text Transcript Output Must Convert From VTT

**Symptom:** `youtube transcripts download "URL" --format txt` failed with `yt-dlp: error: invalid subtitle format "txt" given`.

**Cause:** The CLI advertised `txt` as a transcript output format but passed `txt` directly to `yt-dlp --convert-subs`; `yt-dlp` accepts subtitle formats such as `srt` and `vtt`, not plain text.

**Fix:** Update `<repo-root>/youtube/youtube_cli/client.py` so `--format txt` downloads VTT, converts it to plain text, removes the intermediate VTT file, and reports the `.txt` file.

**Verification:** Reinstall with `uv tool install -e <repo-root>/youtube --force --refresh`, then run `youtube transcripts download "https://www.youtube.com/watch?v=lHQH5zqnBDg" --format txt --output-dir /tmp/youtube-txt-test --table` and confirm the table reports `Format` as `txt` and the output directory contains only the `.txt` transcript.

**Recurrence Prevention:** Keep `txt` as a CLI-level output mode, not a direct `yt-dlp --convert-subs` value.
