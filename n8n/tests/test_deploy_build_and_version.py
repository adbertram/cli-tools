"""Tests for `n8n nodes deploy` build gating and version-bump ordering.

Regression coverage for agent-issues #626:
- deploy always ran `npm run build`, which fails with "Missing script: build"
  for hand-written-JS CommonJS node packages that have no build script.
- deploy bumped package.json's version BEFORE the build, so a failed build
  consumed a version number (0.1.0 -> 0.1.1 on failure, then 0.1.2 on retry).

The deploy pipeline is stopped just after the version-bump decision by making
sync_to_server return a failure, so these tests never touch a real server.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import typer

from n8n_cli.commands import deploy


def _write_package(tmp_path, version="0.1.0", with_build=True):
    pkg_dir = tmp_path / "n8n-nodes-fixture"
    pkg_dir.mkdir()
    scripts = {"build": "tsc"} if with_build else {"test": "echo ok"}
    (pkg_dir / "package.json").write_text(
        json.dumps({"name": "n8n-nodes-fixture", "version": version, "scripts": scripts}) + "\n"
    )
    return pkg_dir


def _read_version(pkg_dir):
    return json.loads((pkg_dir / "package.json").read_text())["version"]


def _ok(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _patch_common(monkeypatch, local_runner):
    """Patch config, local runner, and server calls; halt right after the bump."""
    monkeypatch.setattr(deploy, "get_config", lambda: SimpleNamespace(output_dir="/tmp"))
    monkeypatch.setattr(deploy, "_run_local", local_runner)
    monkeypatch.setattr(deploy, "run_on_server_raw", lambda *a, **k: _ok())
    # Stop the pipeline immediately after the version bump so no real server work runs.
    monkeypatch.setattr(deploy, "sync_to_server", lambda *a, **k: _ok(returncode=1, stderr="halt"))


def test_no_build_script_skips_npm_run_build_and_bumps_once(tmp_path, monkeypatch):
    pkg_dir = _write_package(tmp_path, version="0.1.0", with_build=False)
    calls = []

    def local_runner(cmd, cwd=None, timeout=120):
        calls.append(cmd)
        return _ok()

    _patch_common(monkeypatch, local_runner)

    with pytest.raises(typer.Exit):  # halted at sync step, after the bump
        deploy.deploy_node(
            package_path=str(pkg_dir),
            skip_build=False,
            skip_restart=True,
            skip_verify=True,
            skip_auth_check=True,
        )

    ran = [c for c in calls]
    assert ["npm", "install"] in ran
    assert ["npm", "run", "build"] not in ran  # no build script -> skipped
    assert _read_version(pkg_dir) == "0.1.1"  # bumped exactly once


def test_failed_build_does_not_bump_version(tmp_path, monkeypatch):
    pkg_dir = _write_package(tmp_path, version="0.1.0", with_build=True)

    def local_runner(cmd, cwd=None, timeout=120):
        if cmd == ["npm", "run", "build"]:
            return _ok(returncode=1, stderr='npm error Missing script: "build"')
        return _ok()

    _patch_common(monkeypatch, local_runner)

    with pytest.raises(typer.Exit):
        deploy.deploy_node(
            package_path=str(pkg_dir),
            skip_build=False,
            skip_restart=True,
            skip_verify=True,
            skip_auth_check=True,
        )

    # Build failed BEFORE the bump, so no version was consumed.
    assert _read_version(pkg_dir) == "0.1.0"


def test_successful_build_bumps_after_build(tmp_path, monkeypatch):
    pkg_dir = _write_package(tmp_path, version="0.1.0", with_build=True)
    calls = []

    def local_runner(cmd, cwd=None, timeout=120):
        calls.append(cmd)
        return _ok()

    _patch_common(monkeypatch, local_runner)

    with pytest.raises(typer.Exit):  # halted at sync step, after build + bump
        deploy.deploy_node(
            package_path=str(pkg_dir),
            skip_build=False,
            skip_restart=True,
            skip_verify=True,
            skip_auth_check=True,
        )

    assert ["npm", "run", "build"] in calls  # build ran
    assert _read_version(pkg_dir) == "0.1.1"  # bumped after a successful build


def test_skip_build_still_bumps(tmp_path, monkeypatch):
    pkg_dir = _write_package(tmp_path, version="0.1.0", with_build=True)
    calls = []

    def local_runner(cmd, cwd=None, timeout=120):
        calls.append(cmd)
        return _ok()

    _patch_common(monkeypatch, local_runner)

    with pytest.raises(typer.Exit):
        deploy.deploy_node(
            package_path=str(pkg_dir),
            skip_build=True,
            skip_restart=True,
            skip_verify=True,
            skip_auth_check=True,
        )

    assert calls == []  # nothing built
    assert _read_version(pkg_dir) == "0.1.1"
