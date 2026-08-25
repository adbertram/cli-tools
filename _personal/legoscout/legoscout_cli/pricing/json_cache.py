#!/usr/bin/env python3
"""The one way this project reads and writes a JSON cache file.

Two bugs lived in two byte-identical copies of a `load()` helper, and both
destroyed data with no error.

**A corrupt cache read as an empty one.** `except ValueError: return default`
turned a half-written file into `{}`. The caller then added its one new entry
and wrote the whole dict back, so a single interrupted write replaced 59 paid
Shippo quotes with 1. Silently. There is no recovery -- both cache files are
gitignored. So: a file that EXISTS and does not parse raises. Only an absent
file is empty, because a cache nobody has written has no entries.

**Concurrent writers lost each other's work.** `quote()` read the whole file,
made a paid API call, then wrote the whole file back. Two callers doing that at
once keep only the second one's entry. An atomic rename does not fix this -- it
makes each write internally consistent, not serialised. Measured: 21 concurrent
writers, atomic rename applied, 1 of 21 entries survived. So writes go through
`update()`, which holds an exclusive lock across re-read, merge, and write.

The lock is held for microseconds and NEVER across the API call. Read first,
call the API unlocked, then `update()` with the result.

The lock lives in a sidecar `<path>.lock`, not in the cache file itself: the
write ends in `os.replace`, so a lock taken on the data file would be held on a
replaced inode and would guard nothing.

Usage:

    from . import json_cache

    cache = json_cache.read(CACHE)
    if key in cache:
        return cache[key]
    value = expensive_api_call()
    json_cache.update(CACHE, {key: value})
    return value
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from typing import Any

__all__ = ["CorruptCache", "read", "update", "lock_path"]


class CorruptCache(ValueError):
    """A cache file exists but does not parse.

    Deliberately loud. The old behaviour -- treating this as an empty cache --
    is what let one torn write wipe the file on the next save.
    """


def lock_path(path: str) -> str:
    return path + ".lock"


def read(path: str) -> dict[str, Any]:
    """Return the cache. Absent means empty. Corrupt raises."""
    if not os.path.exists(path):
        return {}
    with open(path) as fh:
        text = fh.read()
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise CorruptCache(
            f"Cache file does not parse: {path} ({exc}). "
            "It was probably left half-written by an interrupted process. "
            "Inspect it, then delete it to rebuild from scratch. "
            "It is NOT treated as empty: doing that is what silently "
            "discarded every entry it still held."
        ) from exc
    if not isinstance(data, dict):
        raise CorruptCache(
            f"Cache file is not a JSON object: {path} holds {type(data).__name__}."
        )
    return data


def update(path: str, entries: dict[str, Any]) -> dict[str, Any]:
    """Merge `entries` into the cache under an exclusive lock.

    Re-reads inside the lock, so an entry written by another process while this
    one was calling an API is preserved rather than overwritten. Returns the
    merged cache.
    """
    if not isinstance(entries, dict):
        raise TypeError(f"entries must be a dict, got {type(entries).__name__}")

    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)

    with open(lock_path(path), "a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            cache = read(path)
            cache.update(entries)
            fd, tmp = tempfile.mkstemp(dir=directory, prefix=".cache-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as fh:
                    json.dump(cache, fh, indent=1)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp, path)
            except BaseException:
                # A failed write must not leave the temp file behind, and must
                # not touch the real cache: os.replace is the only writer.
                if os.path.exists(tmp):
                    os.unlink(tmp)
                raise
            return cache
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
