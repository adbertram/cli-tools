# Microworker CLI

## DESCRIPTION

Runs the per-site gig CLIs registered in the MicroWorker project's `config.json`, writes one schema-validated envelope per site per discovery run, and merges the `ok` envelopes into a durable SQLite task database. Use it when an agent or script needs a deterministic, judgment-free pass over every gig site that records which sites have no account, which have no CLI, which failed auth, and the raw tasks from the ones that answered -- and needs to know, later, when each task was first and last seen.

## Prerequisites

- The MicroWorker project at `/Users/adam/Dropbox/GitRepos/Agents/MicroWorker` (override with `MICROWORKER_ROOT`), holding `config.json`.
- The site CLIs named in `config.json` installed on `PATH` (`microworkers`, `oneforma`, `humanrail`, `outlier`, `mercor`, `trainee-digital`, `atlas-capture`, `crowdgen`). Each owns its own authentication; this CLI only runs `<cli> auth status`, the configured `auth_command`, and `<cli> tasks list`.

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

`config.json` has a `sites` object; every entry carries exactly `cli` (string or null), `account` (bool), `lastpass_item` (string or null), `auth_command` (string or null) and `disabled` (bool). A missing, extra or mistyped key is a `ConfigError` (exit 2); nothing is defaulted, and a `config.json` that is not parseable JSON is a `ConfigError` naming the path and the decode position.

`disabled: true` is the deterministic off-switch for a site's worker. A discovery run skips disabled sites entirely: `discover` refuses them (exit 2, no envelope), `merge` neither expects nor accepts their envelopes, and the roster query the discovery agent drives is `microworker sites list --filter disabled:eq:false --properties name` so no disabled worker is ever spawned. Re-enabling is editing `config.json` back to `disabled: false` -- no agent or code change.

A **run id** is a UTC timestamp of the form `20260902T140000Z` -- exactly what `date -u +%Y%m%dT%H%M%SZ` produces -- and a **site name** is one lowercase segment matching `^[a-z0-9][a-z0-9-]*$`. Both are interpolated into filesystem paths, so both are validated in `paths.py` and every constructed path is asserted to resolve under the project root. Anything else exits 2 and writes nothing.

`discover <site>` follows a fixed decision table with no model judgment:

| Step | Condition | Envelope status |
|------|-----------|-----------------|
| 1 | site not in `config.json` | `ConfigError`, exit 2, no envelope written |
| 1b | `disabled: true` | `ConfigError`, exit 2, no envelope written |
| 2 | `account: false` | `no_account` |
| 3 | `cli: null` | `no_cli` |
| 4 | `<cli> auth status` exits 0 | continue |
| 4 | exits 2 | run `auth_command` once, re-check; still 2 → `auth_failed` (login stderr recorded) |
| 4 | any other exit | `error` |
| 5 | `<cli> tasks list` exits 0 and prints a JSON list | `ok`, `tasks` = the raw list untouched |
| 5 | non-zero exit, non-JSON stdout, non-list JSON, timeout, missing executable | `error` |

`tasks` is `[]` for every status but `ok`; `error` is `null` only for `ok`. Envelopes land at `<root>/agent_workspaces/discovery/<run_id>/<site>.json` and are validated against `microworker_cli/schemas/envelope.schema.json` before they are written.

Every JSON boundary is strict. Python's `json` accepts and emits `NaN`, `Infinity` and `-Infinity`, none of which are JSON, and silently turns an overflowing literal such as `1e999` into infinity. A site CLI that prints any of them gets an `error` envelope naming the literal; envelope files and the stored `raw` column are written with `allow_nan=False`; and `validate_task` rejects a non-finite number anywhere in the record, `raw` included. Without that, a NaN price binds to SQLite as SQL NULL, so a task the site priced reads back as `pay_amount: null` with its currency still attached, and an Infinity in the ledger makes `tasks list` emit output that strict JSON parsers reject.

`merge <run_id>` requires the run directory to hold an envelope for every ENABLED site in `config.json` (disabled sites are skipped: no envelope exists or is expected) **and no `*.json` for anything else**, validates each, maps `ok` tasks through the site adapter (`microworker_cli/adapters/<site>.py`) into the task contract (`schemas/task.schema.json`), validates every task, checks the run's tasks are unique by `(site, task_id)`, and only then writes -- the run row, its per-site summaries and every task upsert commit in one SQLite transaction. It is all-or-nothing: one bad envelope or task fails the whole merge and the database is left exactly as it was.

The envelope set is checked in both directions on purpose. Requiring one per enabled site catches a worker that never ran; rejecting a stray or misnamed `<site>.json` (e.g. `microworkers2.json`, or a disabled site's leftover envelope) catches the opposite mistake, which would otherwise contribute nothing, get no `run_sites` row and let the run exit 0 as though it had been complete.

Two records mapping to the same `(site, task_id)` inside ONE run is a contradiction, not a re-sighting, and is rejected before the transaction opens -- naming the envelope and both record indexes. Left alone, the upsert would let the later record silently overwrite the earlier one and report more tasks than rows.

A task id must be a JSON string or integer. `str(value)` accepts everything, so a guard on the stringified value lets JSON `true` through as the id `"True"` and a JSON object through as `"{'oops': 1}"` -- a Python repr that exists nowhere on the site. The type is therefore checked before the stringify (`adapters/ids.py`), the id is stripped and must be non-empty, and it may be at most 200 characters.

Envelopes are per-run and disposable. The database is the durable store.

Adapters exist for every `config.json` site: `microworkers`, `oneforma`, `humanrail`,
`outlier`, `mercor` and `trainee-digital` implement real mappings; `atlas-capture` and
`crowdgen` raise a `ClientError` until a real `ok` record shape is observed for them
(a contract failure of the merge, so exit 2, not the exit 1 a bare `NotImplementedError`
would produce). An `ok` envelope for a site without an adapter fails the merge.

## Commands

### Discover

```bash
microworker discover microworkers --run-id 20260902T120000Z
microworker discover outlier --run-id 20260902T120000Z --timeout 120
```

Prints `{"site", "status", "path", "task_count"}` and exits 0 for every recorded status; only a config error exits non-zero.

### Merge

```bash
microworker merge 20260902T120000Z
```

Prints `{"run_id", "db_path", "sites": {"<site>": "<status>"}, "unparsed_payments": {"<site>": <count>}, "task_count", "inserted", "updated", "skipped_stale"}`. `task_count` counts the tasks the run merged, and the other three partition exactly those tasks:

| Count | Meaning |
|-------|---------|
| `inserted` | the `(site, task_id)` was not in the database |
| `updated` | the row existed and this sighting was at least as fresh, so its contract columns were refreshed |
| `skipped_stale` | the row existed and this sighting was OLDER than the stored `last_seen_at`, so the contract columns were left alone (only `first_seen_at` could move) |

`skipped_stale` exists because reporting a skipped sighting as `updated` would claim a change that never happened, and reporting it as `inserted` would be plainly false. The three always sum to `task_count`, because a run's tasks are unique by `(site, task_id)`.

Re-running `merge` for the same run id is idempotent: its `runs` and `run_sites` rows are replaced rather than duplicated, and its tasks upsert again (the observation is exactly as fresh, so it counts as `updated`).

#### Prices the adapter could not read

`unparsed_payments` is keyed by every configured site and counts that site's tasks in this run whose published price its adapter could not parse. `pay_amount`/`pay_currency` stay `null` for those tasks -- a price is never invented, and no regex is widened to swallow a format nobody has seen live -- but "the site published no price" and "the site published a price I could not read" are different facts, and they must not both read as an unpriced task.

Without this count, a site changing its price format (`$1.50` to `$1.5`, or `USD 1.00`) stores every price as `null`, exits 0, and quietly drops those tasks out of `microworker tasks list --filter "pay_amount:gte:0"` -- a gap that can sit there for months.

A site whose payment field is absent from a record is a hard error (every adapter lists it in `RAW_KEYS`); an explicit `null` or a blank string is the site publishing nothing, and is not counted. When any site has a nonzero count, `merge` also prints a `Warning:` line naming those sites to stderr; stdout stays data only.

```bash
microworker merge 20260902T120000Z
# {"run_id": "...", "unparsed_payments": {"microworkers": 2, "oneforma": 0, ...}, ...}
# Warning: Unparsed payments (price published, adapter could not read it): microworkers=2. ...
```

The counts are also stored on the run: `microworker runs get <run_id>` reads them back per site, so "when did this start?" is answerable months later rather than only from the stdout of the run that first hit it.

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

Rows are `{name, cli, account, lastpass_item, auth_command, disabled}` straight from `config.json`. Filter for the runnable roster with `--filter disabled:eq:false`.

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

`--limit` defaults to 100. When it truncates the result, the pre-limit total goes to **stderr** (`Showing 100 of 2000 tasks (--limit 100); raise --limit for the rest.`) so a partial answer can never be mistaken for a complete one. stdout stays data only, so piping into `jq` is unaffected.

### Runs

```bash
microworker runs list
microworker runs list --table
microworker runs list --filter "task_count:gt:0" --limit 10
microworker runs list --properties "run_id,merged_at,task_count"
microworker runs get 20260902T120000Z
microworker runs get 20260902T120000Z --table
```

One row per recorded merge, newest `merged_at` first. `runs get` adds a `sites` object keyed by site, each carrying `{status, error, fetched_at, task_count, unparsed_payments}` from that run's envelope and mapping. An unknown run id exits 2. A `null` `unparsed_payments` means the run was merged under schema version 2, before unreadable prices were counted at all.

Every query command reads through a `mode=ro` SQLite connection, so no read can write. A query against a database that does not exist yet exits 2 naming the path and telling you to run a merge; it never returns an empty list, because "nothing has been merged" and "no tasks are open" are different facts. A database the SQLite engine itself refuses -- a file that is not a database, or a stale `-wal` beside a read-only `data/` -- is also exit 2 naming the path, rather than an unwrapped `sqlite3` error at exit 1.

### Field names are validated

`--filter` and `--properties` are both checked against the exact columns the command's rows carry, and an unknown name exits 2 listing the real fields. Both options otherwise fail silently in opposite directions: a misspelled filter field returns `[]` with exit 0, so "that field does not exist" is indistinguishable from "no task matched"; and a misspelled property is emitted as `null` on every row, so a typo reads as "the field exists and is empty".

```bash
microworker tasks list --filter "pay_amout:gt:1"
# Error: Field 'pay_amout' is not filterable. Supported fields: est_minutes, expires_at, ...
microworker tasks list --properties "task_id,pay_amout"
# Error: --properties names no such field: pay_amout; available fields: site, task_id, ...
```

A real field whose value is `null` still projects as `null` -- the allowlist rejects typos, it does not hide data. Note that the shared filter operators are non-null comparisons, so a row whose field is `NULL` is dropped by `eq`, `gt`, `contains` and the rest; use `--filter "<field>:null:"` or `:notnull:` to ask about presence.

Only the first dotted segment of a `--properties` name is checked, so `runs get --properties "sites.microworkers"` still works: the top-level names are fixed columns, while the keys beneath `sites` are data.

## The Task Database

`<project_root>/data/tasks.db` (`data/` is created on first merge). Schema version 3, recorded in `meta`. Older databases are migrated in place on the next write connection, and each migration backfills only what is factually known:

- version 1 -> 2: `runs.skipped_stale` is added with a backfill of 0, a fact rather than a default -- under version 1 every sighting was applied unconditionally, so no version-1 run skipped anything.
- version 2 -> 3: `run_sites.unparsed_payments` is added NULLABLE with no default. The `NULL` left on every version-2 row is the same kind of fact: nothing counted unreadable prices back then, so those counts are unknown. A backfilled 0 would assert that no old run ever hit an unparseable price, which is exactly the claim this column exists to stop the tool from making.

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
    merged_at TEXT NOT NULL,   -- the merge wallclock, NOT an observation time
    task_count INTEGER NOT NULL,
    inserted INTEGER NOT NULL,
    updated INTEGER NOT NULL,
    skipped_stale INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE run_sites (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    site TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    fetched_at TEXT NOT NULL,
    task_count INTEGER NOT NULL,
    unparsed_payments INTEGER,     -- NULL only on rows merged before version 3
    PRIMARY KEY (run_id, site)
);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE INDEX idx_tasks_site ON tasks(site);
CREATE INDEX idx_tasks_last_seen_run_id ON tasks(last_seen_run_id);
CREATE INDEX idx_tasks_pay_amount ON tasks(pay_amount);
```

**Seen timestamps are observation times, not merge times.** A task's `first_seen_at`/`last_seen_at` come from its envelope's `fetched_at` -- when that site's CLI actually answered. Only `runs.merged_at` is the merge wallclock. Binding both to the merge clock is wrong twice over: two sightings months apart would get identical timestamps, and merges do not have to run in observation order.

**A stale sighting cannot overwrite fresher data.** The upsert compares `excluded.last_seen_at` against the stored `last_seen_at` per column, so merging January's run after September's cannot rewrite September's title, price or slot count; `first_seen_at` is a `min()`, so the older sighting still widens the row backwards and `first_seen_run_id` follows it. `first_seen_at` can therefore never end up after `last_seen_at`. An equally fresh sighting (same `fetched_at`) is applied, which is what keeps re-merging a run id idempotent.

There is no per-run task-membership table and no append-per-sighting history: one row per `(site, task_id)` is the whole model.

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
    "auth_command": "microworkers auth login --credential-type browser_session",
    "disabled": false
  }
]
```

### Envelope Example

```json
{
  "site": "crowdgen",
  "status": "no_account",
  "fetched_at": "2026-09-02T12:00:00Z",
  "error": "config.json marks this site account=false",
  "tasks": []
}
```

### Task Contract

Every task an adapter produces has exactly: `site`, `task_id`, `title`, `url`, `pay_amount`, `pay_currency`, `est_minutes`, `slots_open`, `expires_at`, `raw`. Unknown values are `null`; `raw` is the untouched site record. `tasks list` and `tasks get` return those ten fields plus the four the database adds: `first_seen_at`, `last_seen_at`, `first_seen_run_id`, `last_seen_run_id`.

`task_id` must come from a JSON string or integer in the site's record (`adapters/ids.py`), stripped, non-empty, and at most 200 characters. Every number in the record -- `raw` included -- must be finite.

An adapter returns that record inside a `MappedTask` (`adapters/mapped.py`): the task, plus whether the site published a price the adapter could not read. That second fact is an observation about the mapping, not a property of the task, so it is not a contract field, not a `tasks` column, and never smuggled through `raw` -- `merge` sums it per site into `unparsed_payments`.

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success (including every recorded envelope status from `discover`) |
| 1 | Unexpected error |
| 2 | Config error (`config.json` shape or JSON syntax, unknown site) or contract error (schema validation, non-finite number, missing/stray envelopes, duplicate task id in a run, invalid run id or site name, adapter failure, unreadable or missing database, unknown task or run, unknown `--filter`/`--properties` field) |
| 130 | User interrupted (Ctrl+C) |

## Options Reference

| Option | Short | Description |
|--------|-------|-------------|
| `--table` | `-t` | Display data as a table |
| `--limit` | `-l` | Maximum number of results |
| `--filter` | `-f` | Filter results using `field:op:value` syntax |
| `--properties` | `-p` | Restrict output to selected fields |
| `--run-id` |  | Discovery run identifier, `YYYYMMDDTHHMMSSZ` (`discover`) |
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

The unit suite never touches the real project or the real database: every test sets `MICROWORKER_ROOT` to a temp directory with a fixture `config.json`, so `data/tasks.db` is created under that temp root too. `discover` runs against a scripted fake of `runner.run`, and `envelope.utc_now()` is put under test control by the `clock` fixture so first-seen and last-seen timestamps are distinguishable -- `tests/test_seen_timestamps.py` drives the envelope clock and the merge clock apart to prove they are separate facts.
