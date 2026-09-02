# Microworker CLI

## DESCRIPTION

Runs the per-site gig CLIs registered in the MicroWorker project's `config.json`, writes one schema-validated envelope per site per discovery run, and merges the `ok` envelopes into a durable SQLite task database. Use it when an agent or script needs a deterministic, judgment-free pass over every gig site that records which sites have no account, which have no CLI, which failed auth, and the raw tasks from the ones that answered -- and needs to know, later, when each task was first and last seen.

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
microworker runs get "$R" --table
microworker tasks list --filter "pay_amount:gte:0.50" --table
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

`merge <run_id>` requires an envelope for every site in `config.json`, validates each, maps `ok` tasks through the site adapter (`microworker_cli/adapters/<site>.py`) into the task contract (`schemas/task.schema.json`), validates every task, and only then writes -- the run row, its per-site summaries and every task upsert commit in one SQLite transaction. It is all-or-nothing: one bad envelope or task fails the whole merge and the database is left exactly as it was.

Envelopes are per-run and disposable. The database is the durable store.

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

Prints `{"run_id", "db_path", "sites": {"<site>": "<status>"}, "task_count", "inserted", "updated"}`. `task_count` counts the tasks the run merged; `inserted` and `updated` count distinct `(site, task_id)` rows written, so a run carrying the same task twice reports `task_count: 2, inserted: 1`.

Re-running `merge` for the same run id is idempotent: its `runs` and `run_sites` rows are replaced rather than duplicated, and its tasks upsert again.

### Validate

```bash
microworker validate agent_workspaces/discovery/20260902T120000Z/microworkers.json
```

Validates one site envelope against `schemas/envelope.schema.json`. Prints `{"file", "kind": "envelope", "valid": true}` on success; exits 2 with the jsonschema message otherwise. There is no merged file to validate -- merged tasks live in the database, and each one is validated against the task contract on the way in.

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

### Tasks

```bash
microworker tasks list
microworker tasks list --table
microworker tasks list --filter "site:eq:microworkers" --filter "pay_amount:gte:0.25"
microworker tasks list --limit 20 --properties "site,task_id,title,pay_amount"
microworker tasks get microworkers 1974e4b177d2
microworker tasks get microworkers 1974e4b177d2 --table
microworker tasks get microworkers 1974e4b177d2 --properties "url,last_seen_at"
```

One row per `(site, task_id)`, newest `last_seen_at` first. In JSON, `raw` is the parsed site record; in table output `raw` is dropped, because a nested object has no readable cell.

`tasks get` exits 2 when the `(site, task_id)` pair is not in the database.

### Runs

```bash
microworker runs list
microworker runs list --table
microworker runs list --filter "task_count:gt:0" --limit 10
microworker runs list --properties "run_id,merged_at,task_count"
microworker runs get 20260902T120000Z
microworker runs get 20260902T120000Z --table
```

One row per recorded merge, newest `merged_at` first. `runs get` adds a `sites` object keyed by site, each carrying `{status, error, fetched_at, task_count}` from that run's envelope. An unknown run id exits 2.

Every query command reads through a `mode=ro` SQLite connection, so no read can write. A query against a database that does not exist yet exits 2 naming the path and telling you to run a merge; it never returns an empty list, because "nothing has been merged" and "no tasks are open" are different facts.

## The Task Database

`<project_root>/data/tasks.db` (`data/` is created on first merge). Schema version 1, recorded in `meta`.

```sql
CREATE TABLE tasks (
    site TEXT NOT NULL,
    task_id TEXT NOT NULL,
    title TEXT,
    url TEXT,
    pay_amount,                    -- no declared type: keeps REAL/INTEGER affinity
    pay_currency TEXT,
    est_minutes INTEGER,
    slots_open INTEGER,
    expires_at TEXT,
    raw TEXT NOT NULL,             -- the site record, as JSON
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    first_seen_run_id TEXT NOT NULL,
    last_seen_run_id TEXT NOT NULL,
    PRIMARY KEY (site, task_id)
);
CREATE TABLE runs (
    run_id TEXT PRIMARY KEY,
    merged_at TEXT NOT NULL,
    task_count INTEGER NOT NULL,
    inserted INTEGER NOT NULL,
    updated INTEGER NOT NULL
);
CREATE TABLE run_sites (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    site TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    fetched_at TEXT NOT NULL,
    task_count INTEGER NOT NULL,
    PRIMARY KEY (run_id, site)
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX idx_tasks_site ON tasks(site);
CREATE INDEX idx_tasks_last_seen_run_id ON tasks(last_seen_run_id);
CREATE INDEX idx_tasks_pay_amount ON tasks(pay_amount);
```

Seeing a task again refreshes every contract column plus `last_seen_at` and `last_seen_run_id`; `first_seen_at` and `first_seen_run_id` are written once by the insert that creates the row and are never overwritten. Both timestamps take the run's `merged_at`. There is no per-run task-membership table and no append-per-sighting history: one row per `(site, task_id)` is the whole model.

`microworker_cli/db.py` is the only module that opens the database, and `paths.db_path()` is the only place that names it. `PRAGMA journal_mode=WAL` and `PRAGMA foreign_keys=ON` are set on every write connection.

## Output Formats

- JSON is the default output format.
- Add `--table` / `-t` for human-readable table output on every `list` and `get` command.

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

Every task an adapter produces has exactly: `site`, `task_id`, `title`, `url`, `pay_amount`, `pay_currency`, `est_minutes`, `slots_open`, `expires_at`, `raw`. Unknown values are `null`; `raw` is the untouched site record. `tasks list` and `tasks get` return those ten fields plus the four the database adds: `first_seen_at`, `last_seen_at`, `first_seen_run_id`, `last_seen_run_id`.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success (including every recorded envelope status from `discover`) |
| 1 | Unexpected error |
| 2 | Config error (`config.json` shape, unknown site) or contract error (schema validation, missing envelopes, adapter failure, missing database, unknown task or run) |
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

`MICROWORKER_ROOT` overrides the project root, which is where both `config.json` and `data/tasks.db` live (tests point it at a temp directory). Non-authentication configuration for this wrapper lives in `~/.local/share/cli-tools/microworker/.env`; the source repo only carries `.env.example`. This CLI holds no credentials: each site CLI owns its own auth profile, and reusable human-supplied secrets belong in the CLI-tools secret manager (`<cli-tools-root>/_repo/_secret-manager/secrets.sh`), never in any `.env` file.

## Testing

```bash
cd <cli-tools-root>/_personal/microworker
uv run --with pytest python -m pytest tests
<cli-tools-root>/_repo/skills/cli-tool/scripts/test-cli-tool.sh --cli-name microworker
```

The unit suite never touches the real project or the real database: every test sets `MICROWORKER_ROOT` to a temp directory with a fixture `config.json`, so `data/tasks.db` is created under that temp root too. `discover` runs against a scripted fake of `runner.run`, and `envelope.utc_now()` is put under test control by the `clock` fixture so first-seen and last-seen timestamps are distinguishable.
