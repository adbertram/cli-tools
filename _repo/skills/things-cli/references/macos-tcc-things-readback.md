# macOS TCC hangs during Things readback

## When this applies

Use this reference when Things URL writes appear to dispatch, but verification via Things CLI, SQLite readback, or AppleScript hangs/timeouts.

Observed pattern:
- `things:///add...` opens successfully and Things3 is running.
- Simple AppleScript such as `tell application id "com.culturedcode.ThingsMac" to get name` may work.
- AppleScript task-object reads such as `count of to dos` can still fail with AppleEvent timeout `(-1712)`.
- `things todos list ...` or `things projects search ...` fails with `Timed out while accessing the Things database container` or `Permission denied while accessing the Things database container` before printing JSON.
- Sampling the Python process during the original hang showed it stuck in `os.scandir` / `open` while globbing the Things group-container database path; on other macOS states the same TCC denial returns `Operation not permitted` immediately.
- macOS unified logs can show TCC denying `kTCCServiceSystemPolicyAllFiles` for the Python binary.

## Root cause

The CLI reads Things data from:

`~/Library/Group Containers/JLMPQHK86H.com.culturedcode.ThingsMac/ThingsData-*/Things Database.thingsdatabase/main.sqlite`

That container is protected by macOS privacy controls. If Full Disk Access is missing for the exact Python executable running the CLI, filesystem discovery can hang or raise `Operation not permitted`. The CLI wraps protected-container discovery in a killable child process and explicitly probes the protected root for permission denial, so the durable symptom is a fast, actionable `ClientError` naming the Python binary that needs access.

## Diagnostic commands

Find the CLI Python from the live launcher; do not derive it from the command name:

```bash
launcher="$(command -v things)"
printf 'launcher=%s\n' "$launcher"
head -1 "$launcher"
```

Reproduce the read failure:

```bash
things todos list --limit 1 --exclude-tag WF
```

Or, for the Progress-project failure that triggered this note:

```bash
things projects search "Progress" --properties uuid,title,notes,tags,area_uuid,status,deadline,start_date
```

## Fix

Grant Full Disk Access to the exact responsible Python binary reported by the error. The CLI resolves launcher/venv symlinks because TCC attributes access to the real executable, not the symlink. Currently observed as:

`/Users/adam/.local/share/uv/python/cpython-3.11.15-macos-aarch64-none/bin/python3.11`

Do not grant the uv tool venv symlink, Terminal, `pip3`, or a different Homebrew Python app bundle as a substitute. The current gateway and CLI are attributed by TCC to the resolved uv-managed executable above. Re-check the live error after a uv Python upgrade because the versioned executable path can change.

Open the settings pane:

```bash
open 'x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles'
```

Add that exact Python executable, enable it, then rerun:

```bash
things todos list --limit 1 --exclude-tag WF
```

If the blocked caller is a scheduled Hermes cron run, restart the cron host
with `hermes gateway restart` before rerunning the probe.

After permissions are correct, the command should return promptly instead of failing with the TCC message.

## Agent handling rule

Do not retry Things writes or create duplicate tasks when this readback blocker appears. The blocker is local macOS TCC for the CLI Python, not evidence that a requested Things write failed.

`things todos create` is deliberately initialized without SQLite access. It dispatches the AppleScript create first and, when only its post-create SQLite readback is TCC-blocked, returns the UUID and requested fields from the confirmed AppleScript result. This keeps task creation usable and prevents a successful write from being reported as failure. Read commands still require Full Disk Access, and non-TCC readback failures still propagate.

For failures produced by older CLI builds or other write commands, stop, report the exact Full Disk Access action above, and resume verification only after access is granted.

## CLI hardening pattern

Do not let protected-container discovery hang indefinitely or silently collapse permission denial into "database not found." Wrap database discovery in a killable child process with a short timeout, and explicitly report `PermissionError` / `Operation not permitted` as the same Full Disk Access blocker. On timeout or permission denial, raise a clear `ClientError` that names the exact resolved executable needing Full Disk Access.

This converts a silent hang or misleading no-match into an actionable permissions error.
