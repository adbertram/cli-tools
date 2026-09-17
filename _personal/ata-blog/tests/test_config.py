"""Regression tests for delegated auth status handling."""

from __future__ import annotations

import json
import subprocess

from ata_blog_cli.config import (
    Config,
    _active_profile_auth_status,
    _active_profile_has_credentials,
)


def _completed_process(stdout_payload: dict) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["delegated-cli", "auth", "status"],
        returncode=0,
        stdout=json.dumps(stdout_payload),
        stderr="",
    )


def test_active_profile_auth_uses_shared_status_schema(monkeypatch):
    """The wrapper must read active-profile auth from the canonical status shape."""

    def fake_run(args, **kwargs):
        assert args == ["notion", "auth", "status"]
        return _completed_process(
            {
                "profiles": [
                    {
                        "name": "default",
                        "auth_type": "default",
                        "active": True,
                        "authenticated": True,
                        "credential_types": {
                            "custom": {
                                "credentials_saved": True,
                                "authenticated": True,
                                "api_test": "passed",
                            }
                        },
                    }
                ]
            }
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    ok, message = _active_profile_auth_status("notion")

    assert ok is True
    assert message == "passed"


def test_has_credentials_distinguishes_saved_from_authenticated(monkeypatch):
    """Saved delegated credentials must not be collapsed into auth failure."""

    payload = {
        "profiles": [
            {
                "name": "default",
                "auth_type": "default",
                "active": True,
                "authenticated": False,
                "credential_types": {
                    "custom": {
                        "credentials_saved": True,
                        "authenticated": False,
                        "api_test": "failed: timeout",
                    }
                },
            }
        ]
    }
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        return _completed_process(payload)

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert _active_profile_has_credentials("notion") is True
    assert Config().has_credentials() is True
    assert all(args == ["notion", "auth", "status"] for args in calls)


def test_connection_reports_only_the_notion_cli(monkeypatch):
    """Auth status depends on the notion CLI and nothing else."""

    def fake_run(args, **kwargs):
        assert args == ["notion", "auth", "status"]
        return _completed_process(
            {
                "profiles": [
                    {
                        "name": "default",
                        "auth_type": "default",
                        "active": True,
                        "authenticated": True,
                        "credential_types": {
                            "custom": {"credentials_saved": True, "authenticated": True}
                        },
                    }
                ]
            }
        )

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert Config().test_connection() == {
        "notion_auth": "passed",
        "api_test": "passed",
    }
