from pathlib import Path

from coursecraft_cli.config import Config


def test_config_exposes_storage_dir_for_cache_commands():
    config = Config()

    assert isinstance(config.storage_dir, Path)
    assert config.storage_dir == config.get_profile_data_dir()
