#!/usr/bin/env python3
"""`readers._load()` must publish the WHOLE module map or none of it.

The cache used to be a module-level dict that `_load()` filled in place, guarded
by `if _MODULES:`. That test reads true as soon as the FIRST module lands, so a
second thread arriving mid-import received a partial map and `readers.read()`
raised

    Undetermined: no source module for 'shopsalvationarmy' -- add
    sources/shopsalvationarmy.py before reading it

for a module sitting right there on disk. A 6-thread pool hit it on 3 of 42 rows
on 2026-08-06; a cold-cache 8-thread probe hit it on 11 of 480 reads.

These tests run on a genuinely cold cache -- `_MODULES` cleared AND every reader
module dropped from `sys.modules`, so the imports cost real time and the window
is wide. A missing module must still raise; nothing here asserts a retry or a
default.
"""
from __future__ import annotations

import concurrent.futures as cf
import sys

import pytest

from legoscout_cli.sources import listing
from legoscout_cli.sources import readers

# Sorts late among the reader modules, so a partial map is very likely to be
# missing it. This is the namespace the live run actually failed on.
LATE_NAMESPACE = "shopsalvationarmy"

THREADS = 8
ROUNDS = 40


@pytest.fixture
def cold_cache():
    """Drop the published map and every imported reader module, then restore.

    Teardown puts back the ORIGINAL module objects rather than re-importing.
    A fresh import creates new module objects, so any other test module holding
    a reference from before this one ran would find its reader is no longer the
    same object as the one in the map -- a failure this test would have caused
    somewhere else entirely.
    """
    prefix = readers.__name__ + "."
    saved_sys = {n: m for n, m in sys.modules.items() if n.startswith(prefix)}
    saved_map = readers._MODULES

    def go():
        readers._MODULES = None
        for name in [n for n in sys.modules if n.startswith(prefix)]:
            del sys.modules[name]

    go()
    yield go
    go()
    sys.modules.update(saved_sys)
    readers._MODULES = saved_map


def _read_field(_):
    """One `readers.read` on a namespace whose module exists.

    Returns the Undetermined message when the map came back partial, else None.
    `auction_end_date` on Shop The Salvation Army is a real reader, and it is
    resolved off the module -- it is never called, so this makes no network
    request.
    """
    deal = {"listing_key": "%s|571043759" % LATE_NAMESPACE}
    try:
        module = readers.module_for(deal["listing_key"])
        if module is None:
            return "module_for returned None for %r" % LATE_NAMESPACE
        if getattr(module, "auction_end_date", None) is None:
            return "%s module has no auction_end_date reader" % LATE_NAMESPACE
    except listing.Undetermined as exc:
        return str(exc)
    return None


def test_concurrent_cold_reads_never_see_a_partial_module_map(cold_cache):
    """No `Undetermined` for a namespace whose module exists, over many rounds.

    ROUNDS x THREADS = 320 cold reads. The pre-fix code failed roughly 2% of
    them, so a single clean round proves nothing and this runs 40.
    """
    misses = []
    for _ in range(ROUNDS):
        cold_cache()
        with cf.ThreadPoolExecutor(max_workers=THREADS) as pool:
            misses.extend(m for m in pool.map(_read_field, range(THREADS))
                          if m is not None)
    assert misses == [], (
        "%d of %d concurrent cold reads saw a partial module map: %s"
        % (len(misses), ROUNDS * THREADS, sorted(set(misses))))


def test_every_thread_gets_the_same_complete_map(cold_cache):
    """One published map, identical for every caller, with every namespace."""
    cold_cache()
    with cf.ThreadPoolExecutor(max_workers=THREADS) as pool:
        maps = list(pool.map(lambda _: readers._load(), range(THREADS)))

    first = maps[0]
    assert all(m is first for m in maps), \
        "threads received %d distinct map objects" % len({id(m) for m in maps})
    assert LATE_NAMESPACE in first
    # Every module on disk, not a prefix of them.
    import pkgutil
    on_disk = {info.name for info in pkgutil.iter_modules(readers.__path__)}
    assert len(first) == len(on_disk), \
        "published %d namespaces for %d modules on disk" % (len(first), len(on_disk))


def test_a_genuinely_missing_module_still_raises(cold_cache):
    """Fail fast survives the fix: no retry, no fallback, no substituted value."""
    cold_cache()
    with pytest.raises(listing.Undetermined) as exc:
        readers.read({"listing_key": "notamarketplace|1"}, "auction_end_date")
    assert "no source module for 'notamarketplace'" in str(exc.value)
