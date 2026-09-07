from __future__ import annotations

import ast
import inspect

from legoscout_cli.deploy import config, db_sync


def test_should_lock_shared_crop_roots_outside_release_directories():
    assert config.LOCAL_SHARED_CROPS == (
        "/Users/adam/Dropbox/GitRepos/Agents/LegoScout/agent_workspaces/"
        "shared/minifig-crops"
    )
    assert config.REMOTE_SHARED_CROPS == (
        "/Users/adam/GitRepos/legoscout/shared/minifig-crops"
    )
    assert "/releases/" not in config.LOCAL_SHARED_CROPS
    assert "/releases/" not in config.REMOTE_SHARED_CROPS



def test_should_pull_remote_authoritative_crops_additively_with_exact_argv(
    monkeypatch, tmp_path
):
    local_root = tmp_path / "crops"
    local_root.mkdir()
    monkeypatch.setattr(config, "LOCAL_SHARED_CROPS", str(local_root))
    monkeypatch.setattr(config, "REMOTE_SHARED_CROPS", "/remote/shared/crops")
    calls: list[tuple[list[str], str | None]] = []
    remote_scripts: list[str] = []

    def fake_run_local(argv: list[str], input: str | None = None) -> str:
        calls.append((argv, input))
        if "--dry-run" in argv:
            # First dry-run is the preflight; the second is the post-transfer
            # verification, which must come back clean.
            if not any(
                previous_argv is not argv and "--dry-run" in previous_argv
                for previous_argv, _ in calls[:-1]
            ):
                return ">f+++++++++|aa/new.jpg\n"
            return ""
        return ""

    monkeypatch.setattr(db_sync.ssh, "run_local", fake_run_local)
    monkeypatch.setattr(
        db_sync.ssh,
        "run_remote_script",
        lambda script: remote_scripts.append(script) or "",
    )

    report = db_sync._pull_crops()

    source = "adam-server:/remote/shared/crops/"
    destination = str(local_root) + "/"
    assert report == {"transferred": True, "collisions": []}
    assert calls == [
        (
            [
                "rsync",
                "-a",
                "--checksum",
                "--dry-run",
                "--itemize-changes",
                "--out-format=%i|%n",
                source,
                destination,
            ],
            None,
        ),
        (
            ["rsync", "-a", "--existing", "--size-only", "--dry-run",
             "--itemize-changes", "--out-format=%i|%n", destination, source],
            None,
        ),
        (
            [
                "rsync",
                "-a",
                "--ignore-existing",
                source,
                destination,
            ],
            None,
        ),
        (
            [
                "rsync",
                "-a",
                "--checksum",
                "--dry-run",
                "--itemize-changes",
                "--out-format=%i|%n",
                source,
                destination,
            ],
            None,
        ),
    ]
    assert remote_scripts == ["mkdir -p /remote/shared/crops\n"]
    assert all(not any(arg.startswith("--delete") for arg in argv) for argv, _ in calls)



def test_should_push_local_crops_additively_with_exact_argv(monkeypatch, tmp_path):
    local_root = tmp_path / "crops"
    local_root.mkdir()
    monkeypatch.setattr(config, "LOCAL_SHARED_CROPS", str(local_root))
    monkeypatch.setattr(config, "REMOTE_SHARED_CROPS", "/remote/shared/crops")
    calls: list[tuple[list[str], str | None]] = []
    remote_scripts: list[str] = []

    def fake_run_local(argv: list[str], input: str | None = None) -> str:
        calls.append((argv, input))
        if "--dry-run" in argv:
            # First dry-run is the preflight; the second is the post-transfer
            # verification, which must come back clean.
            if not any(
                previous is not argv and "--dry-run" in previous
                for previous, _ in calls[:-1]
            ):
                return ">f+++++++++|bb/new.webp\n"
            return ""
        return ""

    monkeypatch.setattr(db_sync.ssh, "run_local", fake_run_local)
    monkeypatch.setattr(
        db_sync.ssh,
        "run_remote_script",
        lambda script: remote_scripts.append(script) or "",
    )

    report = db_sync._push_crops()

    source = str(local_root) + "/"
    destination = "adam-server:/remote/shared/crops/"
    assert report == {"transferred": True, "collisions": []}
    assert calls == [
        (
            [
                "rsync",
                "-a",
                "--checksum",
                "--dry-run",
                "--itemize-changes",
                "--out-format=%i|%n",
                source,
                destination,
            ],
            None,
        ),
        (
            ["rsync", "-a", "--existing", "--size-only", "--dry-run",
             "--itemize-changes", "--out-format=%i|%n", destination, source],
            None,
        ),
        (
            [
                "rsync",
                "-a",
                "--ignore-existing",
                source,
                destination,
            ],
            None,
        ),
        (
            [
                "rsync",
                "-a",
                "--checksum",
                "--dry-run",
                "--itemize-changes",
                "--out-format=%i|%n",
                source,
                destination,
            ],
            None,
        ),
    ]
    assert remote_scripts == ["mkdir -p /remote/shared/crops\n"]
    assert all(not any(arg.startswith("--delete") for arg in argv) for argv, _ in calls)



def test_should_not_use_release_rsync_or_rsync_delete_flags():
    tree = ast.parse(inspect.getsource(db_sync))
    imported_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    attribute_names = {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    rsync_flags = {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith("--delete")
    }

    assert "release" not in imported_names
    assert "_rsync" not in imported_names
    assert "_rsync" not in attribute_names
    assert rsync_flags == set()
