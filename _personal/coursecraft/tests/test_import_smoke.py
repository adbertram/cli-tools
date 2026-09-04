"""Import smoke tests guarding against broken / stale-bytecode CLI imports.

Background
----------
This CLI is installed editable from a Dropbox-synced source tree. CPython's
default ``.pyc`` cache validates bytecode against the source file's mtime + size.
Dropbox sync can produce an mtime/size collision between two source revisions,
causing CPython to load STALE bytecode that references a prior module surface
(e.g. an old ``templates`` import after the file was renamed to
``slide_templates``). The CLI then dies with ``ImportError: cannot import
name ...`` intermittently and across machines.

``coursecraft_cli._bootstrap.harden_against_stale_bytecode`` (invoked by the
package ``__init__`` on every import path) removes that failure class by disabling
bytecode writes and purging the package ``__pycache__`` before the command
submodules import. These tests are the durable guard:

* ``test_*_imports_cleanly`` catches any genuinely broken import name in
  ``main`` / ``commands`` source.
* ``test_hardening_purges_poisonous_stale_bytecode`` proves the hardening
  recovers even when a poisonous stale ``.pyc`` is planted with a colliding
  mtime.
"""

import importlib
import errno
import os
import py_compile
import pytest
import shutil
import subprocess
import sys
from typer.testing import CliRunner


def test_main_imports_cleanly():
    """``coursecraft_cli.main`` (which imports every command module) loads."""
    module = importlib.import_module("coursecraft_cli.main")
    assert hasattr(module, "app")


def test_commands_package_imports_cleanly():
    """The intentionally empty command package imports cleanly."""
    importlib.import_module("coursecraft_cli.commands")


def test_cli_help_runs_in_subprocess():
    """A real subprocess invocation exercises the hardening path end to end."""
    result = subprocess.run(
        [sys.executable, "-c", "from coursecraft_cli.main import app; app()", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_voice_recordings_group_without_subcommand_renders_help():
    app = importlib.import_module("coursecraft_cli.main").app

    result = CliRunner().invoke(app, ["voice-recordings"])

    assert result.exit_code == 0, result.output
    assert "Generate demo voice recordings" in result.output
    assert "preview" in result.output
    assert "generate" in result.output


def test_hardening_purges_poisonous_stale_bytecode(tmp_path):
    """Plant a stale ``.pyc`` that references a nonexistent module, then prove a
    fresh subprocess import of the CLI succeeds because the package init purges
    the cache before the command modules load."""
    package_root = os.path.dirname(importlib.import_module("coursecraft_cli").__file__)
    commands_init = os.path.join(package_root, "commands", "__init__.py")

    good_source = open(commands_init, encoding="utf-8").read()
    # Reference a module name that does not exist -> stale bytecode is poisonous.
    broken_source = good_source + "\nfrom . import definitely_not_a_module\n"

    original_stat = os.stat(commands_init)
    try:
        # Compile broken source to the cache, then restore good source while
        # forcing the original mtime so the .pyc looks "fresh" to CPython.
        with open(commands_init, "w", encoding="utf-8") as handle:
            handle.write(broken_source)
        os.utime(commands_init, (original_stat.st_atime, original_stat.st_mtime))
        py_compile.compile(
            commands_init,
            doraise=True,
            invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP,
        )
    finally:
        with open(commands_init, "w", encoding="utf-8") as handle:
            handle.write(good_source)
        os.utime(commands_init, (original_stat.st_atime, original_stat.st_mtime))

    # Fresh interpreter: triggers the package-init hardening, which must purge
    # the poisonous .pyc before commands import.
    result = subprocess.run(
        [sys.executable, "-c", "import coursecraft_cli.main; print('ok')"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        "stale-bytecode hardening failed to recover:\n"
        f"stdout={result.stdout!r}\nstderr={result.stderr!r}"
    )
    assert "ok" in result.stdout


def test_hardening_retries_directory_not_empty_cache_race(monkeypatch, tmp_path):
    """macOS can report ENOTEMPTY if a cache dir changes during rmtree."""
    from coursecraft_cli import _bootstrap

    cache_dir = tmp_path / "__pycache__"
    cache_dir.mkdir()
    (cache_dir / "module.pyc").write_bytes(b"stale")

    calls = []
    real_rmtree = shutil.rmtree

    def flaky_rmtree(path):
        calls.append(path)
        if len(calls) == 1:
            raise OSError(errno.ENOTEMPTY, "Directory not empty", path)
        real_rmtree(path)

    monkeypatch.setattr(shutil, "rmtree", flaky_rmtree)

    _bootstrap._remove_bytecode_cache(str(cache_dir))

    assert calls == [str(cache_dir), str(cache_dir)]
    assert not cache_dir.exists()


def test_hardening_surfaces_unrelated_cache_removal_errors(monkeypatch, tmp_path):
    """Only expected cache-removal races are swallowed."""
    from coursecraft_cli import _bootstrap

    cache_dir = tmp_path / "__pycache__"
    cache_dir.mkdir()

    def broken_rmtree(path):
        raise OSError(errno.EIO, "I/O error", path)

    monkeypatch.setattr(shutil, "rmtree", broken_rmtree)

    with pytest.raises(OSError) as exc_info:
        _bootstrap._remove_bytecode_cache(str(cache_dir))

    assert exc_info.value.errno == errno.EIO
