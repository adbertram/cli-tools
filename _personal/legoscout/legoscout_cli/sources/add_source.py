#!/usr/bin/env python3
"""Register a new source in the source registry, the same way every time.

The registry -- the `sources` tables in `found_deals.db` -- is the single source
of truth for every marketplace. Before this script, an add was a hand-crafted
edit plus a manual bump of the active count pin in test_registry.py, and the
procedure lived in nobody's head twice the same way. This script is that
procedure, deterministically:

    legoscout sources add --template <namespace>   # skeleton entry -> stdout
    legoscout sources add <entry.json> --dry-run   # validate only, write nothing
    legoscout sources add <entry.json>             # validate, append, bump, verify
    legoscout sources remove <namespace>    # undo an add that failed verify

Exit codes:
    0  success. stdout is one JSON summary and nothing else.
    1  refused. stdout empty, one problem per line on stderr, nothing written.
    2  usage error (argparse).
    4  the registry was written and is well formed, but post-write verification
       (registry.py --check + test_registry.py) failed. stderr carries the
       failing output verbatim and the exact --retract command.

Every validation rule runs BEFORE any write, and every failure is reported,
not just the first. The structural rules (namespace == key, listing_key_format
prefix, unique short) are not restated here: the merged document is checked
through registry.check(), the same code path the live registry answers to. A
researched fact the template asks for -- capability evidence, a fee block or an
explicit null -- is refused when missing, never defaulted.

A new source also needs a reader module at
`legoscout_cli/sources/readers/<namespace>.py`. The registry no longer
carries extraction data; the module does.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

from . import registry  # noqa: E402

DB_PATH = registry.DB_PATH

NAMESPACE_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STATUSES = ("active", "dormant")
OFFER_METHODS = ("button", "message", "none")
FEE_FIELDS = ("premium_pct_default", "sales_tax_rule", "sales_tax_pct_default",
              "tax_basis", "verified_at", "evidence", "confidence")
PAYLOAD_TOKEN_LIMIT = 2000  # test_registry.py pins every payload under this


def skeleton(namespace):
    """A complete entry with a TODO marker on every fact that needs research.

    JSON has no comments, so the TODO text IS the research instruction. The
    validator refuses any entry that still contains the substring TODO, so a
    half-filled template cannot reach the registry.
    """
    return {namespace: {
        "display_name": "TODO(the marketplace's own name, exact spelling)",
        "aliases": [],
        "short": "TODO(unique short label for tables, e.g. 'SGW')",
        "status": "TODO(active|dormant)",
        "namespace": namespace,
        "listing_key_format": namespace + "|TODO(<id shape from real URLs>)",
        "access": {
            "method": "TODO('CLI first' when a cli-tools CLI exists, else "
                      "'Runtime browser' or 'Direct fetch, no CLI/browser "
                      "needed')",
            "how": "TODO(the exact commands or URLs verified live, with the "
                   "date. Name the CLI skill files to load when method is "
                   "CLI first)",
            "notes": "TODO(sort order and its recency-sort exception, auth "
                     "quirks, rate limits -- what the next worker must know)",
            "auth_required": "TODO(true|false)",
        },
        "capability": {
            "can_offer": "TODO(true|false)",
            "offer_method": "TODO(button|message|none)",
            "conditional": "TODO(true|false -- true when the control is "
                           "per-listing)",
            "notes": "TODO(how an offer works on this marketplace)",
            "evidence": "TODO(help-page URL and what it says)",
            "verified_at": "TODO(YYYY-MM-DD)",
        },
        "fees": "TODO(a full block with premium_pct_default, sales_tax_rule, "
                "sales_tax_pct_default, tax_basis, verified_at, evidence, "
                "confidence -- or the JSON value null, which makes "
                "fee_config raise until the fees are researched)",
        "notes": [{
            "id": namespace + "-TODO(YYYY-MM-DD)-1",
            "date": "TODO(YYYY-MM-DD)",
            "text": "TODO(how this source was researched and added: what was "
                    "verified live, on what date, with what commands)",
            "supersedes": None,
        }],
        "auction_tier": "TODO(never|always|mixed)",
    }}


def template_problems(namespace, doc):
    problems = []
    if not NAMESPACE_RE.match(namespace):
        problems.append("namespace %r must match %s"
                        % (namespace, NAMESPACE_RE.pattern))
    if namespace in doc["sources"]:
        problems.append("%s is already a registered source" % namespace)
    if namespace in doc["discovery_rows"]:
        problems.append("%s is a discovery row, not a source namespace"
                        % namespace)
    return problems


def _is_date(value):
    return isinstance(value, str) and DATE_RE.match(value) is not None


def _check_scaffold(entry_doc, doc):
    """The rules that must hold before field-level rules can run."""
    problems = []
    if not isinstance(entry_doc, dict) or len(entry_doc) != 1:
        problems.append("the entry file must hold exactly one top-level key, "
                        "the namespace")
        return problems, None, None
    namespace = next(iter(entry_doc))
    entry = entry_doc[namespace]
    if not isinstance(entry, dict):
        problems.append("%s: the entry must be an object" % namespace)
        return problems, None, None
    problems.extend(template_problems(namespace, doc))
    if entry.get("namespace") != namespace:
        problems.append("%s: the namespace field says %r"
                        % (namespace, entry.get("namespace")))
    if "TODO" in json.dumps(entry, ensure_ascii=False):
        problems.append("%s: the entry still contains a TODO marker -- every "
                        "one is unfinished research" % namespace)
    return problems, namespace, entry


def _check_fields(namespace, entry, doc):
    problems = []
    for field in registry.REQUIRED + ("aliases",):
        if field not in entry:
            problems.append("%s: missing %r" % (namespace, field))
    if "fees" not in entry:
        problems.append("%s: missing the 'fees' key -- unresearched fees are "
                        "an explicit null, never an absent key" % namespace)

    if entry.get("status") not in STATUSES:
        problems.append("%s: status must be one of %s, got %r"
                        % (namespace, "|".join(STATUSES), entry.get("status")))
    if not (isinstance(entry.get("display_name"), str)
            and entry.get("display_name")):
        problems.append("%s: display_name must be a non-empty string" % namespace)
    if not (isinstance(entry.get("short"), str) and entry.get("short")):
        problems.append("%s: short must be a non-empty string" % namespace)
    aliases = entry.get("aliases")
    if not (isinstance(aliases, list)
            and all(isinstance(a, str) and a for a in aliases)):
        problems.append("%s: aliases must be a list of non-empty strings"
                        % namespace)

    fmt = entry.get("listing_key_format", "")
    if not (isinstance(fmt, str) and fmt.startswith(namespace + "|")
            and len(fmt) > len(namespace) + 1):
        problems.append("%s: listing_key_format must be '%s|<id shape>'"
                        % (namespace, namespace))

    access = entry.get("access")
    if not isinstance(access, dict):
        problems.append("%s: access must be an object" % namespace)
    else:
        for field in ("method", "how", "notes"):
            if not (isinstance(access.get(field), str) and access.get(field)):
                problems.append("%s: access.%s must be a non-empty string"
                                % (namespace, field))
        if not isinstance(access.get("auth_required"), bool):
            problems.append("%s: access.auth_required must be a bool" % namespace)

    capability = entry.get("capability")
    if not isinstance(capability, dict):
        problems.append("%s: capability must be an object" % namespace)
    else:
        for field in ("can_offer", "conditional"):
            if not isinstance(capability.get(field), bool):
                problems.append("%s: capability.%s must be a bool"
                                % (namespace, field))
        if capability.get("offer_method") not in OFFER_METHODS:
            problems.append("%s: capability.offer_method must be one of %s"
                            % (namespace, "|".join(OFFER_METHODS)))
        if not (isinstance(capability.get("notes"), str)
                and capability.get("notes")):
            problems.append("%s: capability.notes must be a non-empty string"
                            % namespace)
        evidence = capability.get("evidence")
        if not (isinstance(evidence, str) and "http" in evidence):
            problems.append("%s: capability.evidence must cite a URL, the "
                            "help page the answer came from" % namespace)
        if not _is_date(capability.get("verified_at")):
            problems.append("%s: capability.verified_at must be YYYY-MM-DD"
                            % namespace)

    fees = entry.get("fees", None)
    if fees is not None and "fees" in entry:
        if not isinstance(fees, dict):
            problems.append("%s: fees must be a researched object or exactly "
                            "null" % namespace)
        else:
            for field in FEE_FIELDS:
                if field not in fees:
                    problems.append("%s: fees.%s is missing"
                                    % (namespace, field))
            if "evidence" in fees and not (
                    isinstance(fees["evidence"], str)
                    and "http" in fees["evidence"]):
                problems.append("%s: fees.evidence must cite a URL" % namespace)
            if "verified_at" in fees and not _is_date(fees["verified_at"]):
                problems.append("%s: fees.verified_at must be YYYY-MM-DD"
                                % namespace)

    notes = entry.get("notes")
    if not (isinstance(notes, list) and notes):
        problems.append("%s: notes must hold at least one dated note saying "
                        "how the source was researched" % namespace)
    else:
        id_re = re.compile(r"^%s-\d{4}-\d{2}-\d{2}-\d+$" % re.escape(namespace))
        for note in notes:
            if not isinstance(note, dict) or not all(
                    k in note for k in ("id", "date", "text", "supersedes")):
                problems.append("%s: every note needs id, date, text and "
                                "supersedes" % namespace)
                continue
            if not id_re.match(str(note["id"])):
                problems.append("%s: note id %r must be "
                                "'%s-<YYYY-MM-DD>-<n>'"
                                % (namespace, note["id"], namespace))
            elif not (_is_date(note["date"])
                      and str(note["id"]).startswith(
                          "%s-%s-" % (namespace, note["date"]))):
                problems.append("%s: note %r must embed its own date field %r"
                                % (namespace, note["id"], note["date"]))
            if note["supersedes"] is not None:
                problems.append("%s: note %r supersedes something, but a new "
                                "source has no history to supersede"
                                % (namespace, note["id"]))

    if entry.get("auction_tier") not in ("never", "always", "mixed"):
        problems.append("%s: auction_tier must be never|always|mixed, got %r"
                        % (namespace, entry.get("auction_tier")))
    return problems


def _check_collisions(namespace, entry, doc):
    """A new spelling must not resolve to an existing source, or key()
    resolution turns ambiguous."""
    problems = []
    taken = {}
    for name, existing in doc["sources"].items():
        spellings = ([name, existing.get("display_name")]
                     + list(existing.get("aliases", [])))
        for spelling in spellings:
            if spelling:
                taken[spelling.lower()] = name
    shorts = {e["short"] for e in doc["sources"].values()}

    display = entry.get("display_name")
    new_spellings = [namespace] + ([display] if isinstance(display, str) else [])
    aliases = entry.get("aliases")
    if isinstance(aliases, list):
        new_spellings += [a for a in aliases if isinstance(a, str)]
    for spelling in new_spellings:
        owner = taken.get(spelling.lower())
        if owner:
            problems.append("%s: %r already resolves to %s"
                            % (namespace, spelling, owner))
    if entry.get("short") in shorts:
        problems.append("%s: short %r is already taken"
                        % (namespace, entry.get("short")))
    return problems


def _check_merged(namespace, entry, doc):
    """Prove the registry that WOULD exist passes registry.check().

    `registry.check()` is a pure function over a document dict, so the proof is
    a deep copy with the candidate entry in it -- no scratch database, no write,
    and the same code path the live registry answers to.
    """
    merged = json.loads(json.dumps(doc))
    merged["sources"][namespace] = entry
    return ["merged registry: %s" % p for p in registry.check(merged)]


def _check_payload_size(namespace, entry, doc):
    merged_entry = dict(entry)
    merged_entry["notes_available"] = len(entry.get("notes", []))
    merged_entry["notes"] = []
    size = len(json.dumps(merged_entry))
    if size // 4 >= PAYLOAD_TOKEN_LIMIT:
        return ["%s: the worker payload is ~%d tokens; test_registry.py pins "
                "every payload under %d. Move history into notes."
                % (namespace, size // 4, PAYLOAD_TOKEN_LIMIT)]
    return []


def validate(entry_doc, doc):
    """Every problem with the candidate entry, as a list. Empty means sound."""
    problems, namespace, entry = _check_scaffold(entry_doc, doc)
    if entry is None:
        return problems
    problems += _check_fields(namespace, entry, doc)
    problems += _check_collisions(namespace, entry, doc)
    if not problems:
        # Structural gates run only on an otherwise-sound entry: a TODO-ridden
        # skeleton would drown the real report in derived noise.
        problems += _check_merged(namespace, entry, doc)
        problems += _check_payload_size(namespace, entry, doc)
    return problems


def _write_atomic(path, text):
    directory = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".add-source-",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def apply_entry(entry_doc, db_path):
    """Write one researched source through the registry's own transaction.

    Returns (namespace, entry, files_written). Raises SystemExit(1) with the
    problems on stderr when the fresh in-transaction read refuses the entry.
    The registry owns the write; this only supplies the rules it runs.
    """
    namespace = next(iter(entry_doc))
    entry = entry_doc[namespace]
    problems = registry.add_entry(namespace, entry,
                                  lambda doc: validate(entry_doc, doc))
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        raise SystemExit(1)
    return namespace, entry, [db_path]


def retract(namespace, db_path):
    """Undo an add: delete the source row and its notes.

    The registry lives in the same database as the deals, so an add is no longer
    a file a `git checkout` can restore. This is the reverse operation, and it is
    the only one: exit 4 points here.

    It REFUSES when the ledger already holds deals on that namespace. Deleting
    the source under them would leave rows whose `source` no reader can brief a
    worker for, and `source_names.CANONICAL` is built from this table.

    Returns a summary dict. Raises SystemExit(1) when the namespace is not
    registered or the ledger references it.
    """
    conn = registry._connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT payload FROM sources WHERE namespace = ?",
                (namespace,)).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                print("%s is not a registered source -- nothing to retract"
                      % namespace, file=sys.stderr)
                raise SystemExit(1)
            deals = conn.execute("SELECT COUNT(*) FROM deals WHERE source = ?",
                                 (namespace,)).fetchone()[0]
            if deals:
                conn.execute("ROLLBACK")
                print("%s has %d deal rows in the ledger -- retracting the "
                      "source would orphan every one of them. Delete or "
                      "re-source those deals first." % (namespace, deals),
                      file=sys.stderr)
                raise SystemExit(1)
            status = json.loads(row["payload"])["status"]
            notes = conn.execute(
                "DELETE FROM source_notes WHERE namespace = ?",
                (namespace,)).rowcount
            conn.execute("DELETE FROM sources WHERE namespace = ?", (namespace,))
            conn.execute("COMMIT")
        except BaseException:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()

    return {"namespace": namespace, "status": status, "notes_deleted": notes,
            "files_written": [db_path]}


def verify():
    """Re-check the whole registry after the write; return (ok, output)."""
    problems = registry.check()
    if not problems:
        return True, "registry.check(): sound"
    return False, "registry.check():\n" + "\n".join("  " + p for p in problems)


def summary(doc, namespace, status, dry_run, files_written, verification):
    active = sum(1 for e in doc["sources"].values() if e["status"] == "active")
    return {"namespace": namespace, "status": status,
            "sources_total": len(doc["sources"]), "active": active,
            "dry_run": dry_run, "files_written": files_written,
            "verification": verification}


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("entry", nargs="?",
                    help="path to a filled entry JSON file (from --template)")
    ap.add_argument("--template", metavar="NAMESPACE",
                    help="print a skeleton entry for this namespace and exit")
    ap.add_argument("--dry-run", action="store_true",
                    help="run every validation rule and write nothing")
    ap.add_argument("--retract", metavar="NAMESPACE",
                    help="delete this source and its notes -- the reverse of an "
                         "apply, for an add that failed verify")
    a = ap.parse_args()
    modes = [bool(a.template), bool(a.entry), bool(a.retract)]
    if sum(modes) != 1:
        ap.error("give exactly one of --template <namespace>, <entry.json>, or "
                 "--retract <namespace>")

    if a.retract:
        print(json.dumps(retract(a.retract, DB_PATH), indent=1))
        return 0

    doc = registry.sources.document()

    if a.template:
        problems = template_problems(a.template, doc)
        if problems:
            for problem in problems:
                print(problem, file=sys.stderr)
            return 1
        print(json.dumps(skeleton(a.template), indent=1, ensure_ascii=False))
        return 0

    try:
        with open(a.entry, encoding="utf-8") as fh:
            entry_doc = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print("cannot read %s: %s" % (a.entry, exc), file=sys.stderr)
        return 1

    problems = validate(entry_doc, doc)
    if problems:
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    namespace = next(iter(entry_doc))
    status = entry_doc[namespace]["status"]

    if a.dry_run:
        print(json.dumps(summary(doc, namespace, status, True, [], "skipped"),
                         indent=1))
        return 0

    namespace, entry, files_written = apply_entry(entry_doc, DB_PATH)
    ok, output = verify()
    if not ok:
        print(output, file=sys.stderr)
        print("\nThe registry was written and is well formed, but verification "
              "failed. Inspect, then fix forward or retract:\n"
              "  legoscout sources remove %s" % namespace,
              file=sys.stderr)
        return 4

    print(json.dumps(summary(registry.sources.document(), namespace, status,
                             False, files_written, "pass"), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
