#!/usr/bin/env python3
"""The single reader of registered prospecting hypothesis types.

A hypothesis type is ONE testable idea about where used LEGO inventory can be
sourced outside the marketplaces legoscout-sources already covers -- either
within 60 straight-line miles of ZIP 47725 for a local_pickup source, or
nationwide for a source that ships. Every prospects and prospect_runs row
names one, so the vocabulary belongs here rather than in each caller.

    legoscout prospects hypotheses                          # table of every type
    legoscout prospects hypotheses estate_sale_companies    # one type
    legoscout prospects hypotheses 'Estate Sale-Companies'  # any spelling works

An unregistered type raises. Register the idea -- description, rationale, and
live-URL evidence -- BEFORE exploring it, so the registry records what was
tried rather than trailing behind the runs.
"""
from .. import paths
import argparse
import json
import os
import re
import sys

CONFIG = paths.HYPOTHESIS_TYPES_JSON


class UnknownEntry(KeyError):
    """A type that is not registered. Never softened into a default."""

    def __str__(self):                       # KeyError repr()s its argument
        return self.args[0]


class Registry:
    """One JSON registry file, read through one code path.

    This class used to live in `legoscout sources` and serve
    both registries. The source registry moved into the deal ledger database, so
    the file-backed reader came here, to its one remaining user. It is read-only:
    a hypothesis type is registered by editing the JSON, never by an append.

    `collection` is the top-level object holding the entries. `subject` names
    them in error messages. `hint` says what to do about an unknown one.

    `normalize` turns a raw key into the table's spelling. It stays a parameter
    because the two registries disagreed about punctuation, and that history is
    what the `normalize()` docstring below records.
    """

    def __init__(self, path, collection, subject, hint, normalize=str.lower):
        self.path = path
        self.collection = collection
        self.subject = subject
        self.hint = hint
        self.normalize = normalize

    def document(self):
        """The whole file. Absent RAISES -- a registry is curated data, not a
        cache, so a missing file is a broken checkout and never 'no entries'."""
        with open(self.path, encoding="utf-8") as fh:
            return json.load(fh)

    def table(self):
        return self.document()[self.collection]

    def key(self, text):
        """Resolve any spelling to a table key.

        Accepts a key, a display name, or a registered alias. Display names are
        looked up in an index built FROM the data, never derived by a transform:
        no rule turns "EstateSales.NET" into `estatesales` while turning
        "EstateSales.org" into `estatesalesorg`, and `fees.source_key` -- which
        tried -- silently served the defaults block for every EstateSales.NET
        caller.
        """
        if not isinstance(text, str):
            raise TypeError(
                "a %s key must be a string, got %r (%s)"
                % (self.subject, text, type(text).__name__))
        raw = text.split("|", 1)[0].strip()
        if not raw:
            raise ValueError("no %s given" % self.subject)
        entries = self.table()
        if raw in entries:
            return raw
        normalized = self.normalize(raw)
        if normalized in entries:
            return normalized
        lowered = raw.lower()
        for name, entry in entries.items():
            spellings = [entry.get("display_name")] + list(entry.get("aliases", []))
            if any(s and s.lower() == lowered for s in spellings):
                return name
        raise UnknownEntry(
            "%r is not a registered %s in %s -- %s"
            % (raw, self.subject, os.path.basename(self.path), self.hint))

    def entry(self, text):
        return self.table()[self.key(text)]


def normalize(text):
    """Any spelling of a type name: strip, lower, spaces and hyphens -> '_'.

    Hyphens collapse here and must NOT collapse for sources: `K-BID` is a real
    namespace on 30 ledger rows, while `Estate Sale-Companies` and
    `estate_sale_companies` are the same idea. That is why Registry takes the
    normaliser as a parameter instead of picking one.
    """
    return re.sub(r"[\s-]+", "_", text.strip().lower())


TYPES = Registry(
    CONFIG, "types", "hypothesis type",
    "register the hypothesis with description, rationale and evidence BEFORE "
    "exploring it, rather than exploring unregistered ideas",
    normalize=normalize)


def table():
    return TYPES.table()


def type_key(text):
    """The registry key for any spelling.

    Raises on a non-string. It used to read `str(text or "")`, the banned `or`
    default: None and 0 became "" and reported as an empty type name, and 123
    became the key "123". Both hid the caller's real mistake.
    """
    try:
        return TYPES.key(text)
    except TypeError as exc:
        # The old contract was ValueError for both bad shapes, and
        # test_hypothesis_types.py plus prospects_db.py rely on it.
        raise ValueError(str(exc)) from exc
    except UnknownEntry:
        return normalize(text.strip())


def entry(hypothesis_type):
    return TYPES.entry(hypothesis_type)


def describe(hypothesis_type):
    return entry(hypothesis_type)["description"]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("hypothesis_type", nargs="?", help="registered hypothesis type")
    a = ap.parse_args()
    if a.hypothesis_type:
        try:
            print(json.dumps(entry(a.hypothesis_type), indent=1))
        except (KeyError, ValueError) as exc:
            sys.exit("hypothesis_types: %s" % exc)
        return
    rows = sorted(table().items())
    print("%-26s %-12s %s" % ("TYPE", "VERIFIED_AT", "DESCRIPTION"))
    for name, meta in rows:
        # A null verified_at is the registered unverified position, not a
        # missing value -- it prints as itself rather than as a blank.
        stamp = meta["verified_at"]
        if stamp is None:
            stamp = "unverified"
        print("%-26s %-12s %s" % (name, stamp, meta["description"]))


if __name__ == "__main__":
    main()
