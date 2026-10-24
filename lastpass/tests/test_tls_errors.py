"""TLS failures stay useful without revealing arbitrary upstream values."""
import subprocess
from lastpass_cli.errors import TLS_FAILURE, command_error
from lastpass_cli.client import ClientError, LastpassClient
import pytest


def test_tls_failure_is_named_without_printing_vault_values(monkeypatch):
    client = LastpassClient.__new__(LastpassClient)
    client.config = type("Config", (), {"cli_command": "lpass", "get_cli_executable": lambda self: "lpass"})()
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "secret-vault-value", TLS_FAILURE))
    with pytest.raises(ClientError, match="TLS certificate verification failed") as error:
        client._run_command(["ls"])
    assert "secret-vault-value" not in str(error.value)
    assert "never disable verification" in str(error.value)


@pytest.mark.parametrize("stderr", ["secret-vault-value", TLS_FAILURE + "\nsecret-vault-value", ""])
def test_unknown_or_mixed_stderr_is_not_disclosed(stderr):
    assert command_error("lpass", 1, stderr) == "lpass command failed (exit 1)"


def test_auth_status_redacts_unrecognized_upstream_failure(monkeypatch):
    from lastpass_cli.config import Config
    config = Config.__new__(Config)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "secret-stdout", "secret-stderr"))
    assert config.test_connection() == {"api_test": "failed: lpass command failed (exit 1)"}


def test_auth_status_preserves_safe_tls_diagnostic(monkeypatch):
    from lastpass_cli.config import Config
    config = Config.__new__(Config)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 1, "secret-stdout", TLS_FAILURE))
    assert "TLS certificate verification failed" in config.test_connection()["api_test"]
