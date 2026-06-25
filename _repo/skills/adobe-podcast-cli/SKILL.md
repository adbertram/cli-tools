---
name: adobe-podcast-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute Adobe Podcast operations using the `adobe-podcast` CLI tool.
  CLI interface for Adobe Podcast Enhance — upload audio, run AI speech enhancement, and download the result.
  Triggers: adobe podcast, adobe podcast enhance, enhance audio, speech enhancement, adobe podcast cli, upload audio, enhance recording
---

<objective>
Execute Adobe Podcast Enhance operations using the `adobe-podcast` CLI. All Adobe Podcast interactions should use this CLI.
</objective>

<quick_start>
The `adobe-podcast` CLI follows this pattern:
```bash
adobe-podcast <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Authenticate | `adobe-podcast auth login` |
| Check auth | `adobe-podcast auth status` |
| Enhance a file | `adobe-podcast enhance run recording.wav` |
| Enhance with custom output | `adobe-podcast enhance run recording.wav --output enhanced.wav` |
| Enhance with gain tuning | `adobe-podcast enhance run podcast.mp3 --enhanced-gain 0.9 --background-gain 0.1` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `adobe-podcast` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `adobe-podcast --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **enhance** -- Upload an audio or video file, run Adobe Podcast AI speech enhancement, and download the enhanced WAV. Supports gain controls for enhanced speech, background audio, and isolated speech.
- **auth** -- Manage browser-session authentication and profiles. Adobe IMS login is manual (browser opens for sign-in); the IMS access token is then extracted headlessly and cached.
- **cache** -- Clear cached responses.
</principle>

<principle name="Auth Flow">
Adobe Podcast uses Adobe IMS for authentication. `auth login` opens a real browser window for manual sign-in (CDP automation is blocked by Adobe IMS). After login, subsequent `enhance run` calls extract the IMS token from `window.adobeIMS` via a headless session and cache it. If the token expires, re-run `auth login`.
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`adobe-podcast --help` and subcommand `--help`** -- Live installed command tree and option list.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
