"""The durable task store: `<project_root>/data/tasks.db`, and nothing else.

Site envelopes are per-run and disposable; this database is what survives them.
`merge` folds each run's envelopes into it, so a task discovered in March and
seen again in September is ONE row that remembers both dates, not two files an
agent has to reconcile.

ONE ROW PER `(site, task_id)`. There is no per-run membership table and no
append-per-sighting history: re-seeing a task refreshes every contract column
plus `last_seen_at`/`last_seen_run_id`, while `first_seen_at`/`first_seen_run_id`
are written once and never overwritten. That is the whole of the history this
store keeps, and it is deliberate -- "what is open right now, and how long has it
been around" is the question the discovery pipeline actually asks.

THIS MODULE IS THE ONLY PLACE THAT OPENS THE DATABASE. `paths.db_path()` is the
only place that names it. Writes go through a write-capable connection under
`BEGIN IMMEDIATE` with an explicit COMMIT/ROLLBACK, so a crashed merge leaves
the previous run intact rather than half of two runs. Reads go through a
separate `mode=ro` URI connection: read-only is enforced by the SQLite engine,
below the SQL grammar, so no query command can write no matter what it is handed.

A read against a database that does not exist is a `ClientError` naming the
path, never an empty list. An empty list would read as "no tasks are open",
which is a different fact from "nothing has ever been merged".
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from cli_tools_shared.exceptions import ClientError

from . import paths

SCHEMA_VERSION = 1
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
RUN_COLUMNS = ("run_id", "merged_at", "task_count", "inserted", "updated")
RUN_SITE_COLUMNS = ("status", "error", "fetched_at", "task_count")

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
    updated INTEGER NOT NULL
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

_UPSERT_TASK = """
INSERT INTO tasks ({columns}) VALUES ({placeholders})
ON CONFLICT(site, task_id) DO UPDATE SET {updates}
""".format(
    columns=", ".join(TASK_COLUMNS),
    placeholders=", ".join("?" for _ in TASK_COLUMNS),
    # Everything the run just observed is refreshed. `first_seen_at` and
    # `first_seen_run_id` are absent from this list, which is the only reason
    # the row remembers when it was new.
    updates=", ".join(
        f"{column} = excluded.{column}"
        for column in TASK_COLUMNS
        if column not in ("site", "task_id", "first_seen_at", "first_seen_run_id")),
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
    conn = sqlite3.connect(
        path.as_uri() + "?mode=ro", uri=True, timeout=READONLY_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    return conn


def write_run(run_id: str, merged_at: str, site_summaries: dict[str, dict],
              tasks: list[dict]) -> dict:
    """Upsert one merge: the run row, its per-site summaries, and its tasks.

    Every task must already satisfy `task.schema.json`; `merge.merge()` validates
    each one as it maps it, where the envelope path and index are still in hand to
    name in the error. This function is reached only after all of them passed, so
    the single transaction below either lands the whole run or none of it.

    Re-merging a run id is idempotent for the run's own bookkeeping: its
    `run_sites` rows are deleted and its `runs` row replaced rather than
    duplicated. The tasks simply upsert again.

    Returns `{"task_count", "inserted", "updated"}`. `task_count` counts the
    tasks the run merged; `inserted`/`updated` count DISTINCT `(site, task_id)`
    rows written, so a run that carries the same task twice reports 2 and 1.
    """
    keys = [(task["site"], task["task_id"]) for task in tasks]
    conn = connect()
    try:
        # BEGIN IMMEDIATE, not the deferred transaction `with conn` opens: the
        # existing-key read below decides the inserted/updated counts, and it is
        # only true if it and the write share one exclusive transaction.
        conn.isolation_level = None
        conn.execute("BEGIN IMMEDIATE")
        try:
            existing = _existing_keys(conn, keys)
            conn.executemany(
                _UPSERT_TASK, [_task_params(task, run_id, merged_at) for task in tasks])
            counts = {
                "task_count": len(tasks),
                "inserted": len(set(keys) - existing),
                "updated": len(existing),
            }
            # run_sites first: the FK points at runs, so replacing the parent
            # while children still reference it is what a constraint is for.
            conn.execute("DELETE FROM run_sites WHERE run_id = ?", (run_id,))
            conn.execute(
                "INSERT OR REPLACE INTO runs (run_id, merged_at, task_count, "
                "inserted, updated) VALUES (?, ?, ?, ?, ?)",
                (run_id, merged_at, counts["task_count"], counts["inserted"],
                 counts["updated"]))
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


def _read(sql: str, params: tuple, to_record) -> list[dict]:
    conn = connect_readonly()
    try:
        return [to_record(row) for row in conn.execute(sql, params)]
    finally:
        conn.close()


def _task_row(row: sqlite3.Row) -> dict:
    record = dict(row)
    record["raw"] = json.loads(record["raw"])
    return record


def _task_params(task: dict, run_id: str, merged_at: str) -> list[Any]:
    """Contract columns in order, then the four bookkeeping columns.

    `first_seen_at`/`first_seen_run_id` are bound to this run's values on every
    call; the upsert's DO UPDATE clause omits them, so they only ever take effect
    on the INSERT that creates the row.
    """
    values = [task[column] for column in CONTRACT_COLUMNS[:-1]]
    # No sort_keys: `raw` is the site's own record, and it comes back out of
    # `tasks get` in the order the site's CLI printed it.
    values.append(json.dumps(task["raw"], ensure_ascii=False))
    return values + [merged_at, merged_at, run_id, run_id]


def _existing_keys(conn: sqlite3.Connection,
                   keys: list[tuple[str, str]]) -> set[tuple[str, str]]:
    if not keys:
        return set()
    rows = conn.execute(
        "SELECT site, task_id FROM tasks WHERE (site, task_id) IN (VALUES {})".format(
            ", ".join("(?, ?)" for _ in keys)),
        [value for key in keys for value in key])
    return {(row["site"], row["task_id"]) for row in rows}
