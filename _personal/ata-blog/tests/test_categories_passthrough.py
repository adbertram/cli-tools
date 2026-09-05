"""Contract tests for ATA Blog category passthrough commands."""

import subprocess

from typer.testing import CliRunner

from ata_blog_cli.commands import categories


def test_categories_create_translates_positional_name_to_wordpress_option(monkeypatch):
    """The documented positional name must become wordpress's required --name option."""
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(categories.subprocess, "run", fake_run)

    result = CliRunner().invoke(
        categories.app,
        ["create", "Business Process Automation"],
    )

    assert result.exit_code == 0, result.output
    assert calls == [
        [
            "wordpress",
            "categories",
            "create",
            "--name",
            "Business Process Automation",
        ]
    ]
