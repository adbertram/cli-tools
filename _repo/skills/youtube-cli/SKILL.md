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
| Upload a video | `youtube channel videos upload PATH --title "T" --privacy private` |
| Schedule a video | `youtube channel videos upload PATH --title "T" --privacy private --publish-at 2026-06-01T15:00:00Z` |
| Update a video | `youtube channel videos update VIDEO_ID --title "New" --privacy public` |
| Delete a video | `youtube channel videos delete VIDEO_ID --yes` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `youtube` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **videos** — Download public YouTube videos (single URLs, multiple URLs, or entire channels) via yt-dlp. Includes `videos list` and `videos get` for any public channel.
- **transcripts** — Download YouTube video transcripts/subtitles in various formats (srt, vtt, txt) via yt-dlp.
- **channel** — Manage the authenticated user's OWN channel via the YouTube Data API v3. Subgroup `channel videos` exposes `list`, `get`, `upload`, `update`, `delete`. Requires `youtube auth login` first.
- **auth** — OAuth login/logout/status/refresh/test plus `auth profiles ...` for multi-account workflows. Uses Google OAuth Desktop client credentials and stores token.json per profile.
</principle>

<principle name="Authentication">
Public download commands (`videos download`, `videos list`, `videos get`, `transcripts download`) require NO auth.
Channel-management commands (`channel videos ...`) require OAuth: run `youtube auth login` once, paste a Client ID + Secret from a Google Cloud "Desktop app" OAuth client, and complete the browser consent flow. Required scopes: `youtube`, `youtube.upload`, `youtube.force-ssl`.
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
