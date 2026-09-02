"""The durable task store: `<project_root>/data/tasks.db`, and nothing else.

Site envelopes are per-run and disposable; this database is what survives them.
`merge` folds each run's envelopes into it, so a task discovered in March and
seen again in September is ONE row that remembers both dates, not two files an
agent has to reconcile.

ONE ROW PER `(site, task_id)`. There is no per-run membership table and no
append-per-sighting history: a sighting refreshes the contract columns plus
`last_seen_at`/`last_seen_run_id`, and widens `first_seen_at` backwards. That is
the whole of the history this store keeps, and it is deliberate -- "what is open
right now, and how long has it been around" is the question the discovery
pipeline actually asks.

OBSERVATION TIME, NOT MERGE TIME. A task's `first_seen_at`/`last_seen_at` are
its envelope's `fetched_at`: the moment the site's CLI actually answered.
`runs.merged_at` is the wallclock of the merge itself. Those are different
facts and merges do not have to run in observation order -- an old run can be
merged today -- so binding both to the merge clock is wrong twice over: two
sightings months apart get identical timestamps, and a January run merged after
a September run leaves `first_seen_run_id` chronologically AFTER
`last_seen_run_id`.

SIGHTINGS ARE APPLIED BY AGE, NOT BY ARRIVAL. The upsert's `DO UPDATE` compares
`excluded.last_seen_at` with the stored `last_seen_at` per column, so merging an
older run cannot overwrite a fresher title, price or slot count; it can only
widen `first_seen_at` (a `min()`) backwards. A sighting that loses that
comparison is counted as `skipped_stale`, not `updated`: the row was matched and
deliberately left alone, which is neither an insert nor a write, and reporting
it as `updated` would claim a change that never happened.

THIS MODULE IS THE ONLY PLACE THAT OPENS THE DATABASE. `paths.db_path()` is the
only place that names it. Writes go through a write-capable connection under
`BEGIN IMMEDIATE` with an explicit COMMIT/ROLLBACK, so a crashed merge leaves
the previous run intact rather than half of two runs. Reads go through a
separate `mode=ro` URI connection: read-only is enforced by the SQLite engine,
below the SQL grammar, so no query command can write no matter what it is handed.

A read against a database that does not exist is a `ClientError` naming the
path, never an empty list. An empty list would read as "no tasks are open",
which is a different fact from "nothing has ever been merged". A read that the
engine itself refuses -- a stale `-wal` beside a read-only `data/`, a file that
is not a database -- is a `ClientError` naming the path too, because a bare
`sqlite3.Error` escapes the CLI's contract-error handler, exits 1 instead of the
documented 2, and names nothing.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from cli_tools_shared.exceptions import ClientError

from . import jsonio, paths

SCHEMA_VERSION = 2
READONLY_TIMEOUT_SECONDS = 1.0

# The task contract's columns, in contract order. `raw` is stored as JSON text
# and comes back parsed, so a reader never sees the serialization.
CONTRACT_COLUMNS = (
    "site", "task_id", "title", "url", "pay_amount", "pay_currency",
    "est_minutes", "slots_open", "expires_at", "raw",
)
# Bookkeeping columns this module owns; adapters never produce them.
SEEN_COLUMNS = (
    "first_seen_at", "last_seen_at", "first_seen_run_id", "last_seen_run_id",
)
TASK_COLUMNS = CONTRACT_COLUMNS + SEEN_COLUMNS
RUN_COLUMNS = ("run_id", "merged_at", "task_count", "inserted", "updated",
               "skipped_stale")
RUN_SITE_COLUMNS = ("status", "error", "fetched_at", "task_count")

# Columns a fresher sighting refreshes. `first_seen_at`/`first_seen_run_id` are
# excluded because they move by their own rule (oldest wins, in either
# direction), and `site`/`task_id` are the key.
REFRESHED_COLUMNS = tuple(
    column for column in TASK_COLUMNS
    if column not in ("site", "task_id", "first_seen_at", "first_seen_run_id"))

# `pay_amount` is declared with NO datatype on purpose. A `TEXT` affinity would
# store 4.5 as '4.5' and break every numeric comparison; BLOB affinity keeps the
# REAL/INTEGER the adapter produced exactly as it produced it.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    site TEXT NOT NULL,
    task_id TEXT NOT NULL,
    title TEXT,
    url TEXT,
    pay_amount,
    pay_currency TEXT,
    est_minutes INTEGER,
    slots_open INTEGER,
    expires_at TEXT,
    raw TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    first_seen_run_id TEXT NOT NULL,
    last_seen_run_id TEXT NOT NULL,
    PRIMARY KEY (site, task_id)
);
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    merged_at TEXT NOT NULL,
    task_count INTEGER NOT NULL,
    inserted INTEGER NOT NULL,
    updated INTEGER NOT NULL,
    skipped_stale INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS run_sites (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    site TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    fetched_at TEXT NOT NULL,
    task_count INTEGER NOT NULL,
    PRIMARY KEY (run_id, site)
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_site ON tasks(site);
CREATE INDEX IF NOT EXISTS idx_tasks_last_seen_run_id ON tasks(last_seen_run_id);
CREATE INDEX IF NOT EXISTS idx_tasks_pay_amount ON tasks(pay_amount);
"""

# Schema-version 1 databases predate `runs.skipped_stale`. `CREATE TABLE IF NOT
# EXISTS` will not add a column to a table that already exists, so the column is
# added here. The backfilled 0 is a fact, not a default: under version 1 every
# sighting was applied unconditionally, so no version-1 run skipped anything.
MIGRATIONS = (
    ("runs", "skipped_stale",
     "ALTER TABLE runs ADD COLUMN skipped_stale INTEGER NOT NULL DEFAULT 0"),
)

_UPSERT_TASK = """
INSERT INTO tasks ({columns}) VALUES ({placeholders})
ON CONFLICT(site, task_id) DO UPDATE SET {updates}
""".format(
    columns=", ".join(TASK_COLUMNS),
    placeholders=", ".join("?" for _ in TASK_COLUMNS),
    # Every refreshed column is guarded by the same comparison, rather than a
    # single WHERE on the DO UPDATE: a stale sighting must still be able to move
    # `first_seen_at` backwards, and a statement-level WHERE would skip that too.
    # `>=` so re-merging the same run id still refreshes (its observation is
    # exactly as fresh), while a strictly older observation changes nothing.
    updates=", ".join(
        [f"{column} = CASE WHEN excluded.last_seen_at >= tasks.last_seen_at "
         f"THEN excluded.{column} ELSE tasks.{column} END"
         for column in REFRESHED_COLUMNS]
        + [
            "first_seen_at = min(tasks.first_seen_at, excluded.first_seen_at)",
            "first_seen_run_id = CASE WHEN excluded.first_seen_at < "
            "tasks.first_seen_at THEN excluded.first_seen_run_id "
            "ELSE tasks.first_seen_run_id END",
        ]),
)


def connect() -> sqlite3.Connection:
    """The write-capable connection. Creates `data/`, the file and the schema."""
    path = paths.db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA_SQL)
    _migrate(conn)
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES ('schema_version', ?)",
        (str(SCHEMA_VERSION),))
    conn.commit()
    return conn


def connect_readonly() -> sqlite3.Connection:
    """A connection SQLite itself will not let anything write through.

    `mode=ro` is enforced by the engine, so it holds for every statement form,
    including the CTE-prefixed `WITH x AS (...) DELETE FROM tasks` that a
    string prefix test would wave through. The path becomes a URI via
    `Path.as_uri()` so a space or `?` in a directory name cannot break it.
    """
    path = paths.db_path()
    if not path.is_file():
        raise ClientError(
            f"no task database at {path}; run a discovery merge "
            "(`microworker merge <run_id>`) to create it")
    try:
        conn = sqlite3.connect(
            path.as_uri() + "?mode=ro", uri=True, timeout=READONLY_TIMEOUT_SECONDS)
    except sqlite3.Error as exc:
        raise ClientError(f"cannot open the task database at {path}: {exc}") from exc
    conn.row_factory = sqlite3.Row
    return conn


def write_run(run_id: str, merged_at: str, site_summaries: dict[str, dict],
              tasks: list[dict]) -> dict:
    """Upsert one merge: the run row, its per-site summaries, and its tasks.

    Every task must already satisfy `task.schema.json`, and the run's tasks must
    already be unique by `(site, task_id)`; `merge.merge()` enforces both as it
    maps them, where the envelope path and record index are still in hand to name
    in the error. This function is reached only after all of that passed, so the
    single transaction below either lands the whole run or none of it.

    Each task's seen timestamps come from its own site's envelope `fetched_at`
    in `site_summaries` -- the observation time. `merged_at` is the merge
    wallclock and stamps only the `runs` row.

    Re-merging a run id is idempotent for the run's own bookkeeping: its
    `run_sites` rows are deleted and its `runs` row replaced rather than
    duplicated. The tasks simply upsert again.

    Returns `{"task_count", "inserted", "updated", "skipped_stale"}`.
    `task_count` counts the tasks the run merged; the other three partition
    those tasks by what the write did with each one.
    """
    conn = connect()
    try:
        # BEGIN IMMEDIATE, not the deferred transaction `with conn` opens: the
        # existing-row read below decides the counts, and it is only true if it
        # and the write share one exclusive transaction.
        conn.isolation_level = None
        conn.execute("BEGIN IMMEDIATE")
        try:
            counts = _counts(_existing_last_seen(conn, tasks), tasks, site_summaries)
            conn.executemany(
                _UPSERT_TASK,
                [_task_params(task, run_id, _observed_at(task, site_summaries))
                 for task in tasks])
            # run_sites first: the FK points at runs, so replacing the parent
            # while children still reference it is what a constraint is for.
            conn.execute("DELETE FROM run_sites WHERE run_id = ?", (run_id,))
            conn.execute(
                "INSERT OR REPLACE INTO runs (run_id, merged_at, task_count, "
                "inserted, updated, skipped_stale) VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, merged_at, counts["task_count"], counts["inserted"],
                 counts["updated"], counts["skipped_stale"]))
            conn.executemany(
                "INSERT INTO run_sites (run_id, site, status, error, fetched_at, "
                "task_count) VALUES (?, ?, ?, ?, ?, ?)",
                [(run_id, site, summary["status"], summary["error"],
                  summary["fetched_at"], summary["task_count"])
                 for site, summary in site_summaries.items()])
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
    return counts


def list_tasks() -> list[dict]:
    """Every task row, most recently seen first."""
    return _read(
        f"SELECT {', '.join(TASK_COLUMNS)} FROM tasks "
        "ORDER BY last_seen_at DESC, site, task_id",
        (), _task_row)


def get_task(site: str, task_id: str) -> dict:
    """One task row. An unknown `(site, task_id)` is a `ClientError`."""
    rows = _read(
        f"SELECT {', '.join(TASK_COLUMNS)} FROM tasks WHERE site = ? AND task_id = ?",
        (site, task_id), _task_row)
    if not rows:
        raise ClientError(
            f"no task '{task_id}' for site '{site}' in {paths.db_path()}")
    return rows[0]


def list_runs() -> list[dict]:
    """Every merge, most recent first."""
    return _read(
        f"SELECT {', '.join(RUN_COLUMNS)} FROM runs ORDER BY merged_at DESC, run_id",
        (), dict)


def get_run(run_id: str) -> dict:
    """One run row plus its per-site summaries, keyed by site."""
    rows = _read(
        f"SELECT {', '.join(RUN_COLUMNS)} FROM runs WHERE run_id = ?",
        (run_id,), dict)
    if not rows:
        raise ClientError(f"no run '{run_id}' in {paths.db_path()}")
    sites = _read(
        f"SELECT site, {', '.join(RUN_SITE_COLUMNS)} FROM run_sites "
        "WHERE run_id = ? ORDER BY site",
        (run_id,), dict)
    return {
        **rows[0],
        "sites": {row.pop("site"): row for row in sites},
    }


def _migrate(conn: sqlite3.Connection) -> None:
    for table, column, statement in MIGRATIONS:
        present = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in present:
            conn.execute(statement)


def _read(sql: str, params: tuple, to_record) -> list[dict]:
    conn = connect_readonly()
    try:
        return [to_record(row) for row in conn.execute(sql, params)]
    except sqlite3.Error as exc:
        # The engine can refuse well after the connection opened: a `mode=ro`
        # open is lazy, and a stale `-wal` needing recovery beside a read-only
        # directory fails on the first statement, not on connect.
        raise ClientError(
            f"cannot read the task database at {paths.db_path()}: {exc}") from exc
    finally:
        conn.close()


def _task_row(row: sqlite3.Row) -> dict:
    record = dict(row)
    record["raw"] = jsonio.loads(record["raw"], "stored raw record")
    return record


def _observed_at(task: dict, site_summaries: dict[str, dict]) -> str:
    """When this task was observed: its own site envelope's `fetched_at`.

    One envelope per site per run, so the site names the observation exactly.
    """
    return site_summaries[task["site"]]["fetched_at"]


def _task_params(task: dict, run_id: str, observed_at: str) -> list[Any]:
    """Contract columns in order, then the four bookkeeping columns.

    All four bookkeeping values describe THIS sighting; the upsert's `DO UPDATE`
    clause decides which of them actually win against the stored row.
    """
    values = [task[column] for column in CONTRACT_COLUMNS[:-1]]
    # No sort_keys: `raw` is the site's own record, and it comes back out of
    # `tasks get` in the order the site's CLI printed it. `jsonio.dumps` refuses
    # NaN/Infinity, which SQLite would otherwise store as NULL or as a real that
    # makes this tool's own JSON output unparseable.
    values.append(jsonio.dumps(task["raw"], ensure_ascii=False))
    return values + [observed_at, observed_at, run_id, run_id]


def _counts(existing: dict[tuple[str, str], str], tasks: list[dict],
            site_summaries: dict[str, dict]) -> dict:
    """What the upsert is about to do, decided by the same rule the SQL uses.

    `merge` guarantees the run's tasks are unique by `(site, task_id)`, so each
    task falls in exactly one bucket and the three sum to `task_count`.
    """
    inserted = updated = skipped = 0
    for task in tasks:
        key = (task["site"], task["task_id"])
        if key not in existing:
            inserted += 1
        elif _observed_at(task, site_summaries) >= existing[key]:
            updated += 1
        else:
            skipped += 1
    return {
        "task_count": len(tasks),
        "inserted": inserted,
        "updated": updated,
        "skipped_stale": skipped,
    }


def _existing_last_seen(conn: sqlite3.Connection,
                        tasks: list[dict]) -> dict[tuple[str, str], str]:
    """`(site, task_id) -> last_seen_at` for the run's keys already stored."""
    keys = [(task["site"], task["task_id"]) for task in tasks]
    if not keys:
        return {}
    rows = conn.execute(
        "SELECT site, task_id, last_seen_at FROM tasks "
        "WHERE (site, task_id) IN (VALUES {})".format(
            ", ".join("(?, ?)" for _ in keys)),
        [value for key in keys for value in key])
    return {(row["site"], row["task_id"]): row["last_seen_at"] for row in rows}
