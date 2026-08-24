#!/usr/bin/env python3
"""One module per marketplace, one function per deal-record field it can answer.

    sources.read(deal, "available_fulfillment") -> (("local_pickup",), evidence)
    sources.read(deal, "item_location")         -> ("Hillsboro, OR 97123", evidence)
    sources.read(deal, "auction_end_date")      -> ("2026-08-07T18:20:00", evidence)
    sources.read(deal, "shipping_estimate")     -> (a quote object, evidence)

**The function name IS the ledger column name.** A source that cannot answer a
field simply omits the function, and states in `NEEDS_PAGE_READ[field]` where a
human or an agent must look instead. There is no separate declaration to keep in
step with the code.

This package replaced the registry's `signals` block and its 571-line
interpreter. The rule it kept: every reader RAISES rather than returning a
default. `listing.Undetermined` means "this listing did not answer"; it never
means "assume the usual".
"""
from __future__ import annotations

import importlib
import pkgutil
import threading

from .. import listing

# The six deal-record columns a source can be asked for. A function named for
# any of these IS the reader for that column.
FIELDS = ("available_fulfillment", "item_location", "auction_end_date",
          "shipping_estimate", "seller_id", "seller_name")

# `None` until the WHOLE map exists. The cache used to be a module-level dict
# that `_load()` filled in place while `if _MODULES:` already read as loaded, so
# a second thread arriving mid-import got a partial map and `read()` raised
# `no source module for 'shopsalvationarmy'` for a module that is right there --
# 3 of 42 rows in a 6-thread run on 2026-08-06. The dict is now built in a local
# and PUBLISHED in one assignment, under a lock so two threads cannot both
# build and half-publish. A genuinely missing module still raises; nothing here
# retries, defaults, or swallows an import error.
_MODULES: dict | None = None
_LOAD_LOCK = threading.Lock()


def _load():
    global _MODULES
    modules = _MODULES
    if modules is not None:
        return modules
    with _LOAD_LOCK:
        # A thread that waited on the lock while the winner built the map reads
        # the finished map here rather than importing all 25 modules again.
        if _MODULES is not None:
            return _MODULES
        built = {}
        for info in pkgutil.iter_modules(__path__):
            module = importlib.import_module("%s.%s" % (__name__, info.name))
            built[module.NAMESPACE] = module
        _MODULES = built  # the one atomic publish
        return _MODULES


def module_for(listing_key):
    """The module that reads this source, or None.

    Takes either a bare namespace (`"k-bid"`) or a full listing_key
    (`"k-bid|65418-227A"`), because both callers exist.
    """
    return _load().get(str(listing_key).split("|")[0])


def where(namespace, field):
    """Where a human must look for a field this source does not read itself.

    An undocumented field reports the GAP. It never borrows the module
    docstring: that substituted a sentence about a different field and read as
    an answer, so an agent hunted for a close time inside a street address.
    """
    module = module_for(namespace)
    if module is None:
        return "no source module exists for %r" % namespace
    stated = getattr(module, "NEEDS_PAGE_READ", {}).get(field)
    if stated:
        return stated
    return ("NOT DOCUMENTED -- sources/readers/%s.py writes no %s() reader and "
            "no NEEDS_PAGE_READ[%r] entry, so this source states nowhere to "
            "look. Treat this as a gap to fill, not as an answer."
            % (namespace.replace("-", "_"), field, field))


def price_bases(namespace):
    """The `price_basis` values this source can legitimately store, or None.

    None means the module declares no restriction, which is the default: a
    marketplace running both bidding and a Buy It Now genuinely stores more than
    one basis, and StockX's 170 `buy_now` rows are correct on a bid/ask exchange.
    Only a module that states outright that ONE branch can ever match declares
    `PRICE_BASES`, and only then does `validate.check` enforce it.
    """
    module = module_for(namespace)
    if module is None:
        return None
    declared = getattr(module, "PRICE_BASES", None)
    return tuple(declared) if declared else None


def read(deal, field):
    """(value, evidence) for one field on one listing. Raises, never defaults."""
    if field not in FIELDS:
        raise ValueError("%r is not a deal-record field a source answers" % field)
    key = deal["listing_key"]
    namespace = str(key).split("|")[0]
    module = module_for(namespace)
    if module is None:
        raise listing.Undetermined(
            "no source module for %r -- add sources/%s.py before reading it"
            % (namespace, namespace.replace("-", "_")))
    reader = getattr(module, field, None)
    if reader is None:
        raise listing.Undetermined(
            "%s reads no machine-readable %s off a listing -- the answer is: %s"
            % (namespace, field, where(namespace, field)))
    return reader(deal)


def answers(field=None):
    """Which sources answer which fields -- the run plan for a sweep."""
    out = {}
    for namespace, module in sorted(_load().items()):
        readable = sorted(f for f in FIELDS if getattr(module, f, None) is not None)
        out[namespace] = readable if field is None else (field in readable)
    return out
