---
name: roomba-cli
description: >-
  Use this skill for service operations only. DO NOT use this skill for CLI implementation lifecycle work such as creating, testing, updating, troubleshooting, validating, removing, or documenting the CLI tool itself; delegate those tasks to cli-tool-expert.
  Execute roomba operations using the `roomba` CLI tool.
  CLI to control iRobot Roomba vacuums.
  Triggers: roomba, roomba cli, roomba vacuum, start roomba, stop roomba, dock roomba, roomba status, roomba battery, vacuum cleaner, irobot
---

<objective>
Execute roomba operations using the `roomba` CLI. All Roomba vacuum interactions should use this CLI.
</objective>

<quick_start>
The `roomba` CLI follows this pattern:
```bash
roomba <command-group> <action> [arguments] [options]
```

| Task | Command |
|------|---------|
| Quick status check | `roomba status` |
| List robots | `roomba robots list --table` |
| Start cleaning | `roomba control start` |
| Stop cleaning | `roomba control stop` |
| Send to dock | `roomba control dock` |
| Find robot (beep) | `roomba control find` |
| Evacuate bin | `roomba control evac` |
| Detailed status | `roomba control status` |
</quick_start>

<essential_principles>
<principle name="Usage Reference">
**MANDATORY: Consult the adjacent `usage.json` at `<cli-tools-root>/_repo/skills/<tool>-cli/usage.json` before executing ANY `roomba` command.**
This file contains complete command syntax, all arguments, all options, and usage instructions for every command. Never guess at command syntax.
</principle>

<principle name="Command Groups">
- **status** -- Quick robot status (shortcut for control status)
- **robots** -- List and view robot information (list, get)
- **control** -- Control robots (start, stop, pause, resume, dock, find, evac, status)
- **auth** -- Manage authentication and discovery (login, logout, status, refresh, test)
- **auth** -- Authentication commands and nested `auth profiles` management
</principle>
</essential_principles>

<reference_index>
**`usage.json`** -- Complete command tree with arguments, options, defaults, and usage instructions for every command.
</reference_index>

<success_criteria>
- Command executes without error
- Output is displayed in requested format
- Correct command and flags used (verified against usage.json)
</success_criteria>

<cloud_reads>
Verified 2026-10-20 against successful authorized app traffic and live CLI reads.
`cloud import-capture PRIVATE_PATH` imports temporary AWS credentials through the
CLI-tools secret manager, cloud inventory, and exact supported successful GET
request templates. The decoder runs through pinned mitmproxy 12.2.3 via `uv`.
It requires a successful app `/v2/login` in the capture. A matching Gigya session
is verified before enabling automatic AWS/MQTT renewal. Captured old login proofs
and account/robot passwords are never retained. Requests must match that
login's access key, or another captured login with identical Cognito identity and
robot/deployment membership. Keep captures and raw output in private non-synced storage.

Use `cloud robots list` to inspect multiple captured vacuums, `cloud select NAME_OR_ID`
for the local cloud default, or `cloud read history --robot NAME_OR_ID` for explicit
selection. Robot history/setup templates are isolated by exact cloud robot ID.
`cloud read schedule` and `cloud read entitlements` are shared household/account
reads. A resource absent from that vacuum's capture fails explicitly. Local LAN
configuration and robot passwords are preserved. Temporary tokens renew automatically
when a verified reusable Gigya session was imported. Rejection or expiration of
that underlying session requires a fresh authorized app login capture.

Label this evidence **Local source**. Cloud data never establishes live device
status or robot execution. The existing LAN path remains separate. This group
supports both captured vacuum models; model-specific repair guidance still requires
the appropriate hardware source. See the CLI README for redacted provenance and
operating limits. Consult the adjacent generated usage map before commands.
</cloud_reads>


<read_surface>
`cloud status --robot NAME_OR_ID` reports model-specific observed telemetry with
per-field metadata age; snapshots never prove current physical online status.
`cloud schedules --robot NAME_OR_ID` reads both household and stored robot
schedules. Household membership must match the selected robot. Empty household
schedules do not establish that stored robot schedules are empty.
`cloud favorites list/get` reads actual favorite definitions and enforces exact
robot membership. Favorites are never started by a read command.

`cloud read` additionally exposes captured robot details, parts, timeline,
map metadata/version, time estimates, evacuation history, teaming/report,
account settings, automations, households, IFTTT connections, and supported
c975020 named settings/config/stats/software snapshots. Missing templates or
unproven map ownership fail explicitly; do not invent a read for another model.
`cloud shadow` is an advanced bounded shadow read, with an allowlist of locally
accepted c975020 partition names. No wildcard subscriptions or mutations exist.
Use `cloud import-capture PATH --additional-capture PATH` for successive private
captures, keeping the same-account proof and per-robot routing intact.

MQTT tokens live in the CLI secret manager. The captured server client ID can
displace the phone connection; perform bounded sequential reads and disconnect.
Never infer freshness from broker GET time, `connected: true`, or error zero.
Check original per-field metadata timestamps. See README and adjacent usage map.
</read_surface>


<session_renewal>
`cloud auth-status` reports local expiry/renewal readiness without logging in.
`cloud refresh` explicitly renews AWS credentials and MQTT connection tokens.
Normal REST/MQTT reads proactively renew relevant tokens within 90 seconds of
expiry, using a fresh signed Gigya account-info request and fresh iRobot login
proof. No password or captured old proof is replayed. Import can bootstrap from
expired temporary tokens when its verified reusable Gigya session remains valid.

Account identity, exact robot SKU/deployment membership and MQTT device coverage
must validate before the atomic credential-store replacement. Session metadata,
default robot and LAN credentials remain unchanged. Per-profile refresh locks
coalesce overlap; separate MQTT operation locks serialize whole read sequences.
Identifiable auth rejection permits one renewal/read retry, with a 30-second
recent-renewal cooldown. Generic transport errors never cause a login loop.
Rejected long-lived sessions require sign-in/import; no background job is created.
See README for supported signing provenance, bounds and live verification.
</session_renewal>

<experimental_cloud_control>
`cloud start --robot NAME_OR_ID` and `cloud pause --robot NAME_OR_ID` physically
act on the explicitly selected vacuum. Obtain action authorization under the
owning project contract. Confirm current app online state; cached connected
flags do not prove reachability. These commands are experimental for the two
scoped SKUs until fresh robot execution evidence is obtained.

They use the captured deployment irbtTopics prefix, a single nonretained QoS1
publish of command/time/rmtApp, no reconnect, and no mutation retry. Auth renews
before publishing under the same-profile MQTT operation lock. Nonretained is
not a guarantee against deferred device delivery. Timeout after publication
means unknown completion, never automatically repeat.

JSON separates publish_attempted, broker_received and robot_confirmed. Only a
fresh changed matching lastCommand or matching mission phase transition can
confirm a robot report; lastCommand is acknowledgement, not physical movement.
PUBACK alone cannot. Existing run/stop phases cannot
confirm. Unconfirmed completion exits1 with structured JSON; --timeout bounds
the entire baseline/publish/confirmation operation (default30, max60 seconds).
</experimental_cloud_control>
