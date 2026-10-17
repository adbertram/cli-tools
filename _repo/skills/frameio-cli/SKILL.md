---
name: frameio-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  MANDATORY: Execute Frame.io public-share operations using the `frameio` CLI tool.
  Read public Frame.io shares (next.frame.io/share/<uuid> and f.io links) and download their original video files, with no login.
  Triggers: frameio, frame.io, frame.io share, f.io link, next.frame.io share, download frame.io video
---

<objective>
Execute Frame.io public-share operations using the `frameio` CLI. It needs no login: the share URL is the access. It reads share settings and asset metadata, and downloads original video files.
</objective>

<quick_start>
The `frameio` CLI follows this pattern:
```bash
frameio <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Check a share is enabled, allows downloads, and when it expires | `frameio shares get <SHARE_URL>` |
| List every asset in a share (id, name, size, video flag, stable url, signed download_url) | `frameio assets list <SHARE_URL>` |
| List only the videos | `frameio assets list <SHARE_URL> --filter "video:eq:true"` |
| Show one asset | `frameio assets get <SHARE_URL> <ASSET_ID>` |
| Download a video's original file | `frameio assets download <SHARE_URL> <ASSET_ID> --output <FILE_PATH>` |

`<SHARE_URL>` is `https://next.frame.io/share/<uuid>` or an `https://f.io/<code>` short link. `<ASSET_ID>` is a UUID from `assets list`. stdout is JSON; messages go to stderr.
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Verify the live command shape before executing ANY `frameio` command.**
Consult `usage.json` when the repo or installed package ships it. If `usage.json` is absent, use `frameio --help`, the relevant subcommand `--help`, and `README.md` instead. Never guess at command syntax.
</principle>

<principle name="Share Rules">
- Asset commands fail explicitly when the share is disabled, has downloads disabled, is expired, or has more than 200 assets (only the first page is read; pagination is not verified).
- `shares get` reports those settings without failing, so use it to diagnose why asset commands fail.
- `download_url` in asset rows is a short-lived signed URL. Use it at once and never write it to a file or note. `assets download` fetches a fresh one itself.
- `assets download` writes `<output>.part` and renames to `--output` only when the byte size matches exactly. The parent directory of `--output` must exist. Non-video assets and assets not in the share are refused.
</principle>

<principle name="Command Groups">
- **assets** -- List and download assets in a public Frame.io share (subcommands: download, get, list)
- **shares** -- Inspect public Frame.io shares (subcommands: get)
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions when present.
**`frameio --help` and subcommand `--help`** -- Live installed command tree and option list.
**`README.md`** -- Supplemental examples and workflow notes.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used, verified against the live help output or `usage.json` when present
</success_criteria>
