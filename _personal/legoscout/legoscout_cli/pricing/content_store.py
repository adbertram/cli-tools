"""One atomic, content-addressed, sharded file write -- shared by every store
that saves bytes keyed by a content hash.

`minifig_detector.write_crop` and `deal_images.write_image` both save encoded
image bytes under `<root>/<digest[:2]>/<stem><suffix>`, via a tempfile created
in the destination's own directory and promoted with `os.replace` so a crash
mid-write can never leave a half-written file at the final path. That
mechanic was implemented twice, byte-for-byte identical except for what wrote
into the tempfile; this is that one implementation.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Callable


class ContentWriteError(OSError):
    """A content-addressed write could not be atomically completed."""


def write_sharded(
    root: str,
    digest_hex: str,
    stem: str,
    suffix: str,
    writer: Callable[[Path], None],
) -> str:
    """Atomically create `<root>/<digest_hex[:2]>/<stem><suffix>`.

    `writer(temp_path)` must create the file at `temp_path`; whatever it
    raises propagates unchanged after the temp file is removed. Always
    writes, even when the destination already exists -- a caller that wants
    cache-hit semantics decides that before calling this. Returns the
    destination path relative to `root`, POSIX-separated.
    """
    relative = Path(digest_hex[:2]) / f"{stem}{suffix}"
    destination = Path(root) / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix=f".{stem}-", suffix=".tmp", dir=destination.parent)
    os.close(handle)
    temp = Path(temp_name)
    try:
        writer(temp)
        os.replace(temp, destination)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    return relative.as_posix()
