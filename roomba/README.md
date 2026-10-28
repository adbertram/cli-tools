# Roomba CLI

## DESCRIPTION

The `roomba` CLI provides a command-line interface for Roomba API.

Use it when you need scriptable, JSON-first access from agents, automation, or terminal workflows.

## Installation

```bash
cd roomba
pip install -e .
```

After installation, the `roomba` command will be available in your terminal.

## Quick Start

```bash
# Discover and configure robots on your network
roomba auth login

# List configured robots
roomba robots list

# Get robot status
roomba status "Living Room"

# Start cleaning
roomba control start "Living Room"

# Send robot to dock
roomba control dock "Living Room"
```

## Commands

### Authentication

```bash
# Auto-discover robots on the network and save credentials
roomba auth login

# Discover a specific IP
roomba auth login --ip 192.168.1.50

# Manually configure a robot
roomba auth login --blid ABC123 --password XYZ789 --ip 192.168.1.50

# Overwrite existing credentials
roomba auth login --force

# Check authentication status
roomba auth status
roomba auth status

# Remove all credentials
roomba auth logout

# Remove specific robot
roomba auth logout "Living Room"
```

### Robot Management

```bash
# List configured robots (JSON output)
roomba robots list

# List robots with table format
roomba robots list

# Discover robots on network (not just configured)
roomba robots list --discover

# Select specific properties
roomba robots list --properties "name,ip"

# Get details for a specific robot
roomba robots get "Living Room"
roomba robots get "Living Room"
```

### Robot Control

```bash
# Start cleaning
roomba control start "Living Room"

# Stop cleaning
roomba control stop "Living Room"

# Pause cleaning
roomba control pause "Living Room"

# Resume after pause
roomba control resume "Living Room"

# Send to dock
roomba control dock "Living Room"

# Play sound to locate robot
roomba control find "Living Room"

# Empty bin (Clean Base models only)
roomba control evac "Living Room"

# Get live status
roomba control status "Living Room"
roomba control status "Living Room"
roomba control status "Living Room" --timeout 15
```

### Profiles

```bash
# List all profiles
roomba auth profiles list

# Create a new profile
roomba auth profiles create work

# Select active profile
roomba auth profiles select work

# Delete a profile
roomba auth profiles delete work
```

### Status (Top-Level Shortcut)

```bash
# Quick status check (shortcut for 'control status')
roomba status "Living Room"
roomba status "Living Room"
```

## Output Formats

All commands support two output formats:

- **JSON** (default): Machine-readable output for scripting and piping

### JSON Output Example

```bash
roomba robots list
```
```json
[
  {
    "ip": "192.168.1.50",
    "blid": "ABC123...",
    "name": "Living Room",
    "mac": "AA:BB:CC:DD:EE:FF",
    "password": "***"
  }
]
```

### Table Output Example

```bash
roomba robots list
```
```
Name          IP              BLID
-----------------------------------------
Living Room   192.168.1.50    ABC123...
```

## Options Reference

### Global Options

| Option | Short | Description |
|--------|-------|-------------|
| `--version` | `-v` | Show version and exit |
| `--help` | | Show help message |

### List Command Options

| Option | Short | Description |
|--------|-------|-------------|
| `--limit` | `-l` | Maximum number of results (default: 100) |
| `--filter` | `-f` | Filter results (field:op:value) |
| `--properties` | `-p` | Comma-separated fields to display |
| `--discover` | `-d` | Discover robots on network |

### Control Command Options

| Option | Short | Description |
|--------|-------|-------------|
| `--timeout` | | Connection timeout in seconds (default: 10) |

### Auth Login Options

| Option | Short | Description |
|--------|-------|-------------|
| `--ip` | `-i` | Specific IP address to discover |
| `--name` | `-n` | Custom name for the robot |
| `--blid` | `-b` | Robot BLID (login) |
| `--password` | `-p` | Robot password |
| `--force` | `-F` | Overwrite existing credentials |

## Configuration

Robot credentials are stored in `~/.config/roomba/robots.json`:

```json
{
  "robots": {
    "Living Room": {
      "ip": "192.168.1.50",
      "blid": "ABC123...",
      "password": "secret..."
    }
  }
}
```

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Authentication/credential error |
| 130 | User interrupted (Ctrl+C) |

## Examples

### Get Robot Status as JSON

```bash
roomba status "Living Room" | jq '.battery_percent'
```

### Start All Configured Robots

```bash
roomba robots list | jq -r '.[].name' | while read name; do
  roomba control start "$name"
done
```

### Export Robot List

```bash
roomba robots list > my_robots.json
```

## Troubleshooting

### Robot Not Discovered

1. Ensure your Roomba is powered on and connected to WiFi
2. Make sure you're on the same network as the Roomba
3. Try specifying the IP directly: `roomba auth login --ip 192.168.1.50`
4. For password retrieval, press and hold the HOME button for 2 seconds

### Connection Timeout

Increase the timeout: `roomba status "Living Room" --timeout 20`

### Only One Connection Allowed

Roomba only allows one connection at a time. Close the iRobot app or other clients before using this CLI.

## Models

This CLI uses Pydantic models for type-safe data handling.

### Available Models

| Model | Description |
|-------|-------------|
| `RobotInfo` | Basic robot info (ip, blid, name) |
| `RobotStatus` | Live status (battery, phase, bin) |
| `RobotDetail` | Full robot details |
| `CommandResult` | Command execution result |
| `AuthStatus` | Authentication status |

### Cleaning Phases

| Phase | Description |
|-------|-------------|
| `charge` | Charging on dock |
| `run` | Cleaning |
| `stop` | Stopped |
| `pause` | Paused |
| `stuck` | Stuck |
| `hmPostMsn` | Returning to dock after mission |
| `hmMidMsn` | Returning to dock mid-mission (recharge) |
| `hmUsrDock` | Returning to dock (user requested) |
| `evac` | Emptying bin |

## Requirements

- Python 3.10+
- Dependencies (installed automatically):
  - typer
  - python-dotenv
  - pydantic
  - roombapy

## License

MIT

## Cache

```bash
roomba cache status
roomba cache clear
```

## Runtime compatibility and verification

The CLI uses the public synchronous `RoombaFactory` API and pins `roombapy==1.9.2`. Roombapy 2.x is a breaking asynchronous API; upgrading requires migrating the complete connection, discovery, callback and disconnect lifecycle together. A mismatched client import prevented startup; corrected and regression-tested on 2026-10-20.

Status requires reported battery or mission telemetry. A silent or rejected connection fails explicitly; missing battery and bin fields remain null. The timeout controls telemetry waiting, not the complete transport retry duration.

Basic command dispatch is implemented, but dispatch does not confirm execution. The legacy `rooms` and map-derived start parameters do not establish app room-selection parity. Mopping preferences, map editing/export and dock refill controls are not exposed.

## Captured app cloud reads (verified 2026-10-20)

The cloud group supports multiple vacuums in the same captured account, independently
of LAN device configuration. It never adds invented LAN addresses or replaces local
robot passwords. Import only your own authorized capture from private local storage:

```bash
roomba cloud import-capture /private/tmp/authorized-app.flows
roomba cloud robots list --table
roomba cloud robots list --filter 'sku:eq:c975020' --properties 'id,name,sku,resources'
roomba cloud select 'CLOUD_ROBOT_ID'
roomba cloud read history
roomba cloud read history --robot 'OTHER_CLOUD_ROBOT_ID'
roomba cloud read setup --robot 'CLOUD_ROBOT_ID' --timeout 15
roomba cloud read schedule
roomba cloud read entitlements
```

`import-capture` uses `uv tool run --python 3.13 --from mitmproxy==12.2.3` to
decode `.flows` in an isolated environment (first use can download the decoder).
It imports temporary AWS credentials and MQTT connection tokens from a successful observed app login,
a minimal cloud inventory, and supported successful signed GET templates whose
access key matches that login, or a captured login with the identical Cognito
identity and robot/deployment roster. Raw account passwords, robot passwords, account
profiles, and Gigya proofs are discarded. Temporary AWS credentials and MQTT connection tokens use the
CLI-tools secret manager. Minimal inventory and templates use the private CLI
profile directory, outside the repository. `--profile NAME` isolates sessions;
`import-capture --robot NAME_OR_ID` chooses an initial cloud default while retaining
all imported vacuums. Names must match unambiguously; IDs are exact.

`cloud robots list` reports imported inventory and which reads were captured for
each vacuum. It supports `--table/-t`, `--limit/-l`, `--filter/-f`, and
`--properties/-p`. `cloud select` changes only the local cloud default. Without
an explicit selection, a matching selected LAN robot is used, or the sole cloud
robot. Multiple cloud robots without a matching default require a selection.

History and setup reads are bound to their captured robot ID. Schedules and
entitlements are household/account resources and their output declares that scope.
An uncaptured resource fails explicitly; there is no endpoint guessing or regional
fallback. Requests use the exact observed host/path/query and signed header set,
with no redirects or retries. `--timeout` bounds the response wait (1–60 seconds,
default 15; connection wait is bounded at 5 seconds).

Temporary AWS/MQTT tokens expire. When a verified reusable Gigya session was
imported, cloud reads renew short-lived tokens automatically. A capture without
that reusable session works only until its temporary tokens expire. No account
password is retained. Cloud history, setup, schedules, and entitlements do not establish live
robot status, connectivity, charging, docking, or command execution. Raw command
output can contain private account/robot data; keep it out of shared files and logs.

Provenance: **Local source**, successful iRobot app capture verified 2026-10-20:
`POST /v2/login` on discovered deployment `unauth3` supplies temporary
`AccessKeyId`, `SecretKey`, `SessionToken`, `Expiration`; successful GETs establish
mission history on `auth1` and `auth3`, setup and household schedule on `auth3`,
and ecommerce entitlements on its captured service. **Upstream reverse engineering**:
[dorita980 cloud login](https://github.com/koalazak/dorita980/blob/master/bin/getPasswordCloud.js)
and [roomba-v4 credential schema](https://github.com/kilianp07/roomba-v4/blob/main/src/roomba_v4/cloud.py)
provided leads; imported credentials come from the actual app login, not a guessed
signature exchange. No proprietary API stability is promised.

Get one imported inventory entry (no network request):

```bash
roomba cloud robots get 'CLOUD_ROBOT_ID'
roomba cloud robots get 'CLOUD_ROBOT_ID' --table
```


## Read operations for each vacuum

```bash
# Merge successive private captures; account identity must be provable.
roomba cloud import-capture /private/tmp/login.flows --additional-capture /private/tmp/reads.flows
roomba cloud status --robot 'CLOUD_ROBOT_ID'
roomba cloud status --robot 'CLOUD_ROBOT_ID' --table
roomba cloud schedules --robot 'CLOUD_ROBOT_ID'
roomba cloud favorites list --robot 'CLOUD_ROBOT_ID' --table
roomba cloud favorites list --robot 'CLOUD_ROBOT_ID' --filter 'deleted:eq:false' --properties 'id,name'
roomba cloud favorites get 'FAVORITE_ID' --robot 'CLOUD_ROBOT_ID'
roomba cloud favorites get 'FAVORITE_ID' --robot 'CLOUD_ROBOT_ID' --table
roomba cloud shadow --robot 'CLOUD_ROBOT_ID'
roomba cloud shadow --robot 'COMBO_ROBOT_ID' --partition ro-currentstate
```

`cloud status` reads the verified model-specific status partitions and reports
observed battery, mission, connectivity, bin, dock, and tank values with each
field's original metadata timestamps and age. Missing fields remain unknown.
A successful broker read and a stored `connected: true` are snapshots; they do
not establish present physical connectivity. A successful GET's server timestamp
is not a robot telemetry timestamp. Error code zero is not an overall health test.

`cloud schedules` includes both the selected robot's household schedules and
stored robot schedules: Classic `cleanSchedule`/`cleanSchedule2` for R989020,
`rw-schedule` for c975020. Household membership is validated against the captured
household roster. Empty household schedules do not mean the robot has no stored
schedules. Raw robot schedule fields and metadata ages are preserved.

`cloud favorites list` filters account favorites by exact command-definition
robot IDs. It supports table, filter, limit, and properties options. Get returns
the actual favorite payload and validates selected-robot membership; no favorite
is rewritten or started. Multiple-robot favorites are marked as such.

Additional `cloud read RESOURCE --robot 'CLOUD_ROBOT_ID'` names are:

| Resource | Scope and limits |
| --- | --- |
| `robot`, `parts`, `timeline`, `history` | Exact robot path/query and observed deployment |
| `setup`, `time-estimates`, `evac-history` | Exact robot; available only when its request was captured |
| `team`, `team-report` | Exact older robot, only its captured deployment |
| `maps`, `map-version` | Robot-bound map metadata; latest captured map-version request only |
| `clean-score` | Exact observed request, re-signed only after current-account map-to-robot ownership proof |
| `settings`, `automations`, `households`, `favorites`, `ifttt`, `user-ifttt`, `entitlements` | Account data, explicitly labeled; not silently filtered to a robot |
| `schedule` | Household data bound to the selected robot's household |
| `robot-settings`, `config`, `stats`, `software` | Accepted c975020 named shadow partitions, with stored field metadata |

Examples:

```bash
roomba cloud read parts --robot 'CLOUD_ROBOT_ID'
roomba cloud read timeline --robot 'CLOUD_ROBOT_ID'
roomba cloud read robot --robot 'CLOUD_ROBOT_ID'
roomba cloud read automations
roomba cloud read households
roomba cloud read robot-settings --robot 'COMBO_ROBOT_ID'
roomba cloud read stats --robot 'COMBO_ROBOT_ID'
```

Unsupported or unbound reads fail before making a request. No static app catalog,
help content, map image/binary export, or undocumented read endpoint is added.
`ro-services` disconnected during its single bounded probe and is not exposed.
Older-robot setup and Combo-only reads are not invented for that model.

Cloud MQTT uses captured deployment routing and server-issued client ID/device
membership, verified TLS WebSockets on port 443, and exactly the three custom
authorizer headers. Each operation uses specific get accepted/rejected topics,
a correlated UUID request token, a bounded deadline, and disconnects afterward.
There are no wildcard subscriptions, automatic reconnects, background listeners,
robot commands or schedule writes. The same server-issued client ID can displace
an active phone connection. Same-profile CLI MQTT read sequences serialize across
processes and disconnect afterward.

**Local source**, verified 2026-10-20: Classic shadow GET accepted for both scoped
SKUs; c975020 accepted `ro-currentstate`, `rw-constatus`, `rw-schedule`,
`rw-settings`, `ro-configinfo`, `ro-stats`, and `rw-software`.
**Upstream reverse engineering**:
[roombapy-prime MQTT transport](https://github.com/johnnyh1975/roombapy-prime/blob/main/roombapy_prime/mqtt_client.py)
provided the Classic WebSocket/custom-authorizer and topic contract. These reads
are not a claim of complete proprietary API coverage or command compatibility.

Legacy `auth login` now uses shared prompting and the CLI secret manager for
account credentials when that existing LAN setup path needs them. Credentials
are passed to its legacy Node helper through stdin, never OS arguments.


Clean-score requests are a narrowly scoped exception to captured-key admission:
an exact observed clean-score host/path/query can be re-signed when its exact
map ID is bound to the selected robot by an account-proven maps response. This
does not assert the original request's unknown session key belongs to that account.
Other unknown-key requests remain excluded. A captured Gigya session token and
secret now provide reusable cloud login renewal; server revocation or expiration
of that underlying session requires a new authorized login capture.

Manual `device add` requires its existing explicit credential options; missing
required values fail without prompting or changing configuration. No robot motion
was used to verify this read implementation.


## Automatic cloud session renewal

```bash
roomba cloud auth-status
roomba cloud refresh
roomba cloud read history --robot 'CLOUD_ROBOT_ID'
roomba cloud status --robot 'CLOUD_ROBOT_ID'
```

Import a capture containing successful Gigya `accounts.login`, a matching signed
`accounts.getAccountInfo`, and successful iRobot `/v2/login`. The importer verifies
the captured signature before saving the reusable Gigya session token/secret in
the existing per-profile CLI secret manager. It retains neither account passwords
nor old UID login signatures. If captured AWS/MQTT tokens already expired but this
verified Gigya session remains valid, import renews them before publishing anything.
A reimport preserves a valid cloud default selection.

REST reads renew AWS credentials when expiry is within 90 seconds. MQTT reads also
check every robot's connection-token expiry/device membership. One renewal obtains
both new AWS credentials and new MQTT tokens for the same account and exact robot
SKU/deployment roster. It leaves robot selection, LAN credentials, captured request
templates, ownership and phone push registration unchanged.

Renewal signs a fresh POST `accounts.getAccountInfo` with a new timestamp/nonce,
then exchanges its fresh UID proof at `/v2/login` with ownership disabled. There is
no replay of an expired proof. The verified session uses the official
[SAP Gigya Swift SDK signing protocol](https://github.com/SAP/gigya-swift-sdk/blob/main/GigyaSwift/Global/Utils/SignatureUtils.swift).
The implementation matched all 21 applicable captured signatures before live use.

Per-profile refresh locks coalesce concurrent renewal attempts. Whole MQTT read
sequences take a separate process lock, preventing two CLI readers from evicting
each other through the shared server client ID. Lock order is consistent. Network
renewal has a 30-second deadline; lock waits are bounded at 35 seconds. A read's
own timeout applies to its operation after authentication/lock acquisition.

An identifiable REST 401/403 or MQTT CONNACK authentication rejection permits at
most one renewal and one read retry. A rejection within 30 seconds of a successful
renewal stops another login attempt. Arbitrary transport failures, including an
unclassified WebSocket upgrade failure, do not trigger login retries; use
`cloud refresh` to check the saved login separately. No mutation is retried.

`cloud auth-status` reports saved expiry and renewal readiness without contacting
the service or exposing credentials. `cloud refresh` explicitly renews both token
types. A rejected/revoked reusable Gigya session produces an instruction to sign
in to the app and import a fresh login capture. Failed proof, identity, roster,
MQTT coverage or credential-store validation preserves the previous working
credential bundle and metadata. There is no background refresh task.

Live verification renewed both token types explicitly and through an installed
read after safely marking stored expiry due. Both vacuums' REST histories and
MQTT status reads then succeeded without a new phone capture. This proves login
renewal and reads, not present robot health or successful control.

## Experimental cloud start and pause

```bash
roomba cloud start --robot "ROBOT_NAME"
roomba cloud pause --robot "ROBOT_NAME"
```

These are physical actions on the explicitly selected vacuum. `start` starts a
cleaning job and `pause` pauses it. Only these two cloud controls are exposed.
Check the app's current online state before running either command. Cached
`connected: true` and old shadow timestamps alone do not establish present
connectivity.

**Upstream reverse engineering:** the shared app command envelope is
`command`, integer Unix `time`, and `initiator: rmtApp`, published to the exact
captured deployment's `irbtTopics/things/<robot>/cmd`. Model compatibility for
these two local SKUs remains experimental until a fresh robot report confirms
an actual command. See the upstream [command evidence trail](https://github.com/johnnyh1975/roombapy-prime/blob/main/docs/internal/EVIDENCE_TRAIL.md#mqtt_clientcmd_topic).

Each command takes the profile MQTT lock, renews expiring authentication before
sending, subscribes and reads a baseline, then makes at most one nonretained
QoS1 command publish. There is no reconnect or command retry. Nonretained does
not guarantee a disconnected robot cannot receive a queued message later.
After a publish attempt, a timeout or lost connection means completion is
unknown; do not automatically repeat the command.

JSON output distinguishes `publish_attempted`, `broker_received`, and
`robot_confirmed`. Broker PUBACK is only receipt. Confirmation requires either
an exact changed `lastCommand` with fresh metadata or a fresh matching mission
phase transition (`run` for start, `stop` within an active cycle for pause).
A matching lastCommand is a robot acknowledgement, not proof of physical movement.
A preexisting matching phase never confirms a command. The total default
operation deadline is 30 seconds (`--timeout`, 1–60). An unconfirmed action
prints its structured result and exits with status 1.

**Local source, 2026-10-20:** one supervised Combo j9+ start produced a fresh
`run` report and the user observed it start. The immediately following single
pause received PUBACK; the CLI saw `refill` and returned unconfirmed. A later
read showed `none/stop`, and the user observed it stopped and returned to Ready
to vacuum. That physical observation is separate from the CLI's conservative
pause correlation. It does not justify treating arbitrary `none/stop` reports
as a confirmed pause. The older vacuum is offline by user report, so its controls were not sent or
live verified. Both explicit selectors are implemented; do not issue commands
to the offline vacuum as a connectivity test.
