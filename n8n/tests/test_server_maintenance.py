"""Server maintenance uses the deployed n8n installation."""
import subprocess

from typer.testing import CliRunner

from n8n_cli.commands import server


def test_version_and_upgrade_use_services_installation(monkeypatch):
    commands = []
    versions = iter(["1.0.0", "2.0.0"])

    def run(command):
        commands.append(command)
        return next(versions)

    def install(command, **kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(server, "run_on_server", run)
    monkeypatch.setattr(server, "run_on_server_raw", install)
    result = CliRunner().invoke(server.app, ["upgrade", "2.0.0", "--skip-restart"])

    assert result.exit_code == 0, result.output
    assert commands == [
        "/Users/adam/Services/n8n/lib/node_modules/n8n/bin/n8n --version",
        "sudo npm install -g --prefix /Users/adam/Services/n8n n8n@2.0.0",
        "/Users/adam/Services/n8n/lib/node_modules/n8n/bin/n8n --version",
    ]
