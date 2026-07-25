from pathlib import Path

from brickfreedom_cli.config import get_config


def test_get_config_reads_root_config_and_default_profile(tmp_path, monkeypatch):
    data_home = tmp_path / "data-home"
    tool_data_dir = data_home / "cli-tools" / "brickfreedom"
    profile_dir = tool_data_dir / "authentication_profiles" / "default"
    profile_dir.mkdir(parents=True)
    config_env_file = tool_data_dir / ".env"
    config_env_file.write_text("BASE_URL=https://example.com\n")
    env_file = profile_dir / ".env"
    env_file.write_text("ACTIVE=true\n")

    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))

    config = get_config(profile="default")

    assert config.config_env_file_path == config_env_file
    assert config.env_file_path == env_file
    assert config._get("BASE_URL") == "https://example.com"
