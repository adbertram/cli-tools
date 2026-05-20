# cc-connect-slack-manager

Manage the always-on Cody Slack bridge powered by `cc-connect`.

The Cody bridge runs from the single Cody runtime configuration at `~/.codex/cody/configuration.json`.
That file owns the LaunchAgent label, cc-connect paths, Slack app ID, bot user ID, default user ID, DM channel ID, and Keychain service names.

## Installation

```bash
uv tool install -e <cli-tools-root>/cc-connect-slack-manager --force --refresh
```

## Commands

### auth

```bash
cc-connect-slack-manager auth status
cc-connect-slack-manager auth status --table
cc-connect-slack-manager auth test
cc-connect-slack-manager auth profiles list
cc-connect-slack-manager auth profiles get default
```

### service

```bash
cc-connect-slack-manager service status
cc-connect-slack-manager service status --table
cc-connect-slack-manager service start
cc-connect-slack-manager service stop
cc-connect-slack-manager service restart
cc-connect-slack-manager service logs
cc-connect-slack-manager service logs --stream stderr --lines 40
cc-connect-slack-manager service logs --table
```

### config

```bash
cc-connect-slack-manager config show
cc-connect-slack-manager config show --table
```

### tokens

```bash
cc-connect-slack-manager tokens status
cc-connect-slack-manager tokens status --table
```

Token values are stored in macOS Keychain and are never printed.

### app

```bash
cc-connect-slack-manager app verify
cc-connect-slack-manager app verify --table
cc-connect-slack-manager app send-test "Cody bridge test"
```

`app verify` checks that the configured Cody bot user belongs to the configured Cody Slack app.
Assistant replies should not include the cc-connect model/status footer or intermediate tool progress; `checks list` verifies quiet mode and the required display settings.

### checks

```bash
cc-connect-slack-manager checks list
cc-connect-slack-manager checks list --table
cc-connect-slack-manager checks list --limit 3
cc-connect-slack-manager checks list --filter "ok:eq:true"
cc-connect-slack-manager checks list --properties "id,ok,detail"
cc-connect-slack-manager checks get service-running
cc-connect-slack-manager checks get service-running --table
```

## Output

JSON is the default output for command composition. Use `--table` on commands that support table output.

## Models

The CLI returns Pydantic-backed models:

| Model | Purpose |
|-------|---------|
| `ActionResult` | Result from a management command |
| `ServiceStatus` | LaunchAgent status |
| `ConfigStatus` | Cody bridge paths and Slack identifiers |
| `TokenStatus` | Keychain token presence without secret values |
| `SlackVerification` | Cody Slack app identity status |
| `LogTail` | Recent log lines |
| `CheckResult` | Single health check result |

## Verification

```bash
cc-connect-slack-manager service status
cc-connect-slack-manager app verify --table
cc-connect-slack-manager checks list --table
<cli-tools-root>/skills/cli-tool/scripts/test-cli-tool.sh --cli-name cc-connect-slack-manager
```
