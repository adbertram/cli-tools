"""Data-level caching decorator for CLI tool methods.

Caches method return values as JSON files keyed by method name + args.
On cache hit, the method body is skipped entirely (no browser launch needed).

Cache files stored at: {config.storage_dir}/cache/{method}_{hash}.json
Each file contains: {"timestamp": <epoch>, "data": <serialized return value>}

Controlled by:
- CACHE_ENABLED env var (default: true) — --no-cache flag sets this to false
- CACHE_TTL env var (default: 3600 seconds)

A cached value backed by a browser session is not served once that session is
gone. That gate keys off the DECORATED METHOD's own credential — declared with
``@cached(credential_type=...)``, or inferred when the tool declares exactly one
credential type — never off the mere presence of a browser session among a
tool's several credential types.

Pydantic models are serialized via model_dump() and deserialized via model_validate().
Plain dicts/lists are stored as-is.
"""

import hashlib
import json
import os
import time
import functools
from pathlib import Path
from typing import Any, Optional, get_type_hints

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


def cache_dir_for(instance: Any) -> Path:
    """Return the on-disk cache directory `@cached` uses for `instance`.

    Public accessor so a CLI can tell the user where completed work was
    persisted (e.g. a resumable multi-page crawl) without duplicating the
    storage layout.
    """
    return _get_cache_dir(instance)


BROWSER_SESSION_CREDENTIAL = "browser_session"


def _credential_value(credential_type: Any) -> Any:
    """Return a credential type's string value, accepting an enum or a string."""
    return getattr(credential_type, "value", credential_type)


def _method_needs_browser_session(instance: Any, credential_type: Any) -> bool:
    """Return whether the cached method's OWN credential is a browser session.

    ``credential_type`` is the credential the decorated method declared via
    ``@cached(credential_type=...)``. When a method declares nothing, the
    credential is inferred ONLY when the tool declares exactly one credential
    type — then that single type is unambiguously the method's own credential.

    A tool that declares several credential types (e.g. eBay's OAuth **and**
    browser session) says nothing about which one an undeclared cached method
    uses, so its browser session is not that method's credential. Treating it
    as one is the bug this function replaces: it gated OAuth- and API-key-backed
    methods on an unrelated browser login, silently disabling their cache on any
    machine with no saved session.
    """
    if credential_type is not None:
        return _credential_value(credential_type) == BROWSER_SESSION_CREDENTIAL

    config = getattr(instance, "config", None)
    declared = list(getattr(config, "CREDENTIAL_TYPES", []) or [])
    if len(declared) != 1:
        return False
    return _credential_value(declared[0]) == BROWSER_SESSION_CREDENTIAL


def _cache_allowed_for_instance(instance: Any, credential_type: Any = None) -> bool:
    """Return whether cached data may be served for this instance.

    A cached value backed by a browser session must not be served once that
    session is gone — the caller would otherwise read data it can no longer
    fetch. Every other credential is unaffected by the browser profile.
    """
    if not _method_needs_browser_session(instance, credential_type):
        return True
    config = getattr(instance, "config", None)
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


def _read_cache_entry(cache_file: Path) -> Optional[Any]:
    """Return the cached payload, or ``None`` when the entry is unreadable.

    An empty (0-byte), truncated, hand-corrupted, or otherwise unreadable file
    is reported as a miss. ``json.load`` raising on such a file must not escape
    the decorator: that would abort the command before the cache-miss body
    could refetch and rewrite the entry, leaving the profile permanently
    broken until ``cache clear``.
    """
    try:
        with open(cache_file, encoding="utf-8") as f:
            cached_data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(cached_data, dict) or "data" not in cached_data:
        return None
    return cached_data["data"]


def _write_cache_entry(cache_file: Path, result: Any) -> None:
    """Persist a cache entry atomically, best-effort.

    The entry is serialized to a same-directory temp file and moved into place
    with :func:`os.replace`, so a concurrent reader can never observe a
    partially written (0-byte or truncated) file. The temp name carries the pid
    and thread id so two writers of the same key never share a scratch file.

    A cache write failure — for example a read-only cache directory — never
    fails the command: the cache is an optimization and the caller already has
    the fresh result. A serialization failure still propagates, after the
    scratch file is removed.
    """
    serialized = _serialize(result)
    cache_entry = {
        "timestamp": time.time(),
        "data": serialized,
    }
    temp_file = cache_file.with_name(
        f"{cache_file.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(cache_entry, f, indent=2, default=_json_default)
        os.replace(temp_file, cache_file)
    except OSError:
        _discard_cache_temp(temp_file)
    except BaseException:
        _discard_cache_temp(temp_file)
        raise


def _discard_cache_temp(temp_file: Path) -> None:
    """Remove a cache scratch file, ignoring an already-gone or unremovable one."""
    try:
        temp_file.unlink(missing_ok=True)
    except OSError:
        pass


def invalidate(instance: Any, method_name: str, *args, **kwargs) -> None:
    """Delete cached entry/entries for a `@cached` method on `instance`.

    Call this from a mutating method (create/update/delete) that changes the
    data a `@cached` read method (e.g. `list_tasks`) returns, so the very next
    read reflects the mutation instead of serving a stale on-disk snapshot
    for up to CACHE_TTL seconds.

    - With no args/kwargs: deletes every cache file for `method_name`
      (covers methods whose cache key doesn't vary, e.g. `list_tasks()`,
      as well as clearing all variants of a parameterized method).
    - With args/kwargs: deletes only the single matching cache file.
    """
    cache_dir = _get_cache_dir(instance)
    if args or kwargs:
        key_hash = _make_cache_key(method_name, args, kwargs)
        cache_file = cache_dir / f"{method_name}_{key_hash}.json"
        cache_file.unlink(missing_ok=True)
    else:
        for cache_file in cache_dir.glob(f"{method_name}_*.json"):
            cache_file.unlink(missing_ok=True)


def cached(fn=None, *, credential_type=None):
    """Decorator that caches method return values as JSON files.

    Usage::

        class MyClient:
            def __init__(self):
                self.config = get_config()  # must have .storage_dir

            @cached
            def get_data(self, item_id: str) -> MyModel:
                ...  # expensive browser/API call

    ``credential_type`` declares which credential the decorated method itself
    uses. Pass it on a tool that declares several credential types, so a method
    reading through the browser session is still gated on that session while an
    API- or OAuth-backed method on the same client is not. On a tool with a
    single credential type the declaration is redundant — that one type is the
    method's credential.

    Cache is skipped when CACHE_ENABLED=false or method raises an exception.
    """
    if fn is None:
        return functools.partial(cached, credential_type=credential_type)

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

        # Check cache. A missing, empty, truncated, or otherwise unreadable
        # entry is a MISS, never an error: another process may be mid-write
        # (the write below is atomic, so this only covers older/foreign
        # writers), and a corrupt file must be re-fetched and rewritten rather
        # than wedging the command until `cache clear`.
        if cache_file.exists():
            try:
                age = time.time() - cache_file.stat().st_mtime
            except OSError:
                age = None
            if (
                age is not None
                and age < ttl
                and _cache_allowed_for_instance(self, credential_type)
            ):
                cached_data = _read_cache_entry(cache_file)
                if cached_data is not None:
                    # Resolve return type for deserialization
                    hints = get_type_hints(fn)
                    return_type = hints.get("return")
                    _cache_state.hit = True
                    return _deserialize(cached_data, return_type)

        # Cache miss — call the real method
        _cache_state.hit = False
        result = fn(self, *args, **kwargs)

        # Serialize and write atomically so a concurrent reader can never see a
        # partially written (0-byte or truncated) file.
        _write_cache_entry(cache_file, result)

        return result

    return wrapper
