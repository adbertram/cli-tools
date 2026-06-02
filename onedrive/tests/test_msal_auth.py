"""Regression tests for OneDrive authentication helpers."""

import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from onedrive_cli import msal_auth


class _FakeConfig:
    def __init__(self, profile_dir: Path):
        self._profile_dir = profile_dir

    def get_profile_data_dir(self) -> Path:
        self._profile_dir.mkdir(parents=True, exist_ok=True)
        return self._profile_dir


def test_get_cache_path_uses_profile_data_dir(tmp_path):
    config = _FakeConfig(tmp_path / "authentication_profiles" / "work")

    cache_path = msal_auth._get_cache_path(config)

    assert cache_path == config.get_profile_data_dir() / "token_cache.json"


def test_az_cli_status_rejects_service_principal(monkeypatch):
    monkeypatch.setattr(msal_auth, "_get_az_cmd", lambda: "az")

    def fake_run(cmd, capture_output, text):
        return type(
            "Result",
            (),
            {
                "returncode": 0,
                "stdout": json.dumps(
                    {
                        "tenantId": "tenant-id",
                        "user": {"name": "app-id", "type": "servicePrincipal"},
                    }
                ),
            },
        )()

    def fail_verify(_token):
        raise AssertionError("service principal sessions must be rejected before /me probe")

    monkeypatch.setattr(msal_auth.subprocess, "run", fake_run)
    monkeypatch.setattr(msal_auth, "_verify_drive_access", fail_verify)

    status = msal_auth._get_az_cli_status()

    assert status["authenticated"] is False
    assert "service principal" in status["error"]


def test_test_handler_surfaces_az_cli_status_failure(monkeypatch):
    config = type("Config", (), {"auth_method": "az_cli"})()

    monkeypatch.setattr(
        msal_auth,
        "_get_az_cli_status",
        lambda: {"authenticated": False, "error": "service principal session"},
    )

    result = msal_auth.test_handler(config)

    assert result["api_test"] == "failed: service principal session"
