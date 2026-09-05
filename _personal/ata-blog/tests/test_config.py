"""Regression tests for delegated auth status handling."""

from __future__ import annotations

import json
import subprocess

import pytest
import requests
import typer
from cli_tools_shared.config import reset_runtime_profile_resolution, set_runtime_profile_resolution

from ata_blog_cli.commands import wordpress_admin
from ata_blog_cli.commands.wordpress_admin import _run_wordpress
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


def _wordpress_admin_command(*args: str) -> list[str]:
    """Expected delegated admin command shape.

    The delegated wordpress Typer app defines ``--profile`` on the ``admin``
    command group, so profile options must be placed after ``admin`` and before
    the admin subcommands.
    """

    return ["wordpress", "admin", "--profile", "default", *args]


def _wordpress_org_token_status_command() -> list[str]:
    """Expected WordPress.com preflight command for the active profile."""

    return ["wordpress", "org", "--profile", "default", "token", "status"]


def test_active_profile_auth_uses_shared_status_schema(monkeypatch):
    """The wrapper must read active-profile auth from the canonical status shape."""

    def fake_run(args, **kwargs):
        assert args == ["wordpress", "auth", "status"]
        return _completed_process(
            {
                "profiles": [
                    {
                        "name": "default",
                        "auth_type": "default",
                        "active": True,
                        "authenticated": True,
                        "credential_types": {
                            "username_password": {
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

    ok, message = _active_profile_auth_status("wordpress")

    assert ok is True
    assert message == "passed"


def test_wrapper_has_credentials_distinguishes_saved_from_authenticated(monkeypatch):
    """Saved delegated credentials must not be collapsed into auth failure."""

    payloads = {
        "wordpress": {
            "profiles": [
                {
                    "name": "default",
                    "auth_type": "default",
                    "active": True,
                    "authenticated": False,
                    "credential_types": {
                        "username_password": {
                            "credentials_saved": True,
                            "authenticated": False,
                            "api_test": "failed: timeout",
                        }
                    },
                }
            ]
        },
        "notion": {
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
        },
    }

    def fake_run(args, **kwargs):
        return _completed_process(payloads[args[0]])

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert _active_profile_has_credentials("wordpress") is True
    assert Config().has_credentials() is True


def test_wordpress_admin_delegation_forwards_runtime_profile(monkeypatch):
    calls = []

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    tokens = set_runtime_profile_resolution(
        profile_name="default",
        profile_auth_type="default",
    )
    try:
        with pytest.raises(typer.Exit) as exc_info:
            _run_wordpress(["plugins", "list"])
    finally:
        reset_runtime_profile_resolution(tokens)

    assert exc_info.value.exit_code == 0
    assert calls == [
        (
            _wordpress_admin_command("plugins", "list"),
            {"text": True},
        )
    ]


def test_wordpress_admin_upgrade_runs_wp_admin_ajax_path(monkeypatch, capsys):
    calls = []

    def fake_upgrade(plugin):
        calls.append(plugin)
        return {
            "before": {
                "plugin": "codepress-admin-columns/codepress-admin-columns",
                "version": "7.0.16",
                "update_status": "available",
                "latest_version": "7.0.17",
            },
            "after": {
                "plugin": "codepress-admin-columns/codepress-admin-columns",
                "version": "7.0.17",
                "update_status": "current",
                "latest_version": "7.0.17",
            },
            "wp_admin_ajax": {"success": True},
        }

    monkeypatch.setattr(wordpress_admin, "_upgrade_plugin_and_verify", fake_upgrade)

    with pytest.raises(typer.Exit) as exc_info:
        wordpress_admin.plugins_upgrade("codepress-admin-columns/codepress-admin-columns")

    assert exc_info.value.exit_code == 0
    assert calls == ["codepress-admin-columns/codepress-admin-columns"]
    output = json.loads(capsys.readouterr().out)
    assert output["after"]["version"] == "7.0.17"


def test_wordpress_admin_upgrade_reports_wp_admin_ajax_failure(monkeypatch, capsys):
    def fake_upgrade(plugin):
        raise RuntimeError(f"Plugin {plugin} does not have an available update")

    monkeypatch.setattr(wordpress_admin, "_upgrade_plugin_and_verify", fake_upgrade)

    with pytest.raises(typer.Exit) as exc_info:
        wordpress_admin.plugins_upgrade("current/current")

    assert exc_info.value.exit_code == 1
    assert "does not have an available update" in capsys.readouterr().err


def test_wordpress_admin_delete_runs_wp_admin_ajax_path(monkeypatch, capsys):
    calls = []

    def fake_delete(plugin):
        calls.append(plugin)
        return {
            "before": {
                "plugin": "copy-delete-posts/copy-delete-posts",
                "version": "1.5.4",
                "status": "inactive",
            },
            "deleted": True,
            "wp_admin_ajax": {"success": True},
        }

    monkeypatch.setattr(wordpress_admin, "_delete_plugin_and_verify", fake_delete)

    with pytest.raises(typer.Exit) as exc_info:
        wordpress_admin.plugins_delete("copy-delete-posts/copy-delete-posts")

    assert exc_info.value.exit_code == 0
    assert calls == ["copy-delete-posts/copy-delete-posts"]
    output = json.loads(capsys.readouterr().out)
    assert output["deleted"] is True


def test_wordpress_admin_update_nonce_and_plugin_file_helpers():
    html = '<script>var _wpUpdatesSettings = {"ajax_nonce":"abc123def4"};</script>'

    assert wordpress_admin._extract_updates_nonce(html) == "abc123def4"
    assert (
        wordpress_admin._plugin_file_from_rest_path("acf-to-rest-api/class-acf-to-rest-api")
        == "acf-to-rest-api/class-acf-to-rest-api.php"
    )
    assert wordpress_admin._slug_from_plugin_path("codepress-admin-columns/codepress-admin-columns") == "codepress-admin-columns"


def test_wordpress_admin_upgrade_forces_update_check(monkeypatch):
    calls = []

    def fake_action(plugin_path, action, plugin_status, timeout=300, *, force_update_check=False):
        calls.append((plugin_path, action, plugin_status, timeout, force_update_check))
        return {"success": True}

    monkeypatch.setattr(wordpress_admin, "_run_plugin_wp_admin_ajax_action", fake_action)

    assert wordpress_admin._upgrade_plugin_via_wp_admin_ajax("redirection/redirection") == {"success": True}
    assert calls == [("redirection/redirection", "update-plugin", "upgrade", 300, True)]


def _response(status_code: int, url: str, text: str = "") -> requests.Response:
    response = requests.Response()
    response.status_code = status_code
    response.url = url
    response._content = text.encode()
    return response


def test_wordpress_admin_503_before_action_is_classified_without_post(monkeypatch):
    class FakeSession:
        post_calls = 0

        def get(self, url, **kwargs):
            return _response(503, url)

        def post(self, url, **kwargs):
            self.post_calls += 1
            raise AssertionError("plugin-action POST must not run after preflight 503")

    session = FakeSession()
    monkeypatch.setattr(wordpress_admin, "_wp_admin_session", lambda: session)

    with pytest.raises(wordpress_admin.WPAdminServiceUnavailable) as exc_info:
        wordpress_admin._run_plugin_wp_admin_ajax_action(
            "redirection/redirection",
            "update-plugin",
            "upgrade",
        )

    assert exc_info.value.mutation_sent is False
    assert "WP_ADMIN_503_PRE_MUTATION" in str(exc_info.value)
    assert "plugin-action POST was not sent" in str(exc_info.value)
    assert session.post_calls == 0


def test_wordpress_admin_503_after_action_is_ambiguous_and_not_retried(monkeypatch):
    class FakeSession:
        post_calls = 0

        def get(self, url, **kwargs):
            html = '<script>var _wpUpdatesSettings = {"ajax_nonce":"abc123def4"};</script>'
            return _response(200, url, html)

        def post(self, url, **kwargs):
            self.post_calls += 1
            return _response(503, url)

    session = FakeSession()
    monkeypatch.setattr(wordpress_admin, "_wp_admin_session", lambda: session)

    with pytest.raises(wordpress_admin.WPAdminServiceUnavailable) as exc_info:
        wordpress_admin._run_plugin_wp_admin_ajax_action(
            "worker/init",
            "update-plugin",
            "upgrade",
        )

    assert exc_info.value.mutation_sent is True
    assert "WP_ADMIN_503_MUTATION_OUTCOME_UNKNOWN" in str(exc_info.value)
    assert "Do not automatically retry or retry in the same run" in str(exc_info.value)
    assert session.post_calls == 1


def test_wordpress_admin_upgrade_handles_latest_ajax_after_successful_readback(monkeypatch):
    records = [
        {
            "plugin": "redirection/redirection",
            "version": "5.8.0",
            "update_status": "available",
            "latest_version": "5.8.1",
        },
        {
            "plugin": "redirection/redirection",
            "version": "5.8.1",
            "update_status": "current",
            "latest_version": "5.8.1",
        },
    ]

    def fake_get(plugin):
        return records.pop(0)

    def fake_upgrade(plugin_path):
        raise wordpress_admin.WPAdminAjaxError(
            "update-plugin",
            {"success": False, "data": {"errorMessage": "The plugin is at the latest version."}},
        )

    monkeypatch.setattr(wordpress_admin, "_get_plugin_for_mutation", fake_get)
    monkeypatch.setattr(wordpress_admin, "_upgrade_plugin_via_wp_admin_ajax", fake_upgrade)

    result = wordpress_admin._upgrade_plugin_and_verify("redirection/redirection")

    assert result["after"]["version"] == "5.8.1"
    assert "already latest" in result["note"]


def test_wordpress_admin_upgrade_reports_stale_update_state(monkeypatch):
    records = [
        {
            "plugin": "redirection/redirection",
            "version": "5.8.0",
            "update_status": "available",
            "latest_version": "5.8.1",
        },
        {
            "plugin": "redirection/redirection",
            "version": "5.8.0",
            "update_status": "available",
            "latest_version": "5.8.1",
        },
    ]

    def fake_get(plugin):
        return records.pop(0)

    def fake_upgrade(plugin_path):
        raise wordpress_admin.WPAdminAjaxError(
            "update-plugin",
            {"success": False, "data": {"errorMessage": "The plugin is at the latest version."}},
        )

    monkeypatch.setattr(wordpress_admin, "_get_plugin_for_mutation", fake_get)
    monkeypatch.setattr(wordpress_admin, "_upgrade_plugin_via_wp_admin_ajax", fake_upgrade)

    with pytest.raises(RuntimeError, match="WordPress update state contradiction"):
        wordpress_admin._upgrade_plugin_and_verify("redirection/redirection")


def test_wordpress_admin_health_report_marks_updates_absent_from_wp_admin_upgrade_screen(monkeypatch):
    report = {
        "plugins": {
            "updates_available_count": 2,
            "updates_available": [
                {"plugin": "jetpack/jetpack", "version": "15.9", "latest_version": "15.9.1", "update_status": "available"},
                {"plugin": "redirection/redirection", "version": "5.8.0", "latest_version": "5.8.1", "update_status": "available"},
            ],
            "items": [
                {"plugin": "jetpack/jetpack", "version": "15.9", "latest_version": "15.9.1", "update_status": "available"},
                {"plugin": "redirection/redirection", "version": "5.8.0", "latest_version": "5.8.1", "update_status": "available"},
            ],
        }
    }
    monkeypatch.setattr(wordpress_admin, "_wp_admin_upgrade_plugin_files", lambda: {"jetpack/jetpack.php"})

    result = wordpress_admin._annotate_plugin_update_contradictions(report)

    assert result["plugins"]["updates_available_count"] == 1
    assert [plugin["plugin"] for plugin in result["plugins"]["updates_available"]] == ["jetpack/jetpack"]
    assert result["plugins"]["stale_update_state_count"] == 1
    assert result["plugins"]["stale_update_state"][0]["plugin"] == "redirection/redirection"
    assert result["plugins"]["items"][1]["update_status"] == "stale_update_state"


def test_wordpress_admin_health_report_default_outputs_annotated_json(monkeypatch, capsys):
    calls = []

    def fake_run_json(args):
        calls.append(args)
        return {"plugins": {"updates_available": []}}

    def fake_annotate(report):
        report["annotated"] = True
        return report

    monkeypatch.setattr(wordpress_admin, "_run_wordpress_json", fake_run_json)
    monkeypatch.setattr(wordpress_admin, "_annotate_plugin_update_contradictions", fake_annotate)

    with pytest.raises(typer.Exit) as exc_info:
        wordpress_admin.health_report(table=False)

    assert exc_info.value.exit_code == 0
    assert calls == [["health-report"]]
    assert json.loads(capsys.readouterr().out)["annotated"] is True
