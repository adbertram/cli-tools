from pathlib import Path

from facebook_cli import config as facebook_config
from facebook_cli import images


def test_facebook_cache_dir_is_profile_cache_dir(tmp_path, monkeypatch):
    data_home = tmp_path / "share"
    tool_dir = tmp_path / "facebook"
    tool_dir.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.setattr(facebook_config, "resolve_tool_dir", lambda _dist: tool_dir)

    config = facebook_config.Config()

    assert config.storage_dir == config.get_profile_data_dir()
    assert config.cache_dir == config.get_profile_data_dir() / "cache"


def test_marketplace_images_use_cache_dir(tmp_path, monkeypatch):
    class _Config:
        cache_dir = tmp_path / "profile" / "cache"

    monkeypatch.setattr(images, "get_config", lambda: _Config())

    assert images._item_dir("123456") == Path(_Config.cache_dir) / "123456"
