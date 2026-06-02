from pathlib import Path

from brickfreedom_cli.config import get_config


def test_get_config_reads_migrated_default_profile(tmp_path, monkeypatch):
    data_home = tmp_path / "data-home"
    profile_dir = data_home / "cli-tools" / "brickfreedom" / "authentication_profiles" / "default"
    profile_dir.mkdir(parents=True)
    env_file = profile_dir / ".env"
    env_file.write_text("ACTIVE=true\nBASE_URL=https://example.com\n")

    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))

    config = get_config(profile="default")

    assert config.env_file_path == env_file
    assert config._get("BASE_URL") == "https://example.com"
