#!/usr/bin/env python3
"""Refuse a reader that contradicts its own source registry entry.

`listing.never_an_auction(why)` builds an `auction_end_date` reader that answers
the literal string `not-an-auction` for every lot, forever. That is the right
answer for Craigslist. It is a LIE on a source the registry marks
`auction_tier: "always"`, and it is a silent one: the reader returns a valid
schema value, the worker stores it, and the row lands in the ledger claiming a
live auction never opens or closes. Nothing raises, so nothing is noticed.

That shipped. `sources/readers/estatesalesorg.py` carried
`never_an_auction("EstateSales.org is a sale-listing directory, not a
transacting marketplace, so no lot on it opens or closes")` while its registry
entry said `auction_tier: "always"` and every live item page carried
`bidding: 1`, a `start_date_time`/`item_close_date_time` pair, and a `timezone`.
`estatesalesorg|125565727` was `status_text="active"`, closing
`2026-08-10 21:25:00 US/Central`, and `readers.read(deal, "auction_end_date")`
answered `not-an-auction`. A row with no close date can never be seen to expire,
so `invalidate.sweep` skips it and it stays "active" in the ledger permanently.

The check compares the two declarations that already exist -- the registry's
`auction_tier` and whether the module's reader is one of the `listing` sentinel
factories -- and reports the disagreement. It is deterministic, needs no
network, and runs from two gates:

  - `legoscout sources validate`, via `registry.check()`, which exits 1
  - `tests/test_reader_contract.py`, which fails the suite

A sentinel is recognised by CODE-OBJECT IDENTITY, not by name. Every closure a
factory returns shares the one code object compiled with the factory, so
`never_an_auction("a").__code__ is never_an_auction("b").__code__` is true and
an unrelated hand-written `auction_end_date` can never collide with it. Matching
on `__name__` would not work at all here: the closures are named for the FIELD
they read, so every sentinel is already called `auction_end_date`.
"""
from __future__ import annotations

from . import listing

# The sentinel factories in `listing`, by the code object every closure they
# build shares. Probed once, at import, from the factories themselves -- so a
# rename or a rewrite in `listing` cannot leave a stale literal behind here.
_SENTINELS = {
    listing.never_an_auction("probe").__code__: "listing.never_an_auction()",
    listing.never_quotes_shipping("probe").__code__:
        "listing.never_quotes_shipping()",
}


class ReaderContractError(AssertionError):
    """A reader and its registry entry state opposite facts about a source."""


def sentinel_name(reader):
    """Which `listing` factory built this reader, or None if a module wrote it.

    None for a missing reader too: omitting `auction_end_date` is a documented
    gap that `readers.where()` already reports. Only an ANSWER can contradict.
    """
    if reader is None:
        return None
    return _SENTINELS.get(getattr(reader, "__code__", None))


def problems(tiers):
    """Every reader/registry contradiction, as a list. Empty means sound.

    `tiers` maps namespace -> `auction_tier`, so a caller can check the registry
    that WOULD exist -- `registry.check()` passes a candidate document's tiers --
    without writing anything first. A namespace with no reader module is not a
    finding: sources are registered before their reader is written.
    """
    from . import readers

    modules = readers._load()
    found = []
    for namespace, tier in sorted(tiers.items()):
        module = modules.get(namespace)
        if module is None:
            continue
        built_by = sentinel_name(getattr(module, "auction_end_date", None))
        if tier == "always" and built_by == "listing.never_an_auction()":
            found.append(
                "%s: registry says auction_tier='always', but "
                "readers/%s.py answers auction_end_date with "
                "listing.never_an_auction(), which stamps the literal "
                "'not-an-auction' on every live bidding row. Read the close "
                "time off the listing, or correct auction_tier -- one of the "
                "two is wrong." % (namespace, namespace.replace("-", "_")))
        if tier == "never" and built_by is None and getattr(
                module, "auction_end_date", None) is not None:
            found.append(
                "%s: registry says auction_tier='never', but "
                "readers/%s.py writes a real auction_end_date() reader. A "
                "source that runs no auction has no close time to read -- one "
                "of the two is wrong." % (namespace, namespace.replace("-", "_")))
    return found


def assert_consistent(tiers):
    """Raise `ReaderContractError` naming every contradiction, or return None."""
    found = problems(tiers)
    if found:
        raise ReaderContractError(
            "%d reader(s) contradict the source registry:\n  %s"
            % (len(found), "\n  ".join(found)))
