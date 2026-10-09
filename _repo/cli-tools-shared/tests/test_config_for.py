"""config_for keys a CLI's config cache on the resolved profile.

The command registry builds the config with the resolved profile name for its
credential check, then the API client calls get_config() with no profile. Both
must land on one instance so an invocation builds one config.
"""

from cli_tools_shared.config import (
    config_for,
    reset_runtime_profile_resolution,
    set_runtime_profile_resolution,
)


class _CountingConfig:
    builds = []

    def __init__(self, profile=None):
        self.profile = profile
        _CountingConfig.builds.append(profile)


def _fresh():
    _CountingConfig.builds = []
    return {}


def test_registry_then_client_share_one_instance_under_the_runtime_profile():
    cache = _fresh()
    tokens = set_runtime_profile_resolution(profile_name="work", profile_auth_type=None)
    try:
        registry = config_for(_CountingConfig, "work", cache)
        client = config_for(_CountingConfig, None, cache)
    finally:
        reset_runtime_profile_resolution(tokens)

    assert client is registry
    assert _CountingConfig.builds == ["work"]
    assert list(cache) == ["work"]


def test_client_first_then_registry_also_share_one_instance():
    cache = _fresh()
    tokens = set_runtime_profile_resolution(profile_name="default", profile_auth_type=None)
    try:
        client = config_for(_CountingConfig, None, cache)
        registry = config_for(_CountingConfig, "default", cache)
    finally:
        reset_runtime_profile_resolution(tokens)

    assert registry is client
    assert _CountingConfig.builds == [None]


def test_no_runtime_profile_uses_default_key():
    cache = _fresh()

    first = config_for(_CountingConfig, None, cache)
    second = config_for(_CountingConfig, None, cache)

    assert first is second
    assert list(cache) == ["_default"]


def test_explicit_profiles_get_separate_instances():
    cache = _fresh()

    a = config_for(_CountingConfig, "a", cache)
    b = config_for(_CountingConfig, "b", cache)

    assert a is not b
    assert (a.profile, b.profile) == ("a", "b")
    assert config_for(_CountingConfig, "a", cache) is a
