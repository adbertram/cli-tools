# Microworker CLI

## DESCRIPTION

Runs the per-site gig CLIs registered in the MicroWorker project's `config.json`, writes one schema-validated envelope per site per discovery run, and merges the `ok` envelopes into a single task list. Use it when an agent or script needs a deterministic, judgment-free pass over every gig site that records which sites have no account, which have no CLI, which failed auth, and the raw tasks from the ones that answered.

## Prerequisites

- The MicroWorker project at `/Users/adam/Dropbox/GitRepos/Agents/MicroWorker` (override with `MICROWORKER_ROOT`), holding `config.json`.
- The site CLIs named in `config.json` installed on `PATH` (`microworkers`, `taskerdata`). Each owns its own authentication; this CLI only runs `<cli> auth status`, the configured `auth_command`, and `<cli> tasks list`.

## Installation

```bash
cd <cli-tools-root>/_personal/microworker
uv tool install -e . --force --refresh
```

After installation, the `microworker` command will be available in your terminal.

## Quick Start

```bash
R=$(date -u +%Y%m%dT%H%M%SZ)
for s in $(microworker sites list --properties name | jq -r '.[].name'); do
  microworker discover "$s" --run-id "$R"
done
microworker merge "$R"
microworker validate "$MICROWORKER_ROOT/agent_workspaces/discovery/$R/merged.json"
```

## How It Works

`config.json` has a `sites` object; every entry carries exactly `cli` (string or null), `account` (bool), `lastpass_item` (string or null) and `auth_command` (string or null). A missing, extra or mistyped key is a `ConfigError` (exit 2); nothing is defaulted.

`discover <site>` follows a fixed decision table with no model judgment:

| Step | Condition | Envelope status |
|------|-----------|-----------------|
| 1 | site not in `config.json` | `ConfigError`, exit 2, no envelope written |
| 2 | `account: false` | `no_account` |
| 3 | `cli: null` | `no_cli` |
| 4 | `<cli> auth status` exits 0 | continue |
| 4 | exits 2 | run `auth_command` once, re-check; still 2 → `auth_failed` (login stderr recorded) |
| 4 | any other exit | `error` |
| 5 | `<cli> tasks list` exits 0 and prints a JSON list | `ok`, `tasks` = the raw list untouched |
| 5 | non-zero exit, non-JSON stdout, non-list JSON, timeout, missing executable | `error` |

`tasks` is `[]` for every status but `ok`; `error` is `null` only for `ok`. Envelopes land at `<root>/agent_workspaces/discovery/<run_id>/<site>.json` and are validated against `microworker_cli/schemas/envelope.schema.json` before they are written.

`merge <run_id>` requires an envelope for every site in `config.json`, validates each, maps `ok` tasks through the site adapter (`microworker_cli/adapters/<site>.py`) into the task contract (`schemas/task.schema.json`), validates every task, then writes and validates `merged.json` (`schemas/merged.schema.json`). It is all-or-nothing: one bad envelope or task fails the whole merge and writes nothing.

Adapters exist for `microworkers` (implemented) and `taskerdata` (raises `NotImplementedError` until a real `ok` record shape is observed). An `ok` envelope for a site without an adapter fails the merge.

## Commands

### Discover

```bash
microworker discover microworkers --run-id 20260902T120000Z
microworker discover taskerdata --run-id 20260902T120000Z --timeout 120
```

Prints `{"site", "status", "path", "task_count"}` and exits 0 for every recorded status; only a config error exits non-zero.

### Merge

```bash
microworker merge 20260902T120000Z
```

Prints `{"run_id", "merged_path", "sites": {"<site>": "<status>"}, "task_count"}`.

### Validate

```bash
microworker validate agent_workspaces/discovery/20260902T120000Z/microworkers.json
microworker validate agent_workspaces/discovery/20260902T120000Z/merged.json
```

Autodetects envelope (`site` + `status`) versus merged (`run_id` + `sites`) from the top-level keys. Prints `{"file", "kind", "valid": true}` on success; exits 2 with the jsonschema message otherwise.

### Sites

```bash
microworker sites list
microworker sites list --table
microworker sites list --filter "account:eq:true" --limit 5
microworker sites list --properties "name,cli,auth_command"
microworker sites get microworkers
microworker sites get microworkers --table
microworker sites get microworkers --properties "cli,lastpass_item"
```

Rows are `{name, cli, account, lastpass_item, auth_command}` straight from `config.json`.

## Output Formats

- JSON is the default output format.
- Add `--table` / `-t` for human-readable table output on `sites list` and `sites get`.

### JSON Output Example

```bash
microworker sites list --limit 1
```

```json
[
  {
    "name": "microworkers",
    "cli": "microworkers",
    "account": true,
    "lastpass_item": "Microworkers",
    "auth_command": "microworkers auth login --credential-type browser_session"
  }
]
```

### Envelope Example

```json
{
  "site": "taskerdata",
  "status": "auth_failed",
  "fetched_at": "2026-09-02T12:00:00Z",
  "error": "`taskerdata auth login --credential-type browser_session` exited 1 and `taskerdata auth status` still exits 2: ...",
  "tasks": []
}
```

### Task Contract

Every merged task has exactly: `site`, `task_id`, `title`, `url`, `pay_amount`, `pay_currency`, `est_minutes`, `slots_open`, `expires_at`, `raw`. Unknown values are `null`; `raw` is the untouched site record.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success (including every recorded envelope status from `discover`) |
| 1 | Unexpected error |
| 2 | Config error (`config.json` shape, unknown site) or contract error (schema validation, missing envelopes, adapter failure) |
| 130 | User interrupted (Ctrl+C) |

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display data as a table |
| `--limit` | `-l` | Maximum number of results |
| `--filter` | `-f` | Filter results using `field:op:value` syntax |
| `--properties` | `-p` | Restrict output to selected fields |
| `--run-id` |  | Discovery run identifier (`discover`) |
| `--timeout` |  | Seconds allowed per site CLI command (`discover`, default 300) |
| `--version` | `-v` | Show version and exit |

## Configuration

`MICROWORKER_ROOT` overrides the project root (tests point it at a temp directory). Non-authentication configuration for this wrapper lives in `~/.local/share/cli-tools/microworker/.env`; the source repo only carries `.env.example`. This CLI holds no credentials: each site CLI owns its own auth profile, and reusable human-supplied secrets belong in the CLI-tools secret manager (`<cli-tools-root>/_repo/_secret-manager/secrets.sh`), never in any `.env` file.

## Testing

```bash
cd <cli-tools-root>/_personal/microworker
uv run --with pytest python -m pytest tests
<cli-tools-root>/_repo/skills/cli-tool/scripts/test-cli-tool.sh --cli-name microworker
```

The unit suite never touches the real project: every test sets `MICROWORKER_ROOT` to a temp directory with a fixture `config.json`, and `discover` runs against a scripted fake of `runner.run`.
