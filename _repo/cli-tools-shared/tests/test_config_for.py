"""config_for keys a CLI's config cache on the resolved profile.

The command registry builds the config with the resolved profile name for its
credential check, then the API client calls get_config() with no profile. Both
must land on one instance so an invocation builds one config.
"""

from cli_tools_shared.config import (
    config_class_of,
    config_for,
    config_getter,
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


def test_one_invocation_builds_one_config_across_registry_client_and_command_calls():
    # An invocation asks for its config several times: the registry's
    # credential check with the resolved profile, then the API client and any
    # command code with no profile. All of them must share one build.
    _fresh()
    get_config = config_getter(_CountingConfig)
    tokens = set_runtime_profile_resolution(profile_name="work", profile_auth_type=None)
    try:
        configs = [get_config("work"), get_config(), get_config(None), get_config("work")]
    finally:
        reset_runtime_profile_resolution(tokens)

    assert all(config is configs[0] for config in configs)
    assert _CountingConfig.builds == ["work"]


def test_config_getter_exposes_its_class_and_clears_its_cache():
    _fresh()
    get_config = config_getter(_CountingConfig)

    first = get_config()
    assert get_config.config_cls is _CountingConfig
    assert get_config() is first

    get_config.cache_clear()

    assert get_config() is not first
    assert _CountingConfig.builds == [None, None]


def test_config_getters_for_different_classes_do_not_share_a_cache():
    class OtherConfig(_CountingConfig):
        pass

    a = config_getter(_CountingConfig)
    b = config_getter(OtherConfig)

    assert isinstance(b(), OtherConfig)
    assert type(a()) is _CountingConfig


def test_config_class_of_reads_config_getter_class():
    assert config_class_of(config_getter(_CountingConfig)) is _CountingConfig


def test_config_class_of_finds_the_class_behind_a_hand_written_get_config():
    # Legacy shape: `_configs = {}` plus a wrapper that calls config_for.
    class Config(_CountingConfig):
        CREDENTIAL_TYPES = []

    def annotated(profile=None) -> Config:
        return config_for(Config, profile, {})

    def unannotated(profile=None):
        return config_for(Config, profile, {})

    assert config_class_of(annotated) is Config
    assert config_class_of(unannotated) is Config


def test_config_class_of_returns_none_when_no_class_is_discoverable():
    assert config_class_of(lambda profile=None: None) is None
