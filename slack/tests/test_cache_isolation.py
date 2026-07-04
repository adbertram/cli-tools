"""Per-profile cache isolation tests.

Regression coverage for the cross-profile cache bleed-through bug where
``Config`` overrode ``storage_dir`` to the shared tool dir, causing all
profiles to read and write the same ``cache/`` directory. Isolation must
come from ``BaseConfig.storage_dir`` resolving to the per-profile data dir
(``~/.local/share/cli-tools/slack/authentication_profiles/<profile>/``).
"""

import pytest

from cli_tools_shared.data_cache import cached

from slack_cli.config import Config, reset_config


@pytest.fixture
def isolated_profiles(tmp_path, monkeypatch):
    """Point profile storage at a temp XDG_DATA_HOME with two profiles."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setenv("CACHE_ENABLED", "true")
    monkeypatch.delenv("CACHE_TTL", raising=False)
    profiles_base = tmp_path / "cli-tools" / "slack" / "authentication_profiles"
    for name in ("profa", "profb"):
        profile_dir = profiles_base / name
        profile_dir.mkdir(parents=True)
        (profile_dir / ".env").write_text("ACTIVE=false\n")
    reset_config()
    yield
    reset_config()


class StubClient:
    """Minimal client shape required by @cached: a config and a method."""

    def __init__(self, config: Config, team: str):
        self.config = config
        self.team = team
        self.live_calls = 0

    @cached
    def get_team_info(self) -> dict:
        self.live_calls += 1
        return {"team": self.team}


def test_profiles_resolve_distinct_storage_dirs(isolated_profiles):
    config_a = Config(profile="profa")
    config_b = Config(profile="profb")

    assert config_a.storage_dir != config_b.storage_dir
    assert config_a.storage_dir == config_a.get_profile_data_dir()
    assert config_b.storage_dir == config_b.get_profile_data_dir()
    assert config_a.storage_dir.name == "profa"
    assert config_b.storage_dir.name == "profb"
    assert config_a.storage_dir.parent.name == "authentication_profiles"
    # The bug: storage_dir pointed at the shared source/tool dir.
    assert config_a.storage_dir != config_a.tool_dir
    assert config_b.storage_dir != config_b.tool_dir


def test_cached_result_not_served_across_profiles(isolated_profiles):
    config_a = Config(profile="profa")
    config_b = Config(profile="profb")

    writer_a = StubClient(config_a, "team-a")
    assert writer_a.get_team_info() == {"team": "team-a"}
    assert writer_a.live_calls == 1

    # Same profile, same args: served from profile A's cache (no live call).
    reader_a = StubClient(config_a, "never-returned")
    assert reader_a.get_team_info() == {"team": "team-a"}
    assert reader_a.live_calls == 0

    # Different profile, same method + args: profile A's cache must NOT bleed.
    reader_b = StubClient(config_b, "team-b")
    assert reader_b.get_team_info() == {"team": "team-b"}
    assert reader_b.live_calls == 1

    cache_files_a = list((config_a.storage_dir / "cache").glob("*.json"))
    cache_files_b = list((config_b.storage_dir / "cache").glob("*.json"))
    assert len(cache_files_a) == 1
    assert len(cache_files_b) == 1
    assert cache_files_a[0] != cache_files_b[0]
