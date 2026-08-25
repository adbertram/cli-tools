#!/usr/bin/env python3
"""SQLite-backed access layer for the LEGO Scout deal ledger.

Every consumer keeps the in-memory shape it already used with the JSON file:
`load_document()` returns the same top-level document, `save(doc)` writes it back
inside a single transaction. Storage is an implementation detail behind this
module.

TWO READS, TWO NAMES. `load_document()` returns the whole `{schema_version,
updated_at, deals: [...], ledger_contract, ...}` mapping -- the thing `save()`
takes back. `load_deals()` returns just the list of deal dicts. The document
reader was called `load()` until 2026-08-06, and that name cost a live run: a
caller wrote the obvious `for deal in db.load(): deal.get(...)` , iterated a
dict, got its KEYS, and died on `AttributeError: 'str' object has no attribute
'get'`. A name that does not say which of the two things it returns is a name
that will be read as the other one. Neither function takes a flag to behave as
the other; one name means one shape.

New capabilities the JSON file could not provide:
  - `query(sql, params)` for real SQL against the deals table
  - `update_status(...)` for a targeted single-row write instead of an 8 MB
    read-modify-write cycle
  - `mark_unavailable(...)` / `mark_blocked(...)` for the same targeted
    single-row write when the status is `unavailable` or `blocked`, which
    `update_status()` refuses
  - transactional writes, so a crashed run cannot leave a half-written ledger
"""

from __future__ import annotations

from .. import paths
import json
import os
import pathlib
import sqlite3
import sys
from typing import Any


from . import schema as deal_schema  # noqa: E402

DB_PATH = paths.DB_PATH
READONLY_TIMEOUT_SECONDS = 1.0

SCHEMA_VERSION = 8

# Scalar deal fields become real columns so they are queryable and indexable.
# Order is the canonical column order.
SCALAR_FIELDS: tuple[str, ...] = (
    "listing_key",
    "source",
    "title",
    "url",
    "direct_url",
    "id",
    "status",
    "last_status",
    "first_seen_at",
    "last_seen_at",
    "posted_date",
    # Bidding window. `auction_start_date` is in the future on a catalog that is
    # posted but not yet open -- readers filter on it rather than on a stored
    # is-live flag, which would be stale the moment bidding opens.
    "auction_start_date",
    # The worker's own read of "can Adam bid on this right now". Secondary to
    # `auction_start_date`, which self-updates against the clock; this exists for
    # the sources that publish no bid-open timestamp at all (AuctionZip,
    # AuctionNinja, K-BID, eBay). Stored so the deal tables stop having to infer
    # openness from a date those sources never provide.
    "bidding_open",
    "auction_end_date",
    # `score` is the deterministic output of legoscout-deal-scoring, and the only
    # value the tables rank on. `quality_score` and `max_price` are its two
    # factors, promoted to columns so "what would I pay for this" is queryable.
    # `model_score` is the model's own advisory verdict -- recorded for the
    # divergence check, never mixed into `score`.
    "score",
    "last_score",
    "quality_score",
    "max_price",
    "model_score",
    "last_price",
    "notes",
    "cost_per_lb_note",
    "current_price",
    "buy_now_price",
    "static_price",
    "price_basis",
    "handling_fee",
    "estimated_total",
    "weight_lbs",
    "per_lb_price",
    "per_lb_price_basis",
    "listing_category",
    "exclusion_reason",
    "figure_count",
    "figure_count_source",
    "listing_type",
    "set_completeness",
    "set_condition",
    "potential_profit",
    "profit_incomplete",
    "used_avg_6mo",
    "new_avg_6mo",
    # eBay sold comps from `legoscout pricing comps`/`ebay-comps` -- this
    # SCALAR column is still an informational lot-level sum. The actual
    # profit input is the per-set blended BrickLink+eBay average inside the
    # `set_analysis` JSON field; see deal_schema.json.
    "ebay_avg_sold_price",
    "ebay_comp_count",
    "ebay_avg_price_per_lb",
    "ebay_avg_price_per_fig",
    "shipping_estimated",
    "confidence",
    "risks_unknowns",
    "winning_bid",
    "destination_zip_note",
    # Where the lot physically is, and how far that is from ZIP 47725. How it
    # can be RECEIVED is `available_fulfillment`, a JSON array -- see
    # available_fulfillment.py, the single reader of that question.
    "item_location",
    "pickup_miles",
    # The seller's ship-FROM ZIP, read during the crawl. `item_location` says
    # where the lot can be collected; this says where freight starts, and the
    # two differ whenever a warehouse is not the pickup counter.
    # estimate_inbound_shipping.py needs an origin, and without this column it
    # gets one by re-fetching the lot page through hibid_lot_state.py -- a
    # second hit on a page the crawler already read, on a source with a browser
    # policy and a block risk. Captured once, by the only agent holding the
    # authenticated session.
    "origin_zip",
    # Who is selling it. The marketplace's own key and the display name it
    # renders, captured at crawl time by the agent holding the authenticated
    # session -- no downstream reader can re-derive them without a second fetch.
    # 20 of the 22 sources publish a seller; Craigslist and StockX are anonymous
    # by design. A `null` therefore means one of two things, and the source registry
    # decides which: the source module writes no `seller_id()` on the anonymous
    # sources (the null is a FACT) and `true` everywhere else (the null is an
    # UNREAD field, named in the worker's evidence_summary). Never infer a name
    # from a title, a URL slug, or another row on the same source.
    "seller_id",
    "seller_name",
    # Set when BrickLink confirms the set exists but has zero sold comps in
    # BOTH conditions over the last 6 months -- resale is priced at $0 (a real,
    # scoreable loss) rather than left unscored. Explains that on hover on the
    # deals page. Never set when the set number itself is unconfirmed; see
    # legoscout-pricing's <pricing_basis>.
    "zero_comp_note",
    # Phase-2 link to the prospects table (prospects_db.py): which prospect
    # produced this deal. Deliberately NOT a declared FK: save() bulk
    # re-INSERTs every deal under foreign_keys=ON, and a dangling reference
    # would abort a full-ledger write over prospector bookkeeping. NULL on
    # every row until phase 2 starts writing it.
    "prospect_id",
)

# Stored as INTEGER 0/1 and round-tripped as real bools.
BOOL_FIELDS: tuple[str, ...] = (
    "profit_incomplete",
    "shipping_estimated",
    "bidding_open",
)

# Nested structures are stored as JSON text. `set_analysis` is deliberately here:
# it is a dict on some records and a list on others, so it has no stable columnar
# shape.
JSON_FIELDS: tuple[str, ...] = (
    # How the listing can be received: some non-empty subset of
    # ["local_pickup", "shipping"]. A set rather than an enum because a listing
    # can genuinely offer both. Read it only through available_fulfillment.py.
    "available_fulfillment",
    # The listing's photo URLs, captured during the crawl through that source's
    # authenticated CLI. The image pass cannot re-derive them: a plain fetch of
    # the listing page returns 403 on Shop The Salvation Army, an Incapsula
    # challenge on LiveAuctioneers, and a JS shell on Poshmark, Mercari, and
    # Depop. A missing list is therefore indistinguishable from a seller who
    # posted no photos -- which is why the crawler stores what it already had in
    # hand. An empty list means "looked, none published"; None means "not
    # captured".
    "image_urls",
    "shipping_estimate",
    # What was seen, never what it is worth: Python's text scan plus the model's
    # image read, as enums and evidence strings. Written by
    # legoscout-deal-scoring, which is also the only thing that turns it into a
    # number. `scoring` is that number plus its full derivation.
    "observations",
    "scoring",
    "fee_breakdown",
    "set_numbers",
    "set_analysis",
    # The classifier's evidence-backed correction of a crawl price the listing
    # text contradicts ({price, evidence}). Kept verbatim on the record so the
    # correction's evidence survives next to the numbers it moved -- the deals
    # page can show WHY a $5 tile is stored at a $200 ask. Applied to the
    # priced columns by build_record._apply_price_override, never re-applied by
    # readers.
    "price_override",
    "verification",
)

# Top-level ledger keys other than `deals` and `source_watermarks`.
META_FIELDS: tuple[str, ...] = (
    "schema_version",
    "updated_at",
    "ledger_contract",
    "latest_run_hint",
    "last_migration",
)

# The meta row holding the monotonic ledger revision, and the key `load_document()`
# stamps it onto the document under. Deliberately NOT in META_FIELDS: it is
# concurrency bookkeeping owned by this module, not a ledger field a caller
# sets. `save()` compares it and increments it inside one write transaction.
_REVISION_KEY = "_revision"

_COLUMNS = SCALAR_FIELDS + JSON_FIELDS

# Columns the schema used to have and must not grow back. A retired column is
# dropped on connect so a database restored from an older copy converges on the
# current shape instead of quietly answering with a stale field.
#
# Each retirement ran its one-time migration over the live ledger first, and
# those scripts are deleted. A database old enough to still hold values in one
# of these columns therefore loses them on connect: copy the columns out by hand
# before you connect, rather than writing a new migration script.
#   `is_live`      -- a stored live/not-live flag, wrong the moment bidding opens;
#                     readers compare auction_start_date/auction_end_date instead.
#   `fulfillment`  -- the ship/local_pickup/both/unknown enum, replaced by the
#                     `available_fulfillment` set on 2026-07-26.
#   the four signal objects -- `visual_assessment`, `minifigure_signal`,
#                     `brand_theme_signal`, `score_adjustments`. They duplicated
#                     each other's fields and stored model-authored point values
#                     with inconsistent signs. Facts now live in `observations`
#                     and numbers in `scoring`, since 2026-07-26.
#   `display`, `display_missing_fields`
#                  -- a 29-field caller-facing copy of the record, built beside
#                     every deal and stored as JSON. It held 24% of the whole
#                     database and every field in it was either a restatement of
#                     a column or a formatted string a reader could format
#                     itself, so the copy and the column drifted apart unseen.
#                     `display_missing_fields` was read only by its own test.
#                     Retired 2026-08-04: 1,088 rows carried `risks_unknowns`
#                     prose and 85 carried a BrickLink comp answer that existed
#                     nowhere else, and all of those were copied out first.
RETIRED_COLUMNS: tuple[str, ...] = (
    "is_live",
    "fulfillment",
    "visual_assessment",
    "minifigure_signal",
    "brand_theme_signal",
    "score_adjustments",
    "display",
    "display_missing_fields",
)

# Numeric columns are declared with NO datatype, which gives them BLOB affinity.
# That is deliberate: NUMERIC/INTEGER affinity silently rewrites a lossless float
# to an integer (0.0 -> 0, 25.0 -> 25), which breaks exact round-tripping of the
# ledger. BLOB affinity stores the value's storage class verbatim, and SQLite
# still compares and indexes it numerically.
_NUMERIC = {
    "score",
    "last_score",
    "quality_score",
    "max_price",
    "model_score",
    "current_price",
    "buy_now_price",
    "static_price",
    "handling_fee",
    "estimated_total",
    "weight_lbs",
    "per_lb_price",
    "potential_profit",
    "used_avg_6mo",
    "new_avg_6mo",
    "ebay_avg_sold_price",
    "ebay_comp_count",
    "ebay_avg_price_per_lb",
    "ebay_avg_price_per_fig",
    "figure_count",
    "figure_count_source",
    "winning_bid",
    "pickup_miles",
    # An integer key, not a measurement. It is here for the affinity, not the
    # float safety: TEXT affinity would store integer 42 as '42' and silently
    # break every join against prospects.prospect_id.
    "prospect_id",
}


def _column_ddl() -> str:
    parts = []
    for col in SCALAR_FIELDS:
        if col == "listing_key":
            parts.append("listing_key TEXT PRIMARY KEY")
        elif col in _NUMERIC:
            parts.append(col)  # no datatype -> BLOB affinity, see _NUMERIC note
        elif col in BOOL_FIELDS:
            parts.append(f"{col} INTEGER")
        else:
            parts.append(f"{col} TEXT")
    for col in JSON_FIELDS:
        parts.append(f"{col} TEXT")
    # Preserves the original key order of each record so round-tripping the
    # document reproduces the JSON file exactly.
    parts.append("_key_order TEXT NOT NULL")
    return ",\n    ".join(parts)


def _schema_sql() -> str:
    return f"""
CREATE TABLE IF NOT EXISTS deals (
    {_column_ddl()}
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS source_watermarks (
    source TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_deals_source ON deals(source);
CREATE INDEX IF NOT EXISTS idx_deals_status ON deals(status);
CREATE INDEX IF NOT EXISTS idx_deals_listing_type ON deals(listing_type);
CREATE INDEX IF NOT EXISTS idx_deals_score ON deals(score);
CREATE INDEX IF NOT EXISTS idx_deals_auction_end ON deals(auction_end_date);
CREATE INDEX IF NOT EXISTS idx_deals_profit ON deals(potential_profit);
CREATE INDEX IF NOT EXISTS idx_deals_per_lb ON deals(per_lb_price);
"""


def connect(path: str = DB_PATH) -> sqlite3.Connection:
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"Ledger database missing: {path}. "
            "It is the only ledger; there is no JSON export to rebuild it from. "
            "Restore the newest copy from ~/legoscout-snapshots/, "
            "or from Dropbox version history."
        )
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _add_missing_columns(conn)
    _ensure_indexes(conn)
    return conn


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    """Bring an existing database up to the current field list.

    Fields get added to SCALAR_FIELDS/JSON_FIELDS as the pipeline learns to
    capture more; without this the next write fails on a column the code knows
    about and the file does not. Retired columns in RETIRED_COLUMNS are dropped
    for the mirror-image reason: a database restored from an older copy would
    otherwise keep answering with a field nothing reads any more. Nothing is
    renamed or backfilled here -- that is a migration script's job.
    """
    have = {r["name"] for r in conn.execute("PRAGMA table_info(deals)")}
    for col in _COLUMNS:
        if col in have:
            continue
        decl = "" if col in _NUMERIC else " TEXT"
        if col in BOOL_FIELDS:
            decl = " INTEGER"
        conn.execute(f"ALTER TABLE deals ADD COLUMN {col}{decl}")
    for col in RETIRED_COLUMNS:
        if col in have:
            conn.execute(f"ALTER TABLE deals DROP COLUMN {col}")
    conn.commit()


# Indexes added after the first release. They have exactly ONE home -- this
# tuple -- and are deliberately absent from _schema_sql(), because connect()
# runs _ensure_indexes on a fresh database too. Each entry is (name, ddl): the
# name is what _ensure_indexes looks up in sqlite_master.
_INDEX_DDL: tuple[tuple[str, str], ...] = (
    (
        "idx_deals_prospect_id",
        "CREATE INDEX IF NOT EXISTS idx_deals_prospect_id ON deals(prospect_id)",
    ),
)


def _ensure_indexes(conn: sqlite3.Connection) -> None:
    """Indexes an existing database predates.

    _add_missing_columns covers columns; nothing ever re-runs _schema_sql
    against the live file, so new indexes are created here, on every
    connect, idempotently.

    sqlite_master is read FIRST. connect() is on every read path too, and
    CREATE INDEX takes a write lock whenever the index is missing -- so issuing
    the DDL unconditionally made load_document() and get_deal() wait on any concurrent
    writer for a migration they did not need.
    """
    have = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'")
    }
    missing = [ddl for name, ddl in _INDEX_DDL if name not in have]
    if not missing:
        return
    for ddl in missing:
        conn.execute(ddl)
    conn.commit()


def init(path: str = DB_PATH) -> sqlite3.Connection:
    """Create the database and schema if absent. Used by the migration only."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_schema_sql())
    conn.commit()
    return conn


def _row_to_deal(row: sqlite3.Row) -> dict[str, Any]:
    """Rebuild a deal dict in its original key order.

    `_key_order` decides ORDER, never membership. It used to decide both, which
    made a populated column unreadable: `facebook|1711205646851978` held
    `used_avg_6mo = 34.2` and `new_avg_6mo = 62.4476` in the table while every
    reader saw neither, because the record's stored key order predated those two
    fields. 17 comp values were hidden that way, and the deals page only showed
    them because the retired `display` object happened to carry a second copy --
    exactly the drift that copy existed to cause.

    So: named keys first, in their recorded order, then any other column that
    actually holds a value. A NULL column stays absent, because "no column" and
    "column set to null" are the same answer here and inventing the key on every
    row would rewrite every record's shape.
    """
    raw = dict(row)
    key_order = json.loads(raw.pop("_key_order"))
    # A retired field can still be named in an old row's _key_order. It has no
    # column any more, so emitting it would resurrect it as a permanent `None`
    # that reads like "recorded, but empty".
    ordered = [k for k in key_order if k in _COLUMNS]
    trailing = [k for k in _COLUMNS if k not in set(ordered) and raw.get(k) is not None]

    out: dict[str, Any] = {}
    for key in ordered + trailing:
        if key in JSON_FIELDS:
            stored = raw.get(key)
            out[key] = json.loads(stored) if stored is not None else None
        elif key in BOOL_FIELDS:
            val = raw.get(key)
            out[key] = None if val is None else bool(val)
        else:
            out[key] = raw.get(key)
    return out


def _deal_to_params(deal: dict[str, Any]) -> list[Any]:
    params: list[Any] = []
    for col in SCALAR_FIELDS:
        val = deal.get(col)
        if col in BOOL_FIELDS and val is not None:
            val = int(bool(val))
        params.append(val)
    for col in JSON_FIELDS:
        val = deal.get(col)
        params.append(None if col not in deal else json.dumps(val))
    # Only real columns go into _key_order. A caller still passing a retired
    # field would otherwise write its name back and have it reappear as None on
    # the next load, undoing the migration one save at a time.
    params.append(json.dumps([k for k in deal if k in _COLUMNS]))
    return params


def _deals(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Every deal row as a dict, in stored order. One reader, two callers."""
    return [_row_to_deal(r) for r in conn.execute("SELECT * FROM deals ORDER BY rowid")]


def load_deals(path: str = DB_PATH) -> list[dict[str, Any]]:
    """Every deal in the ledger, as a list of dicts, in stored order.

    This is the read a caller means when it writes `for deal in ...`. Each
    element answers `.get(...)`, carries every schema field, and has its JSON
    columns already decoded. Use `query(sql, params)` instead when the answer is
    a subset, a filter, or an aggregate -- this one materialises the whole table.
    """
    conn = connect(path)
    try:
        return _deals(conn)
    finally:
        conn.close()


def load_document(path: str = DB_PATH) -> dict[str, Any]:
    """The full ledger DOCUMENT -- the mapping `save(doc)` takes back.

    Returns `{schema_version, updated_at, deals: [...], ledger_contract,
    latest_run_hint, last_migration, source_watermarks}`. Iterating the result
    yields those KEY STRINGS, not deals. Call `load_deals()` when you want the
    records.

    The document also carries `_revision`, the ledger's revision at the instant
    it was read. `save()` requires it and refuses the write if the database has
    moved on since. Pass the document back as it came; do not rebuild it.
    """
    conn = connect(path)
    try:
        return _document_from_connection(conn)
    finally:
        conn.close()


def load_document_readonly(path: str = DB_PATH) -> dict[str, Any]:
    """Read the ledger document without schema migration writes.

    Display routes use this path. A page refresh must fail on an unsupported
    schema, rather than change Adam's ledger while it reads it.
    """
    conn = connect_readonly(path)
    try:
        return _document_from_connection(conn)
    finally:
        conn.close()


def _document_from_connection(conn: sqlite3.Connection) -> dict[str, Any]:
    """Build the familiar document shape from an open ledger connection."""
    doc: dict[str, Any] = {}
    meta = {r["key"]: json.loads(r["value"]) for r in conn.execute("SELECT key, value FROM meta")}
    for field in META_FIELDS:
        if field in meta:
            doc[field] = meta[field]
    doc["deals"] = _deals(conn)
    watermarks = {
        r["source"]: json.loads(r["payload"])
        for r in conn.execute("SELECT source, payload FROM source_watermarks ORDER BY source")
    }
    if watermarks or "source_watermarks" in meta:
        doc["source_watermarks"] = watermarks
    # Restore the original top-level key order.
    order = meta.get("_top_level_order")
    if order:
        doc = {k: doc[k] for k in order if k in doc} | {
            k: v for k, v in doc.items() if k not in order
        }
    doc[_REVISION_KEY] = _read_revision(conn)
    return doc


# How many bad records a failed save reports before it stops listing them. A
# whole-ledger write can fail on hundreds at once, and the first few name the
# defect just as well as all of them.
_MAX_REPORTED = 20


class StaleWrite(RuntimeError):
    """A whole-ledger `save()` built on a read that is no longer current.

    Raised, never smoothed over. There is no retry, no three-way merge and no
    last-write-wins here on purpose: `save()` cannot tell an intentional
    deletion from a row it simply never saw, so "resolving" the conflict means
    guessing which of two workers' findings to throw away.
    """


def _read_revision(conn: sqlite3.Connection) -> int:
    """The ledger's current revision. A database that has none is at 0."""
    row = conn.execute(
        "SELECT value FROM meta WHERE key = ?", (_REVISION_KEY,)).fetchone()
    return 0 if row is None else int(json.loads(row["value"]))


def _bump_revision(conn: sqlite3.Connection, current: int) -> int:
    """Advance the revision inside the caller's open write transaction."""
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                 (_REVISION_KEY, json.dumps(current + 1)))
    return current + 1


def _validate_deals(deals: list[dict[str, Any]]) -> None:
    """Every record must match `deal_schema.json` before it is written.

    The schema was documentation for its whole life. Nothing ran it, so drift
    accumulated silently and was only found by running it over the stored ledger
    on 2026-08-05: 331 rows whose `set_analysis` was an array the schema typed as
    an object, 51 rows keeping a comp REASON inside a field typed `number|null`,
    and 580 `null`s in fields typed `string`. None of it was visible as a
    failure; a string in a numeric field just dropped that row out of every
    profit calculation while still looking populated.

    It runs on the whole batch and names every bad record at once, rather than
    raising on the first. A run that assembled 40 records wants one list of what
    is wrong with them, not forty rounds of fix-and-retry. Nothing is written
    when any record fails: a half-migrated ledger is worse than an unmigrated
    one.
    """
    problems = []
    for record in deals:
        try:
            deal_schema.validate(record)
        except deal_schema.Invalid as exc:
            problems.append(str(exc))
        duplicate_set_nos = deal_schema.duplicate_set_analysis_set_numbers(record)
        if duplicate_set_nos:
            # A 2026-08-20 review found build_deal_record() guards its own
            # comps input, but every OTHER writer (rescore, sweep, invalidate)
            # calls save()/upsert_deals() directly and bypassed that guard
            # entirely -- 10 live rows already carried this defect, 5 of them
            # active, before this check existed here. This is the one gate
            # every writer actually passes through; the check belongs here,
            # not only in the assembly function some callers skip.
            problems.append(
                "%s: set_analysis has duplicate set_no: %s -- each set's "
                "resale value must be counted at most once against its "
                "allocated cost share"
                % (record.get("listing_key", "<no listing_key>"),
                   ", ".join(duplicate_set_nos)))
    if not problems:
        return
    shown = problems[:_MAX_REPORTED]
    more = len(problems) - len(shown)
    raise deal_schema.Invalid(
        "%d of %d records do not match deal_schema.json, so NOTHING was "
        "written:\n  %s%s"
        % (len(problems), len(deals), "\n  ".join(shown),
           "\n  ...and %d more" % more if more else ""))


def save(doc: dict[str, Any], path: str = DB_PATH) -> None:
    """Replace the whole ledger with `doc`, atomically, if nobody moved it first.

    `doc` MUST be a document `load_document()` returned, because the `_revision`
    it carries is what proves this write is not built on a stale read. A save
    whose revision no longer matches the database RAISES `StaleWrite`. It is
    never retried, never merged, and never allowed to win: this function's whole
    body is `DELETE FROM deals` followed by a re-insert of the caller's list, so
    a stale document does not overwrite a conflicting row, it deletes every row
    the other writer added.

    That is not theoretical. Two processes each loaded a 3-deal ledger, appended
    one distinct deal, and saved; both returned successfully and the table ended
    with 4 rows, holding only the SECOND writer's deal. The first worker's find
    was gone with no error anywhere. `ledger/sweep.py`, `scoring/rescore.py` and
    `invalidate/sweep.py` all save whole documents, while the deals page writes
    status from Adam's clicks, so the overlap is a normal Tuesday.

    Prefer `upsert_deals()` for a run that adds or updates records. It touches
    only the rows it was given, so it neither needs nor invalidates a whole-file
    read, and two runs writing different sources cannot collide at all.
    """
    if "deals" not in doc:
        raise ValueError("ledger document has no 'deals' key")
    if _REVISION_KEY not in doc:
        raise StaleWrite(
            "the document passed to save() carries no %r, so there is no way to "
            "tell whether it is current. Build it with load_document(), which "
            "stamps the revision it read, rather than assembling a bare dict."
            % _REVISION_KEY)
    expected = doc[_REVISION_KEY]
    _validate_deals(doc["deals"])
    conn = connect(path)
    try:
        # BEGIN IMMEDIATE, not the implicit deferred transaction `with conn`
        # opens. The revision check is only worth anything if it and the write
        # are the same exclusive transaction; a deferred one reads the revision
        # under a shared lock and takes the write lock later, which is the exact
        # window the check exists to close.
        conn.isolation_level = None
        conn.execute("BEGIN IMMEDIATE")
        try:
            current = _read_revision(conn)
            if current != expected:
                raise StaleWrite(
                    "the ledger moved from revision %r to %r while this document "
                    "was being built, so saving it would delete every row the "
                    "other writer added. Re-read with load_document(), reapply "
                    "this change, and save again -- or use upsert_deals() to "
                    "write just the records you touched."
                    % (expected, current))
            conn.execute("DELETE FROM deals")
            conn.execute("DELETE FROM source_watermarks")
            placeholders = ", ".join("?" for _ in range(len(_COLUMNS) + 1))
            cols = ", ".join(list(_COLUMNS) + ["_key_order"])
            conn.executemany(
                f"INSERT INTO deals ({cols}) VALUES ({placeholders})",
                [_deal_to_params(d) for d in doc["deals"]],
            )
            for source, payload in (doc.get("source_watermarks") or {}).items():
                conn.execute(
                    "INSERT INTO source_watermarks (source, payload) VALUES (?, ?)",
                    (source, json.dumps(payload)),
                )
            for field in META_FIELDS:
                if field in doc:
                    conn.execute(
                        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                        (field, json.dumps(doc[field])),
                    )
            # `_revision` is bookkeeping, not a ledger field, so it is kept out
            # of the stored key order -- otherwise it would come back as a
            # top-level document key and every reader would have to know it.
            conn.execute(
                "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
                ("_top_level_order",
                 json.dumps([k for k in doc if k != _REVISION_KEY])),
            )
            _bump_revision(conn, current)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
    # Local import: sellers_db imports ledger_db.connect(), so importing it at
    # module load time here would deadlock the two modules on load order. This
    # runs only after the transaction above committed cleanly -- every
    # full-ledger save upserts the seller behind every deal that carries one,
    # which is the whole of how the sellers table populates itself.
    from . import sellers as sellers_db
    sellers_db.upsert_seen_bulk(doc["deals"], path=path)


def upsert_deals(deals: list[dict[str, Any]], path: str = DB_PATH) -> dict[str, int]:
    """Write just these records. The concurrency-safe way for a run to store.

    Returns `{"inserted": n, "updated": n}`, counted by whether the listing_key
    already existed. Every record is schema-validated first, and NOTHING is
    written if any fails -- the same all-or-nothing rule `save()` uses.

    This exists so a run never has to overwrite the whole ledger to add a row.
    `save()` deletes every deal and re-inserts the caller's list, which makes two
    concurrent load-modify-save cycles mutually destructive; this touches only
    the listing_keys it was handed, so an appraiser finishing a ShopGoodwill
    batch and a sweep updating eBay rows do not interact at all. It takes no
    revision because it needs none: it never deletes a row it was not told about.

    A whole-ledger `save()` is still the right call for a migration or a rewrite
    that genuinely replaces the file. It is the wrong call for "I found 12 more
    deals".
    """
    _validate_deals(deals)
    conn = connect(path)
    try:
        conn.isolation_level = None
        conn.execute("BEGIN IMMEDIATE")
        try:
            keys = [d["listing_key"] for d in deals]
            existing = {
                r["listing_key"] for r in conn.execute(
                    "SELECT listing_key FROM deals WHERE listing_key IN (%s)"
                    % ", ".join("?" for _ in keys), keys)
            } if keys else set()
            placeholders = ", ".join("?" for _ in range(len(_COLUMNS) + 1))
            cols = ", ".join(list(_COLUMNS) + ["_key_order"])
            updates = ", ".join(
                "%s = excluded.%s" % (c, c) for c in list(_COLUMNS) + ["_key_order"]
                if c != "listing_key")
            conn.executemany(
                f"INSERT INTO deals ({cols}) VALUES ({placeholders}) "
                f"ON CONFLICT(listing_key) DO UPDATE SET {updates}",
                [_deal_to_params(d) for d in deals],
            )
            current = _read_revision(conn)
            _bump_revision(conn, current)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
    from . import sellers as sellers_db
    sellers_db.upsert_seen_bulk(deals, path=path)
    return {"inserted": len(set(keys) - existing), "updated": len(existing)}


def connect_readonly(path: str = DB_PATH) -> sqlite3.Connection:
    """A connection SQLite itself will not let anything write through.

    `mode=ro` is enforced by the engine, below the SQL grammar, so it holds for
    every statement form -- including the ones a prefix test cannot see coming.
    The path is turned into a URI with `Path.as_uri()` so a space or a `?` in a
    directory name cannot break the query string.

    This deliberately skips the `_add_missing_columns` / `_ensure_indexes` pass
    that `connect()` runs: both take a write lock, and a read is not the place to
    migrate. A query naming a column an older database does not have will fail
    loudly here, which is the correct answer -- `save()` and `load_document()`
    still migrate on their own write-capable connections.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"Ledger database missing: {path}. "
            "It is the only ledger; there is no JSON export to rebuild it from. "
            "Restore the newest copy from ~/legoscout-snapshots/, "
            "or from Dropbox version history."
        )
    conn = sqlite3.connect(
        pathlib.Path(path).as_uri() + "?mode=ro",
        uri=True,
        timeout=READONLY_TIMEOUT_SECONDS,
    )
    conn.row_factory = sqlite3.Row
    return conn


def query(sql: str, params: tuple = (), path: str = DB_PATH) -> list[dict[str, Any]]:
    """Run a read-only SQL query against the ledger and return dict rows.

    READ-ONLY IS ENFORCED BY THE ENGINE, not by inspecting the statement. The
    string test below is kept only to reject an obviously wrong call early with a
    clear message; it is not the guard. It cannot be the guard. SQLite accepts
    `WITH x AS (SELECT 1) DELETE FROM deals`, and that passed the
    `startswith("with")` test and committed: a live check ran it against a copy
    of the ledger and took it from 2314 deals to 0, with `query()` returning `[]`
    and raising nothing. `UPDATE` and `INSERT` have the same CTE form. The
    ledger is the single source of truth and is gitignored, so a silent
    whole-table delete through the documented READ api is unrecoverable.
    """
    stripped = sql.lstrip().lower()
    if not (stripped.startswith("select") or stripped.startswith("with")):
        raise ValueError("query() accepts SELECT/WITH statements only")
    conn = connect_readonly(path)
    try:
        return [dict(r) for r in conn.execute(sql, params)]
    finally:
        conn.close()


# The statuses a caller may SET through `update_status()`. `blocked` and
# `unavailable` are not in this set -- see `display/server.py`, which has
# always enforced exactly this list on the page's write route. An unlisted
# value used to reach the column unchecked, so a typo became a status no
# reader recognised and every per-status query silently dropped the row.
#
# `unavailable` and `blocked` each have their own single-row primitive,
# `mark_unavailable()` and `mark_blocked()`, below -- for a human or agent
# confirming ONE listing is gone or wall-blocked, the same mutation shape
# `invalidate/sweep.py`'s bulk run applies to a whole batch via one batched
# `upsert_deals()` call. Both are deliberately absent from SETTABLE_STATUS
# because they need a third argument (`evidence`) `update_status()`'s
# three-argument shape has no room for, not because a person can never set
# them.
SETTABLE_STATUS = ("active", "rejected", "inquired", "bid_placed", "purchased")


class UnknownStatus(ValueError):
    """A status outside `SETTABLE_STATUS`. Never softened into a write."""


def update_status(
    listing_key: str,
    status: str,
    last_seen_at: str,
    path: str = DB_PATH,
) -> bool:
    """Set status/last_status/last_seen_at on one deal. Returns True if the deal
    existed.

    This is a single-row transaction, not a read-modify-write of the whole
    ledger, so concurrent clicks cannot lose each other's write.

    It used to mirror the same two values into a `display` object as well. There
    is no second copy of a record any more, so there is nothing left to keep in
    sync -- which is the point: the mirror is what could go stale.
    """
    if status not in SETTABLE_STATUS:
        raise UnknownStatus(
            "%r is not a settable status -- use one of %s. Use "
            "mark_unavailable(listing_key, evidence, last_seen_at) to confirm "
            "a listing is gone, or mark_blocked(listing_key, evidence, "
            "last_seen_at) to record a CAPTCHA/bot-wall that stopped a check."
            % (status, "/".join(SETTABLE_STATUS)))
    conn = connect(path)
    try:
        with conn:
            cursor = conn.execute(
                "UPDATE deals SET status = ?, last_status = ?, last_seen_at = ? "
                "WHERE listing_key = ?",
                (status, status, last_seen_at, listing_key),
            )
            return cursor.rowcount > 0
    finally:
        conn.close()


def get_deal(listing_key: str, path: str = DB_PATH) -> dict[str, Any] | None:
    """Fetch one deal by key without loading the whole ledger."""
    conn = connect(path)
    try:
        row = conn.execute(
            "SELECT * FROM deals WHERE listing_key = ?", (listing_key,)
        ).fetchone()
        return _row_to_deal(row) if row is not None else None
    finally:
        conn.close()


def _write_pipeline_status(
    listing_key: str,
    status: str,
    evidence: str,
    last_seen_at: str,
    path: str = DB_PATH,
) -> bool:
    """Shared body of `mark_unavailable()` and `mark_blocked()`.

    Both are single-row confirmations that need a third argument
    (`evidence`) `update_status()` has no room for, and both write it the
    same way: read the one row, set `status`/`last_status`, stamp
    `last_seen_at`, append a dated evidence note, and write back through
    `upsert_deals()` rather than `save()`, so a confirmation can never
    collide with a concurrent sweep or another confirmation the way two
    `save()` calls could.

    Returns True if the deal existed and was written, False if
    `listing_key` was not found.
    """
    deal = get_deal(listing_key, path)
    if deal is None:
        return False
    deal["status"] = status
    deal["last_status"] = status
    deal["last_seen_at"] = last_seen_at
    note = f" [Marked {status} {last_seen_at} by manual verification: {evidence}]"
    deal["notes"] = (deal.get("notes", "") + note).strip()
    upsert_deals([deal], path=path)
    return True


def mark_unavailable(
    listing_key: str,
    evidence: str,
    last_seen_at: str,
    path: str = DB_PATH,
) -> bool:
    """Confirm one listing is gone and write it, without a whole-ledger save().

    This is the single-row twin of `invalidate/sweep.py`'s bulk confirmation,
    for the case that script does not cover: a human or agent manually
    verifying ONE listing, rather than the batch sweep confirming many at once
    from the `load_deals()` list it already holds. Both write the same
    mutation shape -- `status`/`last_status` to `unavailable`, `last_seen_at`
    stamped, a dated evidence note appended -- and both go through
    `upsert_deals()` rather than `save()`, so a manual verification can never
    collide with a concurrent sweep or another manual check the way two
    `save()` calls could. `invalidate/sweep.py` itself batches every row it
    changes into ONE `upsert_deals()` call at the end of its run rather than
    calling this function per row, which is the right call for a run touching
    hundreds of rows; this function is the right call for exactly one.

    `unavailable` is deliberately absent from `SETTABLE_STATUS`: it needs the
    `evidence` this function requires, which `update_status()`'s three-argument
    shape has no room for.

    Returns True if the deal existed and was written, False if `listing_key`
    was not found.
    """
    return _write_pipeline_status(listing_key, "unavailable", evidence, last_seen_at, path=path)


def mark_blocked(
    listing_key: str,
    evidence: str,
    last_seen_at: str,
    path: str = DB_PATH,
) -> bool:
    """Confirm one listing hit a CAPTCHA/bot-wall and write it, without save().

    The single-row twin of `mark_unavailable()`, for the terminal state a live
    check reaches when the source itself refused to answer -- an Imperva or
    Incapsula wall, a reCAPTCHA/hCaptcha prompt, a Facebook checkpoint. It is
    never a guess about the listing's own availability: `blocked` records that
    THIS source could not be checked, not that the item is gone. Per the
    project's hard rule, a wall is recorded and never bypassed.

    `blocked` is deliberately absent from `SETTABLE_STATUS` for the same
    reason `unavailable` is: it needs the `evidence` this function requires.

    Returns True if the deal existed and was written, False if `listing_key`
    was not found.
    """
    return _write_pipeline_status(listing_key, "blocked", evidence, last_seen_at, path=path)


if __name__ == "__main__":
    import sys

    doc = load_document()
    print(
        json.dumps(
            {
                "schema_version": doc.get("schema_version"),
                "updated_at": doc.get("updated_at"),
                "deals": len(doc["deals"]),
                "sources": len(doc.get("source_watermarks") or {}),
            },
            indent=2,
        )
    )
    if len(sys.argv) > 1:
        for row in query(sys.argv[1]):
            print(json.dumps(row, default=str))
