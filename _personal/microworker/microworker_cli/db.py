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

WHAT A RUN COULD NOT READ IS STORED, NOT ONLY PRINTED. `run_sites` carries
`unparsed_payments`: how many of that site's tasks in that run published a
price its adapter could not parse (see `adapters/mapped.py`). It lives here
rather than in the merge's stdout alone because the failure it describes is
slow -- a site changes its price format and every later run stores nulls while
still exiting 0 -- and a number nobody stored cannot answer "when did this
start?" months later. `runs get` reads it back per site; a NULL means the run
was merged under schema version 2, before anything counted.

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

SCHEMA_VERSION = 6
READONLY_TIMEOUT_SECONDS = 1.0

# The task contract's columns, in contract order. `raw` is stored as JSON text
# and comes back parsed, so a reader never sees the serialization.
CONTRACT_COLUMNS = (
    "site", "task_id", "title", "description", "url", "pay_amount",
    "pay_currency", "est_minutes", "slots_open", "expires_at", "raw",
)
# Bookkeeping columns this module owns; adapters never produce them.
SEEN_COLUMNS = (
    "first_seen_at", "last_seen_at", "first_seen_run_id", "last_seen_run_id",
)
# Derived columns written only by the task evaluator's apply path, after the
# merge. `ai_can_handle` is 1 (an AI agent can do the task), 0 (it cannot),
# or NULL (not yet evaluated). `multimodal_required` is 1 (the task needs an
# agent that can take image, video, or audio input), 0 (AI-capable with text-
# only input), or NULL (task is not AI-capable, so no agent modality applies,
# or not yet evaluated). Never produced by an adapter, never touched by the
# merge upsert, so they are read but not written through TASK_COLUMNS.
EVALUATION_COLUMNS = ("ai_can_handle", "multimodal_required")
TASK_COLUMNS = CONTRACT_COLUMNS + SEEN_COLUMNS
RUN_COLUMNS = ("run_id", "merged_at", "task_count", "inserted", "updated",
               "skipped_stale")
RUN_SITE_COLUMNS = ("status", "error", "fetched_at", "task_count",
                    "unparsed_payments")

# Columns a fresher sighting refreshes. `first_seen_at`/`first_seen_run_id` are
# excluded because they move by their own rule (oldest wins, in either
# direction), and `site`/`task_id` are the key. `description` is excluded too:
# it follows its own rule in `_UPSERT_TASK` (a fresher sighting's non-null
# description wins, but a sighting with no description must NOT wipe one that
# was enriched after the fact -- see the guard clause there).
REFRESHED_COLUMNS = tuple(
    column for column in TASK_COLUMNS
    if column not in ("site", "task_id", "first_seen_at", "first_seen_run_id",
                      "description"))

# `pay_amount` is declared with NO datatype on purpose. A `TEXT` affinity would
# store 4.5 as '4.5' and break every numeric comparison; BLOB affinity keeps the
# REAL/INTEGER the adapter produced exactly as it produced it.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tasks (
    site TEXT NOT NULL,
    task_id TEXT NOT NULL,
    title TEXT,
    description TEXT,
    url TEXT,
    pay_amount,
    pay_currency TEXT,
    est_minutes INTEGER,
    slots_open INTEGER,
    expires_at TEXT,
    raw TEXT NOT NULL,
    ai_can_handle INTEGER,
    multimodal_required INTEGER,
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
    unparsed_payments INTEGER,
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
#
# Schema-version 2 databases predate `run_sites.unparsed_payments`. That column
# is added NULLABLE with NO default, and the NULL left on every version-2 row is
# the same kind of fact: under version 2 nothing counted unreadable prices, so
# those runs' counts are UNKNOWN. A backfilled 0 would assert that no old run
# ever hit an unparseable price, which is exactly the claim this column exists
# to stop the tool from making.
#
# Schema-version 3 databases predate `tasks.description`. The column is added
# NULLABLE with NO default: NULL means the site never published a description
# this pipeline could read, and backfilling anything else would assert text
# nobody stored.
#
# Schema-version 4 databases predate `tasks.ai_can_handle`. The column is added
# NULLABLE with NO default: NULL means the task has not been through the task
# evaluator yet, and backfilling a 0 or 1 would assert a verdict nobody made.
#
# Schema-version 5 databases predate `tasks.multimodal_required`. The column is
# added NULLABLE with NO default: NULL means the task is not AI-capable (no
# agent modality applies) or has not been re-evaluated under the extended
# contract, and backfilling a 0 or 1 would assert a modality verdict nobody
# made.
MIGRATIONS = (
    ("runs", "skipped_stale",
     "ALTER TABLE runs ADD COLUMN skipped_stale INTEGER NOT NULL DEFAULT 0"),
    ("run_sites", "unparsed_payments",
     "ALTER TABLE run_sites ADD COLUMN unparsed_payments INTEGER"),
    ("tasks", "description",
     "ALTER TABLE tasks ADD COLUMN description TEXT"),
    ("tasks", "ai_can_handle",
     "ALTER TABLE tasks ADD COLUMN ai_can_handle INTEGER"),
    ("tasks", "multimodal_required",
     "ALTER TABLE tasks ADD COLUMN multimodal_required INTEGER"),
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
    #
    # `description` is NOT in REFRESHED_COLUMNS because it follows its own rule:
    # a fresher sighting's non-empty description replaces the stored one, but a
    # sighting that carries none (the common case -- most sites publish
    # descriptions only on detail pages, where `microworker enrich` fetches
    # them AFTER the merge) leaves an enriched description alone instead of
    # wiping it back to null on every re-discovery.
    updates=", ".join(
        [f"{column} = CASE WHEN excluded.last_seen_at >= tasks.last_seen_at "
         f"THEN excluded.{column} ELSE tasks.{column} END"
         for column in REFRESHED_COLUMNS]
        + [
            "description = CASE WHEN excluded.last_seen_at >= tasks.last_seen_at "
            "AND excluded.description IS NOT NULL "
            "AND excluded.description != '' THEN excluded.description "
            "ELSE tasks.description END",
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
                "task_count, unparsed_payments) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(run_id, site, summary["status"], summary["error"],
                  summary["fetched_at"], summary["task_count"],
                  summary["unparsed_payments"])
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
        f"SELECT {', '.join(TASK_COLUMNS + EVALUATION_COLUMNS)} FROM tasks "
        "ORDER BY last_seen_at DESC, site, task_id",
        (), _task_row)


def get_task(site: str, task_id: str) -> dict:
    """One task row. An unknown `(site, task_id)` is a `ClientError`."""
    rows = _read(
        f"SELECT {', '.join(TASK_COLUMNS + EVALUATION_COLUMNS)} FROM tasks "
        "WHERE site = ? AND task_id = ?",
        (site, task_id), _task_row)
    if not rows:
        raise ClientError(
            f"no task '{task_id}' for site '{site}' in {paths.db_path()}")
    return rows[0]


def update_task_description(site: str, task_id: str, description: str) -> bool:
    """Set one task's description; the `microworker enrich` write path.

    The text comes from the site's detail page, fetched after the merge that
    stored the row; the merge upsert's own guard keeps a later description-less
    sighting from wiping it. Returns whether a row matched.
    """
    conn = connect()
    try:
        cursor = conn.execute(
            "UPDATE tasks SET description = ? WHERE site = ? AND task_id = ?",
            (description, site, task_id))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def update_task_descriptions_many(entries: list[dict]) -> dict:
    """Bulk-fill empty descriptions from one file, atomically.

    `entries` is `[{"site", "task_id", "description"}]`, already validated by
    the caller (`descriptions.apply_descriptions`). A row is only updated when
    it has NO stored description (NULL or empty) -- a real description from a
    site detail page is never clobbered by a later generated fallback. Every
    row is counted as updated, skipped (already described), or named missing
    (no such task). Returns `{"updated": int, "skipped": int,
    "missing": [f"{site}/{task_id}", ...]}`.
    """
    conn = connect()
    try:
        conn.isolation_level = None
        conn.execute("BEGIN IMMEDIATE")
        try:
            updated = skipped = 0
            missing: list[str] = []
            for entry in entries:
                cursor = conn.execute(
                    "UPDATE tasks SET description = ? "
                    "WHERE site = ? AND task_id = ? "
                    "AND (description IS NULL OR description = '')",
                    (entry["description"], entry["site"], entry["task_id"]))
                if cursor.rowcount > 0:
                    updated += 1
                    continue
                found = conn.execute(
                    "SELECT 1 FROM tasks WHERE site = ? AND task_id = ?",
                    (entry["site"], entry["task_id"])).fetchone()
                if found is not None:
                    skipped += 1
                else:
                    missing.append(f"{entry['site']}/{entry['task_id']}")
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
    return {"updated": updated, "skipped": skipped, "missing": missing}


def set_task_ai_can_handle(site: str, task_id: str,
                           value: int | None) -> bool:
    """Set one task's `ai_can_handle` (1, 0, or None to clear). Returns whether
    a row matched. Low-level single-column helper (tests, one-off clears); the
    evaluator's apply path writes both verdict columns together through
    `set_task_evaluation_many`.
    """
    conn = connect()
    try:
        cursor = conn.execute(
            "UPDATE tasks SET ai_can_handle = ? WHERE site = ? AND task_id = ?",
            (value, site, task_id))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def set_task_evaluation_many(entries: list[dict]) -> dict:
    """Bulk-set evaluator verdict columns from one verdict file, atomically.

    `entries` is `[{"site", "task_id", "ai_can_handle": 0|1|None,
    "multimodal_required": 0|1|None}]`, already validated and coerced by the
    caller (`evaluate.apply_evaluation`). Both columns are written in one
    UPDATE per task inside one transaction, so a verdict never lands with one
    field refreshed and the other stale. Every row is updated or named
    missing; a verdict never creates a task. Returns
    `{"updated": int, "missing": [f"{site}/{task_id}", ...]}`.
    """
    conn = connect()
    try:
        conn.isolation_level = None
        conn.execute("BEGIN IMMEDIATE")
        try:
            updated = 0
            missing: list[str] = []
            for entry in entries:
                cursor = conn.execute(
                    "UPDATE tasks SET ai_can_handle = ?, "
                    "multimodal_required = ? "
                    "WHERE site = ? AND task_id = ?",
                    (entry["ai_can_handle"], entry["multimodal_required"],
                     entry["site"], entry["task_id"]))
                if cursor.rowcount > 0:
                    updated += 1
                else:
                    missing.append(f"{entry['site']}/{entry['task_id']}")
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
    return {"updated": updated, "missing": missing}


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


def migrate() -> str:
    """Apply any pending schema migrations. Returns the schema version.

    Migrations run on the write connection (`connect`), so a database created
    by an older tool version stays readable by read-only commands until a
    write path runs. This is the explicit operator path for that gap: run it
    after upgrading the tool and before read commands, or let the next merge
    do the same work.
    """
    conn = connect()
    conn.close()
    return str(SCHEMA_VERSION)


def _read(sql: str, params: tuple, to_record) -> list[dict]:
    conn = connect_readonly()
    try:
        return [to_record(row) for row in conn.execute(sql, params)]
    except sqlite3.Error as exc:
        # The engine can refuse well after the connection opened: a `mode=ro`
        # open is lazy, and a stale `-wal` needing recovery beside a read-only
        # directory fails on the first statement, not on connect. A missing
        # column is the migration gap: the database predates the current
        # schema, and only a write path (`merge`, or `microworker migrate`)
        # can add it.
        hint = ""
        if "no such column" in str(exc):
            hint = "; the database predates the current schema -- run " \
                   "`microworker migrate` (or any merge) to upgrade it"
        raise ClientError(
            f"cannot read the task database at {paths.db_path()}: {exc}{hint}"
        ) from exc
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


# ---------------------------------------------------------------------------
# The board store: `data/board.db`, beside the ledger and owned by the board
# service on adam-server. Same rule as the ledger: this module is the only
# thing that opens it.
#
# The ledger (`tasks.db`) is written by `merge` on the discovery machine only;
# the board service reads a snapshot of it read-only. The board's own state --
# which column a card sits in, and the delegation jobs that hand cards to an
# agent -- cannot live in a file it may not write, so it lives here, in a
# second file with exactly one writer. Two files, one writer each: a synced
# SQLite file with two writers is how a ledger silently forks (the Dropbox
# ignore rules carry exactly that warning), and this split makes it
# impossible by construction.
#
# A task with no `task_states` row is on the default `backlog` column; the
# board materializes that default rather than writing a row for every task a
# merge ever stores. `delegations` is append-only except for the fields a run
# may fill in: status, pid, exit code, and the two clocks.
# ---------------------------------------------------------------------------

BOARD_COLUMNS = ("backlog", "ready", "delegated", "working", "review", "done")
DELEGATION_KINDS = ("work", "apply")
DELEGATION_STATUSES = ("pending", "running", "done", "failed")
DELEGATION_UPDATE_COLUMNS = ("status", "pid", "exit_code", "log_path",
                             "started_at", "finished_at")

BOARD_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS board_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS task_states (
    site TEXT NOT NULL,
    task_id TEXT NOT NULL,
    column_id TEXT NOT NULL,
    approved INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (site, task_id)
);
CREATE TABLE IF NOT EXISTS delegations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site TEXT NOT NULL,
    task_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    prompt TEXT,
    log_path TEXT,
    pid INTEGER,
    exit_code INTEGER,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_delegations_status ON delegations(status);
CREATE INDEX IF NOT EXISTS idx_delegations_task ON delegations(site, task_id);
"""


def connect_board() -> sqlite3.Connection:
    """The board store's write-capable connection. Creates the file/schema."""
    path = paths.board_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(BOARD_SCHEMA_SQL)
    conn.commit()
    return conn


def _board_read(sql: str, params: tuple = ()) -> list[dict]:
    """Read board rows through a connection this function closes."""
    conn = connect_board()
    try:
        return [dict(row) for row in conn.execute(sql, params)]
    finally:
        conn.close()


def board_settings() -> dict[str, str]:
    """Every board setting as `{key: value}`. Empty when nothing was set."""
    return {row["key"]: row["value"]
            for row in _board_read("SELECT key, value FROM board_settings")}


def board_set_settings(settings: dict[str, str]) -> None:
    """Upsert the given settings; keys not named are left alone."""
    conn = connect_board()
    try:
        conn.executemany(
            "INSERT OR REPLACE INTO board_settings (key, value) VALUES (?, ?)",
            list(settings.items()))
        conn.commit()
    finally:
        conn.close()


def board_upsert_task_state(site: str, task_id: str, column_id: str, *,
                            approved: bool, updated_at: str) -> None:
    """One card's column and approval flag. Unknown columns are `ClientError`."""
    if column_id not in BOARD_COLUMNS:
        raise ClientError(
            f"invalid board column {column_id!r}: a column is one of "
            + ", ".join(BOARD_COLUMNS))
    conn = connect_board()
    try:
        conn.execute(
            "INSERT INTO task_states (site, task_id, column_id, approved, "
            "updated_at) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(site, task_id) DO UPDATE SET "
            "column_id = excluded.column_id, approved = excluded.approved, "
            "updated_at = excluded.updated_at",
            (site, task_id, column_id, int(bool(approved)), updated_at))
        conn.commit()
    finally:
        conn.close()


def board_task_states() -> list[dict]:
    """Every card state row; `approved` comes back as a 0/1 integer."""
    return _board_read(
        "SELECT site, task_id, column_id, approved, updated_at "
        "FROM task_states")


def board_create_delegation(site: str, task_id: str, kind: str, prompt: str,
                            log_path: str, created_at: str) -> int:
    """Insert a `pending` delegation and return its id."""
    if kind not in DELEGATION_KINDS:
        raise ClientError(
            f"invalid delegation kind {kind!r}: a kind is one of "
            + ", ".join(DELEGATION_KINDS))
    conn = connect_board()
    try:
        cursor = conn.execute(
            "INSERT INTO delegations (site, task_id, kind, status, prompt, "
            "log_path, created_at) VALUES (?, ?, ?, 'pending', ?, ?, ?)",
            (site, task_id, kind, prompt, log_path, created_at))
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def board_get_delegation(delegation_id: int) -> dict:
    """One delegation row; an unknown id is a `ClientError`."""
    rows = _board_read("SELECT * FROM delegations WHERE id = ?",
                       (delegation_id,))
    if not rows:
        raise ClientError(f"no delegation {delegation_id} in {paths.board_path()}")
    return rows[0]


def board_update_delegation(delegation_id: int, **fields) -> None:
    """Fill in the run fields of one delegation (status, pid, clocks, exit).

    Only `DELEGATION_UPDATE_COLUMNS` are writable; everything else is fixed
    at creation, so a typo here is a `ClientError`, not a silent no-op.
    """
    unknown = set(fields) - set(DELEGATION_UPDATE_COLUMNS)
    if unknown:
        raise ClientError(
            f"cannot update delegation fields: {', '.join(sorted(unknown))}; "
            f"writable fields: {', '.join(DELEGATION_UPDATE_COLUMNS)}")
    if "status" in fields and fields["status"] not in DELEGATION_STATUSES:
        raise ClientError(
            f"invalid delegation status {fields['status']!r}: a status is one "
            f"of {', '.join(DELEGATION_STATUSES)}")
    if not fields:
        return
    assignments = ", ".join(f"{column} = ?" for column in fields)
    conn = connect_board()
    try:
        conn.execute(f"UPDATE delegations SET {assignments} WHERE id = ?",
                     (*fields.values(), delegation_id))
        conn.commit()
    finally:
        conn.close()


def board_delegations(site: str, task_id: str) -> list[dict]:
    """Every delegation for one card, oldest first."""
    return _board_read(
        "SELECT * FROM delegations WHERE site = ? AND task_id = ? ORDER BY id",
        (site, task_id))


def board_pending_delegations() -> list[dict]:
    """Delegations waiting for the dispatcher, oldest first."""
    return _board_read(
        "SELECT * FROM delegations WHERE status = 'pending' ORDER BY id")


def board_active_delegation(site: str, task_id: str,
                            kind: str) -> dict | None:
    """The card's in-flight delegation of that kind, if any."""
    rows = _board_read(
        "SELECT * FROM delegations WHERE site = ? AND task_id = ? "
        "AND kind = ? AND status IN ('pending', 'running') "
        "ORDER BY id DESC LIMIT 1",
        (site, task_id, kind))
    return rows[0] if rows else None


def board_latest_delegations() -> dict[tuple[str, str], dict]:
    """`(site, task_id) ->` each card's newest delegation row."""
    rows = _board_read(
        "SELECT d.* FROM delegations d JOIN "
        "(SELECT site, task_id, MAX(id) AS max_id FROM delegations "
        "GROUP BY site, task_id) m "
        "ON d.site = m.site AND d.task_id = m.task_id AND d.id = m.max_id")
    return {(row["site"], row["task_id"]): row for row in rows}
