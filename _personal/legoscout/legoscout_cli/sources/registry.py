#!/usr/bin/env python3
"""The one reader of the LEGO Scout source registry.

`source_capabilities.py`, `hypothesis_types.py` and `fees.py` were the same
file three times: each defined HERE/CONFIG, a `table()`, a key normaliser, an
`entry()` that raises "research it, do not default it", and an argparse
`main()`. Only the config path and the noun differed. This is that file once.

    legoscout sources                        # every source, one line each
    legoscout sources ebay                    # one source, no notes
    legoscout sources ebay --notes            # ...with its learning notes
    legoscout sources 'hibid|314234951'       # a listing_key resolves
    legoscout sources --active-namespaces     # the run plan
    legoscout sources --check                 # every entry is well formed
    legoscout sources --dump                  # the whole sources table, JSON
    legoscout sources ebay --append-note "2026-08-04: ..."

The registry lives in three tables inside the deal ledger database --
`sources`, `source_notes` and `source_registry_meta` -- and this module is the
only access layer for them. It builds on `ledger_db.connect()`, so the registry
and the deals share one file, one WAL and one backup.

An unknown key RAISES. A source that has never been researched is a gap to
close, not a silent default -- that rule is why `SOURCE_SHORT`'s `||` fallback
hid 7 missing sources for weeks.

Notes are excluded by default. They are 66% of the registry, and eBay's alone
are ~2,900 tokens; a worker that gets them unasked spends its context on
history. A note whose `supersedes` names another note hides that older one, so
`--notes` returns the current position rather than the whole archaeology.

A payload is still complete: `fee_defaults` is stated once in the meta table,
and a source states a field again only to override it. `--check` fails a source
that restates a default verbatim, because that is how 19 copies of one sentence
got there.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# The ledger owns the database file, the WAL mode and the connect contract, so
# the registry borrows all three rather than opening the file a second way. An
# absolute literal, the same bridge prospects_db.py uses to reach the
# prospector: these two skills sit in fixed places and a relative walk up the
# tree breaks the moment either one is invoked through a symlink.

from ..ledger import db as ledger_db  # noqa: E402

DB_PATH = ledger_db.DB_PATH

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    namespace TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_notes (
    id TEXT PRIMARY KEY,
    namespace TEXT NOT NULL REFERENCES sources(namespace),
    date TEXT NOT NULL,
    text TEXT NOT NULL,
    supersedes TEXT
);
CREATE INDEX IF NOT EXISTS idx_source_notes_namespace ON source_notes(namespace);
CREATE TABLE IF NOT EXISTS source_registry_meta (
    key TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
"""

# Every object _SCHEMA creates. sqlite_master is read before the script runs, so
# a database already at the current shape takes no write lock -- the same
# idempotent-connect pattern sellers_db.py and prospects_db.py use.
_SCHEMA_OBJECTS: tuple[str, ...] = (
    "sources", "source_notes", "idx_source_notes_namespace",
    "source_registry_meta",
)

# The document's top-level blocks other than `sources`, in the order they are
# served. They are shared facts, not per-source ones: a fee default stated once
# here is what stops 22 sources from each holding a copy of it.
_META_KEYS: tuple[str, ...] = (
    "_doc", "_note_buckets", "note_buckets",
    "fee_defaults", "fee_buyer", "discovery_rows",
)

_HINT = ("research the source and register it with add_source.py, rather than "
         "assuming a default for it")


class UnknownEntry(KeyError):
    """A key that is not registered. Never softened into a default."""

    def __str__(self):                       # KeyError repr()s its argument
        return self.args[0]


def _ensure_schema(conn: sqlite3.Connection) -> None:
    have = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    if all(name in have for name in _SCHEMA_OBJECTS):
        return
    conn.executescript(_SCHEMA)
    conn.commit()


def _connect(path: str = DB_PATH) -> sqlite3.Connection:
    """A ledger_db connection with the registry schema guaranteed present.

    `busy_timeout` is set here and nowhere else: concurrent source workers append
    notes, and without it the second writer to reach `BEGIN IMMEDIATE` fails
    instantly with "database is locked" instead of waiting out the first. The
    ledger's own readers do not append, so they do not need it.

    `isolation_level = None` hands transaction control to this module. The
    append is one explicit `BEGIN IMMEDIATE` ... `COMMIT`, which is what makes
    the resolve-count-insert sequence atomic against another writer.
    """
    conn = ledger_db.connect(path)
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.isolation_level = None
    _ensure_schema(conn)
    return conn


def _read_table(conn: sqlite3.Connection) -> dict:
    """Every source with its notes, in registration order.

    `ORDER BY rowid` on both tables, the same idiom `ledger_db.load_document()` uses: it
    is what makes "the new entry is the last key" a fact about the data rather
    than about the alphabet.
    """
    notes: dict[str, list] = {}
    for row in conn.execute(
            "SELECT id, namespace, date, text, supersedes FROM source_notes "
            "ORDER BY rowid"):
        notes.setdefault(row["namespace"], []).append(
            {"id": row["id"], "date": row["date"], "text": row["text"],
             "supersedes": row["supersedes"]})
    entries = {}
    for row in conn.execute("SELECT namespace, payload FROM sources ORDER BY rowid"):
        entry = json.loads(row["payload"])
        entry["notes"] = notes.get(row["namespace"], [])
        entries[row["namespace"]] = entry
    return entries


def _read_document(conn: sqlite3.Connection) -> dict:
    """The whole registry, read through one open connection.

    Separate from `Registry.document()` so add_source.py can take its fresh read
    INSIDE the transaction it is about to write in, rather than opening a second
    connection that another writer could change under it.
    """
    stored = {r["key"]: json.loads(r["payload"]) for r in conn.execute(
        "SELECT key, payload FROM source_registry_meta")}
    doc = {}
    for key in _META_KEYS:
        if key not in stored:
            raise KeyError(
                "the source registry has no %r block. Restore the newest copy "
                "from ~/legoscout-snapshots/, or from Dropbox version history."
                % key)
        doc[key] = stored[key]
    doc["sources"] = _read_table(conn)
    return doc


def _resolve(entries: dict, text) -> str:
    """Resolve any spelling to a table key, against an already-read table.

    Accepts a key, a listing_key (`hibid|3142...`), a display name, or a
    registered alias. Display names are looked up in an index built FROM the
    data, never derived by a transform: no rule turns "EstateSales.NET" into
    `estatesales` while turning "EstateSales.org" into `estatesalesorg`, and
    `fees.source_key` -- which tried -- silently served the defaults block for
    every EstateSales.NET caller.
    """
    if not isinstance(text, str):
        raise TypeError("a source key must be a string, got %r (%s)"
                        % (text, type(text).__name__))
    raw = text.split("|", 1)[0].strip()
    if not raw:
        raise ValueError("no source given")
    if raw in entries:
        return raw
    lowered = raw.lower()
    if lowered in entries:
        return lowered
    for name, entry in entries.items():
        spellings = [entry.get("display_name")] + list(entry.get("aliases", []))
        if any(s and s.lower() == lowered for s in spellings):
            return name
    raise UnknownEntry("%r is not a registered source in the source registry "
                       "-- %s" % (raw, _HINT))


class Registry:
    """The source registry, read through one code path.

    `path` is the ledger database. It is a parameter so a test can run against a
    scratch copy; every caller in the pipeline takes the default.
    """

    def __init__(self, path: str = DB_PATH):
        self.path = path

    def document(self):
        """The whole registry: the meta blocks, then the sources.

        A missing meta block RAISES. The registry is curated data, not a cache,
        so an absent `fee_defaults` is a broken database and never "no defaults"
        -- which would silently un-merge the shared rule out of all 22 payloads.
        """
        conn = _connect(self.path)
        try:
            return _read_document(conn)
        finally:
            conn.close()

    def table(self):
        conn = _connect(self.path)
        try:
            return _read_table(conn)
        finally:
            conn.close()

    def key(self, text):
        return _resolve(self.table(), text)

    def entry(self, text):
        entries = self.table()
        return entries[_resolve(entries, text)]

    def append_note(self, text, note, date):
        """Add a dated note to one source, inside one transaction.

        Five skill files used to instruct an agent to append prose to
        sources.md. Concurrent source workers doing that lose each other's work.
        The resolve, the ordinal count and the insert now happen between one
        `BEGIN IMMEDIATE` and its `COMMIT`, so the second writer waits rather
        than reading a table the first is about to change.
        """
        conn = _connect(self.path)
        try:
            conn.execute("BEGIN IMMEDIATE")
            try:
                name = _resolve(_read_table(conn), text)
                seq = 1 + conn.execute(
                    "SELECT COUNT(*) FROM source_notes WHERE namespace = ? "
                    "AND date = ?", (name, date)).fetchone()[0]
                row = {"id": "%s-%s-%d" % (name, date, seq), "date": date,
                       "text": note, "supersedes": None}
                conn.execute(
                    "INSERT INTO source_notes (id, namespace, date, text, "
                    "supersedes) VALUES (?, ?, ?, ?, ?)",
                    (row["id"], name, row["date"], row["text"],
                     row["supersedes"]))
                conn.execute("COMMIT")
                return row
            except BaseException:
                conn.execute("ROLLBACK")
                raise
        finally:
            conn.close()


sources = Registry()


# --- source-specific reads --------------------------------------------------


def current_notes(entry):
    """An entry's notes with every superseded one removed."""
    replaced = {n["supersedes"] for n in entry["notes"] if n["supersedes"]}
    return [n for n in entry["notes"] if n["id"] not in replaced]


def add_entry(namespace, entry, validate):
    """Insert one researched source, validated against a fresh read, in one write.

    The registry owns its own writes. `BEGIN IMMEDIATE` takes the write lock
    BEFORE the document is read, so a concurrent `--append-note` cannot land
    between the validation and the insert. That is the same guarantee the file
    lock used to give, from the database rather than from a lock file beside it.

    `validate(doc)` is the caller's rule set, run against the in-transaction
    document. It returns a list of problems; a non-empty list rolls back and is
    returned to the caller, which decides how to report it.
    """
    conn = _connect(DB_PATH)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            doc = _read_document(conn)
            problems = validate(doc)
            if problems:
                conn.execute("ROLLBACK")
                return problems
            payload_row = {k: v for k, v in entry.items() if k != "notes"}
            conn.execute("INSERT INTO sources (namespace, payload) VALUES (?, ?)",
                         (namespace, json.dumps(payload_row, ensure_ascii=False)))
            for note in entry["notes"]:
                conn.execute(
                    "INSERT INTO source_notes (id, namespace, date, text, "
                    "supersedes) VALUES (?, ?, ?, ?, ?)",
                    (note["id"], namespace, note["date"], note["text"],
                     note["supersedes"]))
            conn.execute("COMMIT")
        except BaseException:
            # A rolled-back transaction is already closed; a second ROLLBACK on
            # one is an error, so only roll back a live transaction.
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
    return []


def payload(text, with_notes):
    """What a source worker is handed for its source."""
    doc = sources.document()
    entry = dict(doc["sources"][_resolve(doc["sources"], text)])
    entry["notes_available"] = len(entry["notes"])
    entry["notes"] = current_notes(entry) if with_notes else []
    return entry


def active_namespaces():
    return sorted(k for k, v in sources.table().items() if v["status"] == "active")


def can_offer(text):
    return sources.entry(text)["capability"]["can_offer"]


def fee_config(text):
    """The fee table for one source: the shared defaults, then its own rates.

    A source whose `fees` is null has never had its premium and tax researched.
    That RAISES rather than pricing at the defaults. The defaults say 0%
    premium and no sales tax, so the old silent merge priced
    `palletliquidation|4751` -- a $500 pallet from a real WooCommerce checkout
    that charges Indiana tax -- at exactly $500 landed.
    """
    doc = sources.document()
    name = _resolve(doc["sources"], text)
    fees = doc["sources"][name]["fees"]
    if fees is None:
        raise UnknownEntry(
            "%s has no researched fee structure in the source registry -- read "
            "its buyer premium and sales tax off a live checkout or lot page "
            "and record them, rather than pricing it at the zero-fee defaults"
            % name)
    config = dict(doc["fee_defaults"])
    config.update(fees)
    config["_key"] = name
    return config


def fee_buyer():
    """Adam's own tax position, shared by every source."""
    return sources.document()["fee_buyer"]


def display_name(text):
    return sources.entry(text)["display_name"]


REQUIRED = ("display_name", "short", "status", "namespace",
            "listing_key_format", "access", "capability", "notes")


def check(doc=None):
    """Every problem with the registry, as a list. Empty means it is sound.

    A pure function over a document dict, so a caller can check the registry
    that WOULD exist -- add_source.py merges its candidate entry into a copy and
    checks that -- without writing anything first. `doc=None` reads the live
    registry, which is what `main()` does.
    """
    if doc is None:
        doc = sources.document()
    problems = []
    for name, entry in doc["sources"].items():
        for field in REQUIRED:
            if field not in entry:
                problems.append("%s: missing %r" % (name, field))
        if entry.get("namespace") != name:
            problems.append("%s: namespace field says %r"
                            % (name, entry.get("namespace")))
        if not entry.get("listing_key_format", "").startswith(name + "|"):
            problems.append("%s: listing_key_format does not start with the "
                            "namespace" % name)
        ids = [n["id"] for n in entry.get("notes", [])]
        if len(ids) != len(set(ids)):
            problems.append("%s: duplicate note ids" % name)
        for note in entry.get("notes", []):
            if note["supersedes"] and note["supersedes"] not in ids:
                problems.append("%s: note %s supersedes %s, which is not one "
                                "of its own notes" % (name, note["id"],
                                                      note["supersedes"]))
    shorts = [e["short"] for e in doc["sources"].values()]
    if len(shorts) != len(set(shorts)):
        problems.append("two sources share a short name")
    for slug, row in doc["discovery_rows"].items():
        if slug in doc["sources"]:
            problems.append("%s is both a source and a discovery row" % slug)
    # A registry entry and its reader module can each be internally valid and
    # still state opposite facts. `estatesalesorg` said auction_tier='always'
    # while its reader answered `not-an-auction` for every lot, and nothing
    # raised, because both halves were well-formed on their own. Local import:
    # reader_contract imports the readers package, which imports this one.
    from . import reader_contract

    problems.extend(reader_contract.problems(
        {name: entry.get("auction_tier") for name, entry in doc["sources"].items()}))
    return problems


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", nargs="?", help="namespace, display name, or listing_key")
    ap.add_argument("--notes", action="store_true",
                    help="include the source's current learning notes")
    ap.add_argument("--append-note", metavar="TEXT",
                    help="add a note to this source")
    ap.add_argument("--date", help="the note's date, YYYY-MM-DD (required with "
                                   "--append-note; there is no 'today' default "
                                   "because a run's date is the run's, not the "
                                   "clock's)")
    ap.add_argument("--active-namespaces", action="store_true",
                    help="the run plan, one namespace per line")
    ap.add_argument("--check", action="store_true",
                    help="validate the registry; exit 1 on any problem")
    ap.add_argument("--dump", action="store_true",
                    help="the whole sources table as one JSON object")
    a = ap.parse_args()

    if a.check:
        problems = check()
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1 if problems else 0

    if a.dump:
        print(json.dumps(sources.table(), ensure_ascii=False))
        return 0

    if a.active_namespaces:
        for name in active_namespaces():
            print(name)
        return 0

    if a.append_note:
        if not (a.source and a.date):
            return sys.exit("--append-note needs a source and a --date")
        print(json.dumps(sources.append_note(a.source, a.append_note, a.date),
                         indent=1, ensure_ascii=False))
        return 0

    if a.source:
        try:
            print(json.dumps(payload(a.source, a.notes), indent=1,
                             ensure_ascii=False))
        except (UnknownEntry, ValueError, TypeError) as exc:
            print("registry: %s" % exc, file=sys.stderr)
            return 2
        return 0

    print("%-22s %-12s %-8s %-9s %s"
          % ("NAMESPACE", "SHORT", "STATUS", "CAN_OFFER", "ACCESS"))
    for name, entry in sorted(sources.table().items()):
        print("%-22s %-12s %-8s %-9s %s"
              % (name, entry["short"], entry["status"],
                 entry["capability"]["can_offer"], entry["access"]["method"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
