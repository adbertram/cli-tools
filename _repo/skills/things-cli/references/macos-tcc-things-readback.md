# macOS TCC hangs during Things readback

## When this applies

Use this reference when Things URL writes appear to dispatch, but verification via Things CLI, SQLite readback, or AppleScript hangs/timeouts.

Observed pattern:
- `things:///add...` opens successfully and Things3 is running.
- Simple AppleScript such as `tell application id "com.culturedcode.ThingsMac" to get name` may work.
- AppleScript task-object reads such as `count of to dos` can still fail with AppleEvent timeout `(-1712)`.
- `things todos list ...` or `things projects search ...` fails with `Timed out while accessing the Things database container` before printing JSON.
- Sampling the Python process during the original hang showed it stuck in `os.scandir` / `open` while globbing the Things group-container database path.
- macOS unified logs can show TCC denying `kTCCServiceSystemPolicyAllFiles` for the Python binary.

## Root cause

The CLI reads Things data from:

`~/Library/Group Containers/JLMPQHK86H.com.culturedcode.ThingsMac/ThingsData-*/Things Database.thingsdatabase/main.sqlite`

That container is protected by macOS privacy controls. If Full Disk Access is missing for the exact Python executable running the CLI, filesystem discovery can hang instead of failing quickly. The CLI now wraps protected-container globbing in a killable child process, so the durable symptom is a fast, actionable `ClientError` naming the Python binary that needs access.

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

Grant Full Disk Access to the exact Python binary reported by the error, currently observed as:

`/Users/adam/.local/share/uv/tools/things-cli/bin/python`

If System Settings shows that path as a greyed-out alias/symlink, grant Full Disk Access to the Homebrew Python app bundle instead:

`/opt/homebrew/Frameworks/Python.framework/Versions/3.14/Resources/Python.app`

Do not grant `pip3` as a substitute. `pip3` may be selectable because it is a script with a shebang into the same Python install, but the Things CLI runs as Python, not pip.

Open the settings pane:

```bash
open 'x-apple.systempreferences:com.apple.preference.security?Privacy_AllFiles'
```

Add that Python executable or Python.app bundle, enable it, then rerun:

```bash
things todos list --limit 1 --exclude-tag WF
```

After permissions are correct, the command should return promptly instead of failing with the TCC message.

## Agent handling rule

Do not retry Things writes or create duplicate tasks when this readback blocker appears. The blocker is local macOS TCC for the CLI Python, not evidence that the requested Things write failed. Stop, report the exact Full Disk Access action above, and resume verification only after access is granted.

## CLI hardening pattern

Do not let protected-container globbing hang indefinitely. Wrap database discovery in a killable child process with a short timeout. On timeout, raise a clear `ClientError` that names the exact `sys.executable` needing Full Disk Access.

This converts a silent hang into an actionable permissions error.
