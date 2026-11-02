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


def test_repair_preserves_other_bytes_and_both_orders(tmp_path):
    from n8n_cli.sync_install_prefix import sync
    paths = [tmp_path / "a.py", tmp_path / "b.py"]
    assignments = ['N8N_BIN = "/usr/local/lib/node_modules/n8n/bin/n8n"  # old\n', 'N8N_INSTALL_PREFIX = "/usr/local"\n']
    for path, lines in zip(paths, (assignments, assignments[::-1])):
        path.write_text("# unrelated\n" + "".join(lines) + "def older_code():\n    return 42\n")
    result = sync(paths, server.N8N_INSTALL_PREFIX)
    assert len(result["backups"]) == 2
    for path in paths:
        source = path.read_text()
        assert source.startswith("# unrelated\n") and source.endswith("def older_code():\n    return 42\n")
        assert '# old' in source and '/usr/local' not in source
    assert not sync(paths, server.N8N_INSTALL_PREFIX)["changed"]


def test_repair_rejects_unexpected_source_and_symlinks(tmp_path):
    import pytest
    from n8n_cli.sync_install_prefix import sync
    target = tmp_path / "source.py"
    target.write_text('N8N_BIN = get_bin()\nN8N_INSTALL_PREFIX = "/usr/local"\n')
    with pytest.raises(ValueError):
        sync([target], server.N8N_INSTALL_PREFIX)
    alias = tmp_path / "alias.py"
    alias.symlink_to(target)
    with pytest.raises(ValueError):
        sync([alias], server.N8N_INSTALL_PREFIX)


def test_repair_rolls_back_on_failure(tmp_path, monkeypatch):
    import pytest
    from n8n_cli import sync_install_prefix as repair
    sync = repair.sync
    content = 'N8N_BIN = "/usr/local/lib/node_modules/n8n/bin/n8n"\nN8N_INSTALL_PREFIX = "/usr/local"\n'
    paths = [tmp_path / "a.py", tmp_path / "b.py"]
    for path in paths:
        path.write_text(content)
    write = repair.atomic_write
    def fail_second(path, data, mode):
        if path == paths[1] and data != content.encode():
            raise OSError("simulated failure")
        return write(path, data, mode)
    monkeypatch.setattr(repair, "atomic_write", fail_second)
    with pytest.raises(OSError):
        sync(paths, server.N8N_INSTALL_PREFIX)
    assert all(path.read_text() == content for path in paths)


def test_repair_rolls_back_failed_import_verification(tmp_path):
    import pytest
    from n8n_cli.sync_install_prefix import sync
    path = tmp_path / 'server.py'
    original = 'N8N_BIN = "/usr/local/lib/node_modules/n8n/bin/n8n"\nN8N_INSTALL_PREFIX = "/usr/local"\n'
    path.write_text(original)
    def reject():
        raise ValueError('wrong import')
    with pytest.raises(ValueError, match='wrong import'):
        sync([path], server.N8N_INSTALL_PREFIX, reject)
    assert path.read_text() == original


def test_main_refuses_unexpected_import_path(monkeypatch):
    import pytest
    import subprocess
    from n8n_cli import sync_install_prefix as repair
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: subprocess.CompletedProcess(a, 0, '["/unexpected/server.py", "x", "y"]', ''))
    with pytest.raises(ValueError, match='Unexpected installed'):
        repair.main(server.N8N_INSTALL_PREFIX)


def test_repair_attempts_every_rollback_and_reports_backups(tmp_path, monkeypatch):
    import pytest
    from n8n_cli import sync_install_prefix as repair
    original = b'N8N_BIN = "/usr/local/lib/node_modules/n8n/bin/n8n"\nN8N_INSTALL_PREFIX = "/usr/local"\n'
    paths = [tmp_path / "a.py", tmp_path / "b.py"]
    for path in paths:
        path.write_bytes(original)
    write = repair.atomic_write
    restored = []
    def failing_rollback(path, data, mode):
        if data == original:
            restored.append(path)
            if path == paths[0]:
                raise OSError("rollback error")
        return write(path, data, mode)
    monkeypatch.setattr(repair, "atomic_write", failing_rollback)
    def fail_verification():
        raise ValueError("verification error")
    with pytest.raises(RuntimeError, match="verification error.*rollback failures.*backups"):
        repair.sync(paths, server.N8N_INSTALL_PREFIX, fail_verification)
    assert restored == paths
    assert paths[1].read_bytes() == original


def test_failed_atomic_replacement_leaves_original_intact(tmp_path, monkeypatch):
    import pytest
    from n8n_cli import sync_install_prefix as repair
    path = tmp_path / "server.py"
    path.write_bytes(b"original")
    def fail(*args):
        raise OSError("replacement failed")
    monkeypatch.setattr(repair.os, "replace", fail)
    with pytest.raises(OSError, match="replacement failed"):
        repair.atomic_write(path, b"new", 0o644)
    assert path.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [path]
