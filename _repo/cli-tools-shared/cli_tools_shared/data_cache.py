"""Data-level caching decorator for CLI tool methods.

Caches method return values as JSON files keyed by method name + args.
On cache hit, the method body is skipped entirely (no browser launch needed).

Cache files stored at: {config.storage_dir}/cache/{method}_{hash}.json
Each file contains: {"timestamp": <epoch>, "data": <serialized return value>}

Controlled by:
- CACHE_ENABLED env var (default: true) — --no-cache flag sets this to false
- CACHE_TTL env var (default: 3600 seconds)

Pydantic models are serialized via model_dump() and deserialized via model_validate().
Plain dicts/lists are stored as-is.
"""

import hashlib
import json
import time
import functools
from pathlib import Path
from typing import Any, get_type_hints

import threading

from .config import is_cache_enabled, get_cache_ttl


_cache_state = threading.local()


def get_cache_hit():
    """Return True/False/None for the last @cached call's hit status."""
    return getattr(_cache_state, "hit", None)


def reset_cache_hit():
    """Reset cache hit state (called after print_json consumes it)."""
    _cache_state.hit = None


def _make_cache_key(method_name: str, args: tuple, kwargs: dict) -> str:
    """Build a deterministic hash from method name and arguments."""
    # Skip 'self' — args[0] is self for bound methods, but we receive
    # args *without* self since the decorator intercepts after binding.
    key_parts = [method_name]
    for arg in args:
        key_parts.append(repr(arg))
    for k in sorted(kwargs.keys()):
        key_parts.append(f"{k}={repr(kwargs[k])}")
    raw = "|".join(key_parts)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _get_cache_dir(instance: Any) -> Path:
    """Discover storage_dir from the instance's config and return cache subdir."""
    config = getattr(instance, "config", None)
    if config is None:
        raise RuntimeError("@cached requires self.config with storage_dir")
    storage_dir = getattr(config, "storage_dir", None)
    if storage_dir is None:
        raise RuntimeError("@cached requires self.config.storage_dir")
    cache_dir = Path(storage_dir) / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _cache_allowed_for_instance(instance: Any) -> bool:
    """Return whether cached data may be served for this instance."""
    config = getattr(instance, "config", None)
    credential_types = getattr(config, "CREDENTIAL_TYPES", [])
    if not any(getattr(item, "value", None) == "browser_session" for item in credential_types):
        return True
    return bool(config.has_saved_session())


def _serialize(value: Any) -> Any:
    """Serialize a return value to JSON-safe form."""
    if hasattr(value, "model_dump"):
        return {"__pydantic__": type(value).__qualname__, "data": value.model_dump(mode="python")}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value


def _deserialize(raw: Any, return_type: Any) -> Any:
    """Deserialize cached JSON back to the expected return type."""
    origin = getattr(return_type, "__origin__", None)

    # Handle List[Model]
    if origin is list:
        item_type = return_type.__args__[0] if hasattr(return_type, "__args__") else None
        if isinstance(raw, list):
            return [_deserialize(item, item_type) for item in raw]
        return raw

    # Handle single Pydantic model
    if isinstance(raw, dict) and "__pydantic__" in raw:
        if return_type is not None and hasattr(return_type, "model_validate"):
            return return_type.model_validate(raw["data"])
        return raw["data"]

    # Plain dict/list/scalar — return as-is
    if return_type is not None and hasattr(return_type, "model_validate") and isinstance(raw, dict):
        return return_type.model_validate(raw)

    return raw


def _json_default(obj: Any) -> Any:
    """JSON serializer fallback for non-standard types."""
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    if hasattr(obj, "value"):  # enums
        return obj.value
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def cached(fn):
    """Decorator that caches method return values as JSON files.

    Usage::

        class MyClient:
            def __init__(self):
                self.config = get_config()  # must have .storage_dir

            @cached
            def get_data(self, item_id: str) -> MyModel:
                ...  # expensive browser/API call

    Cache is skipped when CACHE_ENABLED=false or method raises an exception.
    """

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):

        if not is_cache_enabled():
            _cache_state.hit = False
            return fn(self, *args, **kwargs)

        method_name = fn.__name__
        key_hash = _make_cache_key(method_name, args, kwargs)
        cache_dir = _get_cache_dir(self)
        cache_file = cache_dir / f"{method_name}_{key_hash}.json"

        ttl = get_cache_ttl()

        # Check cache
        if cache_file.exists():
            age = time.time() - cache_file.stat().st_mtime
            if age < ttl and _cache_allowed_for_instance(self):
                with open(cache_file) as f:
                    cached_data = json.load(f)
                # Resolve return type for deserialization
                hints = get_type_hints(fn)
                return_type = hints.get("return")
                _cache_state.hit = True
                return _deserialize(cached_data["data"], return_type)

        # Cache miss — call the real method
        _cache_state.hit = False
        result = fn(self, *args, **kwargs)

        # Serialize and save
        serialized = _serialize(result)
        cache_entry = {
            "timestamp": time.time(),
            "data": serialized,
        }
        with open(cache_file, "w") as f:
            json.dump(cache_entry, f, indent=2, default=_json_default)

        return result

    return wrapper
