import json
import sys
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from ata_blog_cli.main import app


@pytest.fixture
def runner():
    return CliRunner()


def _result(returncode=0):
    result = MagicMock()
    result.returncode = returncode
    return result


def _passthrough_result(payload=None, returncode=0, stderr=""):
    def _run(*_args, **_kwargs):
        if payload is not None:
            sys.stdout.write(json.dumps(payload))
        if stderr:
            sys.stderr.write(stderr)
        return _result(returncode=returncode)

    return _run


def test_wordpress_admin_plugins_list_forwards_to_wordpress_admin(runner):
    plugins = [
        {"name": "akismet/akismet", "status": "active", "version": "5.3"},
        {"name": "wordfence/wordfence", "status": "inactive", "version": "7.11"},
    ]

    with patch(
        "ata_blog_cli.commands.wordpress_admin.subprocess.run",
        side_effect=_passthrough_result(payload=plugins),
    ) as mock_run:
        result = runner.invoke(
            app,
            [
                "wordpress-admin",
                "plugins",
                "list",
                "--status",
                "active",
                "--properties",
                "name,status,version",
            ],
        )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == plugins
    mock_run.assert_called_once_with(
        [
            "wordpress",
            "admin",
            "plugins",
            "list",
            "--status",
            "active",
            "--properties",
            "name,status,version",
        ],
        text=True,
    )


def test_wordpress_admin_plugins_get_forwards_to_wordpress_admin(runner):
    plugin = {"name": "wordfence/wordfence", "status": "active", "version": "7.11"}

    with patch(
        "ata_blog_cli.commands.wordpress_admin.subprocess.run",
        side_effect=_passthrough_result(payload=plugin),
    ) as mock_run:
        result = runner.invoke(
            app,
            ["wordpress-admin", "plugins", "get", "wordfence/wordfence", "--properties", "name,status,version"],
        )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == plugin
    mock_run.assert_called_once_with(
        [
            "wordpress",
            "admin",
            "plugins",
            "get",
            "wordfence/wordfence",
            "--properties",
            "name,status,version",
        ],
        text=True,
    )


def test_wordpress_admin_plugins_upgrade_forwards_to_wordpress_admin(runner):
    upgrade = {"name": "wordfence/wordfence", "upgraded": True}

    with patch(
        "ata_blog_cli.commands.wordpress_admin.subprocess.run",
        side_effect=_passthrough_result(payload=upgrade),
    ) as mock_run:
        result = runner.invoke(app, ["wordpress-admin", "plugins", "upgrade", "wordfence/wordfence"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == upgrade
    mock_run.assert_called_once_with(
        ["wordpress", "admin", "plugins", "upgrade", "wordfence/wordfence"],
        text=True,
    )


def test_wordpress_admin_plugin_command_failure_exits_nonzero(runner):
    failure = _passthrough_result(returncode=1, stderr="plugin not found")

    with patch("ata_blog_cli.commands.wordpress_admin.subprocess.run", side_effect=failure):
        result = runner.invoke(app, ["wordpress-admin", "plugins", "get", "missing/plugin"])

    assert result.exit_code != 0
    assert "plugin not found" in result.stderr
