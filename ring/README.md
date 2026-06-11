# Ring CLI

## DESCRIPTION

The `ring` CLI provides a command-line interface for Ring devices via python-ring-doorbell.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Installation

To install or refresh the editable CLI from this repository:

```bash
<cli-tools-root>/_repo/_scripts/install-cli-tool.sh ring
```

After installation, the `ring` command is on PATH.

## Quick Start

```bash
ring auth login        # prompts for Ring account email, password, and 2FA code
ring devices list      # confirm the account looks right
ring devices list --table
```

## Authentication

This CLI does not use Ring Partner API app credentials. It wraps `python-ring-doorbell`, whose supported bootstrap flow is your Ring consumer account email/password plus Ring's 2FA challenge, followed by a cached OAuth refresh token.

The official Ring developer platform is a separate hosted partner integration model with account-linking URLs, token-exchange endpoints, webhooks, and HMAC verification. That model is not wired into this local CLI and does not cover the full control surface this tool currently exposes through `ring-doorbell`.

On first login the SDK exchanges your email + password for an access/refresh token, and Ring sends a 6-digit 2FA code via SMS or email. The CLI prompts for the code interactively. After that, the refresh token in `~/authentication_profiles/<profile>/ring_token.json` keeps the session alive — no further prompts.

```bash
# First-time login (interactive 2FA prompt)
ring auth login

# Re-authenticate from scratch (clears cached token, prompts again)
ring auth login --force

# Status — shows whether credentials and token are usable
ring auth status
ring auth status --table

# Drop credentials + token
ring auth logout

# Profiles
ring auth profiles list
ring auth profiles create work
ring auth profiles select work
```

`--force` clears the cached OAuth token so the next login re-runs the Ring account + 2FA challenge.

## Devices (`ring devices`)

```bash
# List every doorbell, camera, chime, intercom
ring devices list
ring devices list --table
ring devices list --family stickup_cams
ring devices list --filter "family:eq:doorbots"
ring devices list --properties "id,name,family,kind" --table
ring devices list --limit 5

# Full detail (includes battery, wifi, connection)
ring devices get "Front Door"
ring devices get 123456789 --table
ring devices get "Front Door" --properties "id,name,battery_life,wifi_signal_strength"

# Health-only snapshot
ring devices health "Front Door"
ring devices health "Back Yard" --table
```

`--family` accepts: `doorbots`, `authorized_doorbots`, `stickup_cams`, `chimes`, `other`.

## Events (`ring events`)

History across all video devices (doorbells, cameras). Each event is a ding, motion, or on-demand session.

```bash
ring events list
ring events list --table
ring events list --device "Front Door" --limit 50
ring events list --kind motion
ring events list --device "Back Yard" --kind ding --table
ring events list --filter "answered:eq:true"
ring events list --properties "id,device_name,kind,created_at" --table
```

### Download recordings

Recordings are MP4 files served by Ring's S3-backed CDN.

```bash
# Specific event id (use `events list` to find it)
ring events download EVENT_ID --device "Front Door"

# The most recent N events for a device
ring events download --device "Front Door" --recent 5
ring events download --device "Back Yard" --recent 10 --kind motion

# Choose a destination (default: ~/Downloads/ring/)
ring events download --device "Front Door" --recent 3 --output ./clips
```

## Snapshots (`ring snapshot`)

Triggers a fresh capture from a doorbell or camera.

```bash
ring snapshot get --device "Front Door"
ring snapshot get --device 123456789 --output ./front-door.jpg
ring snapshot get --device "Back Yard" --table
```

## Motion detection (`ring motion`)

Per-device on/off toggle. Motion zones and sensitivity sliders are not exposed by the `ring-doorbell` library — edit them in the mobile app.

```bash
ring motion status --device "Front Door"
ring motion enable --device "Front Door"
ring motion disable --device "Front Door"
ring motion status --device "Front Door" --table
```

## Lights (`ring lights`) — stickup_cams only

```bash
ring lights on  --device "Driveway"
ring lights off --device "Driveway"
ring lights on  --device "Driveway" --table
```

## Siren (`ring siren`) — stickup_cams only

```bash
ring siren on  --device "Driveway" --duration 30
ring siren off --device "Driveway"
ring siren on  --device "Driveway" --duration 60 --table
```

## Chime test (`ring chime`)

```bash
ring chime test --device "Downstairs" --kind ding
ring chime test --device "Downstairs" --kind motion --table
```

## Volume (`ring volume`)

```bash
ring volume set --device "Front Door" --value 7
ring volume set --device "Downstairs" --value 3 --table
```

## Output Formats

All commands default to JSON on stdout. Pass `--table`/`-t` for a human-readable table. Messages and prompts go to stderr.

```bash
ring devices list | jq '.[] | select(.family=="doorbots") | .name'
ring events list --device "Front Door" --limit 20 > events.json
```

## Options Reference

| Option | Short | Where | Description |
|--------|-------|-------|-------------|
| `--table` | `-t` | every read command | Render as a markdown table |
| `--limit` | `-l` | list commands | Maximum rows |
| `--filter` | `-f` | list commands | Filter `field:op:value` (repeatable) |
| `--properties` | `-p` | list / get | Comma-separated field allow-list (supports dot-notation) |
| `--device` | `-d` | events / snapshot / motion / lights / siren / chime / volume | Device name or numeric ID |
| `--kind` | `-k` | events | Filter by event kind (`ding`, `motion`, ...) |
| `--family` | — | `devices list` | Filter by device family |
| `--output` | `-o` | `events download` / `snapshot get` | Destination path |
| `--recent` | `-r` | `events download` | Download last N events |
| `--duration` | `-u` | `siren on` | Seconds to sound the siren |
| `--value` | `-v` | `volume set` | Volume 0-10 |
| `--force` | `-F` | `auth login` | Clear cached token + re-run 2FA |
| `--profile` | `-p` | every `auth` command | Multi-account support |
| `--version` | `-v` | root | Show version and exit |

## Configuration

`auth login` writes the email and password to `authentication_profiles/<profile>/.env` and persists the OAuth token (with refresh) to `authentication_profiles/<profile>/ring_token.json`. Both files live under the CLI's installed directory; never edit them by hand.

This CLI does not read `CLIENT_ID`, `CLIENT_SECRET`, redirect URIs, webhook URIs, or HMAC keys from the Ring developer console.

| Env var | Source | Notes |
|---------|--------|-------|
| `RING_USERNAME` | `.env` | Ring account email |
| `RING_PASSWORD` | `.env` | Ring account password |
| `RING_BASE_URL` | `.env` | Override default `https://api.ring.com` if Ring redirects |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error (network, Ring API failure, validation) |
| 2 | Authentication / credential error |
| 130 | User interrupted (Ctrl+C) |

## Debug

Set `DEBUG=1` to enable verbose logging from `cli_tools_shared`:

```bash
DEBUG=1 ring devices list
```

## Scope notes

- **Ring Alarm (security panel arm/disarm):** Not exposed by `ring-doorbell`. Use the Ring mobile app.
- **Motion zones / sensitivity:** Not exposed by `ring-doorbell`. Use the Ring mobile app.
- **Live streaming / two-way talk:** Out of scope for v1 (the library exposes WebRTC primitives but the workflow is non-trivial in a CLI context).

## Library

This CLI wraps [`ring-doorbell`](https://pypi.org/project/ring-doorbell/) `>=0.9.14` — the same Python library used by Home Assistant. `0.9.14` is the current PyPI release and authenticates with `Auth.async_fetch_token(username, password, otp_code=None)` against Ring's consumer OAuth endpoint.

Ring does now publish an official partner API, but it is a separate hosted integration surface documented at Amazon Developer. The current CLI is not a Ring App Store partner integration and does not use that auth model. If a command breaks after a Ring backend change, check the [project tracker](https://github.com/python-ring-doorbell/python-ring-doorbell/issues) first.

## Models

This CLI uses Pydantic models for type-safe data handling.

| Model | Returned by |
|-------|-------------|
| `Device` | `devices list`, `devices get` |
| `DeviceHealth` | `devices health` |
| `Event` | `events list` |
| `DownloadResult` | `events download` |
| `SnapshotResult` | `snapshot get` |
| `MotionState` | `motion enable` / `motion disable` / `motion status` |
| `LightsState` | `lights on` / `lights off` |
| `SirenState` | `siren on` / `siren off` |
| `VolumeState` | `volume set` |

## License

MIT
