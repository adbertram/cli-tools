# Frame.io CLI

## DESCRIPTION

Read public Frameio shares and download their original video files. Use this CLI for scriptable, JSON-first access to an unauthenticated share link (a share URL or short link) from agents, automation, or terminal workflows. There is no login and no auth group, because the share link itself is the access.

## Docs

- Web app: https://next.frame.io
- GraphQL endpoint: https://api.frame.io/graphql (operations `GetShareForShareReview`, `GetShareCollectionAssets`, `GetAssetForDownload`)

## Installation

```bash
<cli-tools-root>/_repo/skills/cli-tool/scripts/install-cli-tool.sh --force-refresh frameio
```

After installation, the `frameio` command will be available in your terminal.

## Quick Start

```bash
# Inspect a share
frameio shares get https://f.io/58zYKG1t

# List its assets
frameio assets list https://f.io/58zYKG1t --table

# Download the original of one video
frameio assets download https://f.io/58zYKG1t 5f14f9b8-b379-416d-98cb-40872e5f50bb --output ./video.mp4
```

## Commands

Every command takes the share URL as its first argument. `https://next.frame.io/share/<uuid>` URLs (optionally with a `/view/<asset>` suffix) and `f.io` short links are accepted; `f.io` links are resolved by following the redirect.

### Shares

```bash
# Get share settings: id, url, enabled, downloadingEnabled, expiration
frameio shares get https://next.frame.io/share/7f6203a3-8ec1-49fa-9c7c-07e3c1a8a9dd

# Table output (field/value rows)
frameio shares get https://f.io/58zYKG1t --table

# Restrict output fields
frameio shares get https://f.io/58zYKG1t --properties "id,downloadingEnabled"
```

`shares get` reports the settings as they are, including a disabled, download-disabled or expired share. Asset commands fail explicitly for such shares.

### Assets

```bash
# List the assets in the share's FILE collection (newest first, as the API returns them)
frameio assets list https://f.io/58zYKG1t

# Table output
frameio assets list https://f.io/58zYKG1t --table

# Only the first 10 assets (only those are looked up)
frameio assets list https://f.io/58zYKG1t --limit 10

# Only videos
frameio assets list https://f.io/58zYKG1t --filter "video:eq:true"

# Restrict output fields
frameio assets list https://f.io/58zYKG1t --properties "id,name,size"

# Get one asset (error if it is not in the share)
frameio assets get https://f.io/58zYKG1t 5f14f9b8-b379-416d-98cb-40872e5f50bb
frameio assets get https://f.io/58zYKG1t 5f14f9b8-b379-416d-98cb-40872e5f50bb --table

# Download the original video to exactly this path
frameio assets download https://f.io/58zYKG1t 5f14f9b8-b379-416d-98cb-40872e5f50bb --output ./video.mp4
```

`assets download` refuses assets that are not videos or not in the share. The file is written to `<output>.part` and moved to `--output` only when its size equals the original's `size` exactly; a failed download never replaces an existing file. The signed download URL is requested again right before each attempt; one attempt that gets HTTP 401 or 403 is retried once with a fresh URL. The parent directory of `--output` must exist.

## Output Formats

- JSON is the default output format (stdout). Messages go to stderr.
- Add `--table` / `-t` for human-readable table output.

### `shares get`

```json
{
  "id": "7f6203a3-8ec1-49fa-9c7c-07e3c1a8a9dd",
  "url": "https://next.frame.io/share/7f6203a3-8ec1-49fa-9c7c-07e3c1a8a9dd",
  "enabled": true,
  "downloadingEnabled": true,
  "expiration": null
}
```

### `assets list` / `assets get`

`assets list` prints an array of these rows; `assets get` prints one row.

```json
{
  "id": "5f14f9b8-b379-416d-98cb-40872e5f50bb",
  "share_id": "7f6203a3-8ec1-49fa-9c7c-07e3c1a8a9dd",
  "name": "4 Imposters vs 1 Real Ghost Hunter.mp4",
  "type": "VideoAsset",
  "video": true,
  "size": 537058072,
  "mime_type": "video/mp4",
  "status": "TRANSCODED",
  "url": "https://next.frame.io/share/7f6203a3-8ec1-49fa-9c7c-07e3c1a8a9dd/view/5f14f9b8-b379-416d-98cb-40872e5f50bb",
  "download_url": "https://assets.frame.io/uploads/...signed..."
}
```

`size` and `mime_type` are `null` and `download_url` is `null` for assets that are not `VideoAsset`. `download_url` is a short-lived signed URL: use it immediately and never store it. `url` is the stable view URL.

### `assets download`

```json
{
  "id": "5f14f9b8-b379-416d-98cb-40872e5f50bb",
  "name": "4 Imposters vs 1 Real Ghost Hunter.mp4",
  "size": 537058072,
  "path": "./video.mp4"
}
```

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display data as a table (`shares get`, `assets list`, `assets get`) |
| `--limit` | `-l` | Maximum number of assets (`assets list`, 1 to 200, default 100) |
| `--filter` | `-f` | Filter results using `field:op:value` syntax (`assets list`) |
| `--properties` | `-p` | Restrict output to selected fields (`shares get`, `assets list`, `assets get`) |
| `--output` | `-o` | File path to download to (`assets download`, required) |
| `--version` | `-v` | Show version and exit |

## Limits and Explicit Failures

- Only the first page of 200 assets is read. A share reporting `hasNextPage: true` fails with an error because cursor pagination is not verified.
- Metadata responses larger than 2 MiB fail.
- Share and asset IDs must be UUIDs.
- Asset commands fail when the share is disabled, has downloading disabled, is expired, or has missing or malformed settings.
- A video without original media metadata or with a non-HTTPS download URL fails.
- Nothing is cached and signed URLs are never written to disk.

## Configuration

No configuration or credentials are needed. Everything is read from the public share.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error (including every Frame.io failure above) |
| 2 | Usage error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### Download Every Video in a Share

```bash
share=https://f.io/58zYKG1t
frameio assets list "$share" --filter "video:eq:true" --properties "id,name" \
  | jq -r '.[] | [.id, .name] | @tsv' \
  | while IFS=$'\t' read -r id name; do frameio assets download "$share" "$id" --output "./$name"; done
```

### Total Size of a Share's Videos

```bash
frameio assets list https://f.io/58zYKG1t --properties "size" | jq 'map(.size // 0) | add'
```

## Requirements

- Python 3.11+
- Dependencies (installed automatically):
  - typer
  - python-dotenv

## License

MIT
