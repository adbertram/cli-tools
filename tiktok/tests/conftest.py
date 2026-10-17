"""Run every test against a temp data root with signed-in profiles, never the host's real ones."""
import pytest

from tiktok_cli.config import Config, reset_config

PROFILES = ("default", "clipper", "clipping")


@pytest.fixture(autouse=True)
def hermetic_data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "host-data"))
    reset_config()
    paths = Config(profile="default")
    for name in PROFILES:
        env_path = paths.profile_path_for(name)
        env_path.parent.mkdir(parents=True, exist_ok=True)
        env_path.write_text(f"AUTH_TYPE=browser_session\nACTIVE={'true' if name == 'default' else 'false'}\n")
    for name in PROFILES:
        cookies = Config(profile=name).get_persistent_profile_dir() / "Default" / "Cookies"
        cookies.parent.mkdir(parents=True, exist_ok=True)
        cookies.touch()
    yield
    reset_config()
