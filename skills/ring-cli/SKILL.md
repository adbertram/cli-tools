---
name: "ring-cli"
description: "Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert. MANDATORY: Execute ring operations using the `ring` CLI tool. CLI for Ring doorbells, cameras, chimes, and intercoms — devices, events, snapshots, recording downloads, motion detection, lights, siren, chime test, volume. Triggers: ring, ring cli, ring doorbell, ring camera, ring chime, ring devices, ring events, ring motion, ring snapshot, ring history, ring recording, ring download, my ring, my doorbell, motion detection ring, ring floodlight, ring siren, ring intercom, list ring devices, last ring event, doorbell battery, doorbell wifi, ring 2fa."
---

<objective>
Execute ring operations using the `ring` CLI. All ring interactions should use this CLI — never hit the Ring API directly, never scrape the Ring web UI.
</objective>

<quick_start>
The `ring` CLI follows this pattern:
```bash
ring <command-group> <action> [arguments] [options]
```

| Common task | Command |
|-------------|---------|
| First-time login (prompts for email, password, 2FA) | `ring auth login` |
| List every device on the account | `ring devices list --table` |
| Show battery + wifi for one device | `ring devices health "Front Door" --table` |
| Recent motion events on one device | `ring events list --device "Front Door" --kind motion --limit 20` |
| Download the last 5 recordings | `ring events download --device "Front Door" --recent 5` |
| Grab a fresh snapshot | `ring snapshot get --device "Front Door"` |
| Turn motion detection on/off | `ring motion enable --device "Front Door"` |
| Floodlight on (stickup_cams only) | `ring lights on --device "Driveway"` |
| Sound the siren | `ring siren on --device "Driveway" --duration 30` |
| Test a chime | `ring chime test --device "Downstairs" --kind ding` |
| Set volume | `ring volume set --device "Front Door" --value 7` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult `usage.json` before executing ANY `ring` command.**
That file contains the full command tree (every argument, every option, every leaf usage_instruction). Do not guess flag names — read usage.json.
</principle>

<principle name="2FA on first login">
Ring requires a 6-digit 2FA code on the first login from this CLI client (delivered via SMS/email at the moment `ring auth login` runs). The CLI prompts for it through the standard cli_tools_common prompting pipeline. After a successful exchange the OAuth token (with refresh) is cached in the profile data directory and reused on subsequent runs — no further prompts. Use `ring auth login --force` to clear the cached token and re-run the 2FA challenge.
</principle>

<principle name="Device identifiers">
Every per-device command (events, snapshot, motion, lights, siren, chime, volume) accepts either the case-insensitive device name (e.g. `"Front Door"`) OR the numeric device ID returned by `ring devices list`. Names are matched exactly (case-insensitive) — partial matches are not supported.
</principle>

<principle name="Out of scope">
Ring Alarm arm/disarm (security panel mode home/away/disarmed) and motion-zone editing are NOT exposed by the underlying ring-doorbell library and are intentionally not part of this CLI. If a user asks for those, point them at the Ring mobile app and do not try to scrape the web UI.
</principle>

<principle name="Output">
Default output is JSON on stdout for every read command. Pass `--table`/`-t` for a human-readable markdown table. Messages and prompts go to stderr. Pipe to `jq` for ad-hoc shaping.
</principle>
</essential_principles>

<command_groups>
| Group | Purpose |
|-------|---------|
| `auth` | Login (with 2FA prompt), logout, status, refresh, test. Supports profiles. |
| `devices` | List / get / health for doorbells, cameras, chimes, intercoms. |
| `events` | History (dings + motion + on-demand) — list, get, download. |
| `snapshot` | List snapshot-capable devices; capture fresh JPEGs. |
| `motion` | Toggle motion detection (enable/disable/status) per device. |
| `lights` | Control floodlights on stickup_cams. |
| `siren` | Sound / silence the siren on stickup_cams. |
| `chime` | Play test sounds on Ring chimes. |
| `volume` | Set device volume (0-10). |
| `cache` | Manage the local response cache. |
</command_groups>

<reference_index>
**`usage.json`** — Complete command tree with arguments, options, defaults, and usage_instructions for every command. Read before issuing any `ring` command.
</reference_index>

<success_criteria>
- Command executes without error (exit code 0)
- Output is in the requested format (JSON by default, table with --table)
- Correct command path and flags used, verified against usage.json
- No direct Ring API calls, no Ring web scraping
</success_criteria>
