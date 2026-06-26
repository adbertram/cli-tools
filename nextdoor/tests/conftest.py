"""Shared fixtures for nextdoor CLI tests.

Disable response caching for the whole test session so the ``@cached`` client
methods call through to the real implementation (the fake configs used in
tests do not provide a cache storage directory).
"""

import os

import pytest


@pytest.fixture(autouse=True)
def _disable_cache():
    previous = os.environ.get("CACHE_ENABLED")
    os.environ["CACHE_ENABLED"] = "false"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("CACHE_ENABLED", None)
        else:
            os.environ["CACHE_ENABLED"] = previous
