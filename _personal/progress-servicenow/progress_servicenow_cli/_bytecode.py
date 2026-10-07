"""Load restored Progress ServiceNow modules from their preserved bytecode."""

from __future__ import annotations

import importlib.util
import marshal
import sys
from pathlib import Path

_HEADER_BYTES = 16


def load_module_bytecode(module_name: str, namespace: dict) -> None:
    """Execute the preserved bytecode for a restored module."""
    source_path = Path(namespace["__file__"]).resolve()
    cache_dir = source_path.parent / "_bytecode_cache"
    cache_name = f"{source_path.stem}.{sys.implementation.cache_tag}.pyc"
    bytecode_path = cache_dir / cache_name

    if not bytecode_path.exists():
        raise ImportError(f"Missing restored bytecode for {module_name}: {bytecode_path}")

    data = bytecode_path.read_bytes()
    if data[:4] != importlib.util.MAGIC_NUMBER:
        raise ImportError(f"Incompatible bytecode for {module_name}: {bytecode_path}")

    code = marshal.loads(data[_HEADER_BYTES:])
    exec(code, namespace)
