from __future__ import annotations

import ast
import inspect
from datetime import datetime, timezone
from typing import Any, cast

import pytest
import typer

from legoscout_cli.commands import deploy as deploy_commands
from legoscout_cli.deploy import config
from legoscout_cli.deploy import db_sync


NOW = datetime(2026, 8, 25, tzinfo=timezone.utc).timestamp()
DAY = 24 * 60 * 60


def _analysis(crop_ref: str) -> list[dict[str, Any]]:
    return [
        {
            "match_group_id": "group-1",
            "detections": [{"crop_ref": crop_ref}],
            "representative_crop_ref": crop_ref,
            "verification": {"status": "unknown"},
            "quantity": 1,
            "null_value_reason": "identity unresolved",
        }
    ]


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


def test_should_preserve_pull_database_snapshot_commands(monkeypatch):
    local_calls: list[tuple[list[str], str | None]] = []
    remote_scripts: list[str] = []
    monkeypatch.setattr(config, "LOCAL_DB", "/local/current.db")
    monkeypatch.setattr(config, "REMOTE_SHARED_DB", "/remote/found.db")
    monkeypatch.setattr(db_sync.os, "getpid", lambda: 42)
    monkeypatch.setattr(
        db_sync.ssh,
        "run_local",
        lambda argv, input=None: local_calls.append((argv, input)) or "",
    )
    monkeypatch.setattr(
        db_sync.ssh,
        "run_remote_script",
        lambda script: remote_scripts.append(script) or "",
    )

    assert db_sync._pull_database() == {"copied": True}
    assert local_calls == [
        (
            [
                "scp",
                "-q",
                "adam-server:/tmp/legoscout-pull-42.db",
                "/local/current.db",
            ],
            None,
        )
    ]
    assert remote_scripts == [
        "set -euo pipefail\n"
        "sqlite3 /remote/found.db '.backup /tmp/legoscout-pull-42.db'\n",
        "rm -f /tmp/legoscout-pull-42.db\n",
    ]


def test_should_preserve_push_database_snapshot_commands(monkeypatch):
    local_calls: list[tuple[list[str], str | None]] = []
    remote_scripts: list[str] = []

    class FixedTemporaryDirectory:
        def __enter__(self):
            return "/tmp/local-snapshot"

        def __exit__(self, _kind, _value, _traceback):
            return False

    monkeypatch.setattr(config, "LOCAL_DB", "/local/current.db")
    monkeypatch.setattr(config, "REMOTE_SHARED_DB", "/remote/found.db")
    monkeypatch.setattr(config, "REMOTE_SHARED_DIR", "/remote")
    monkeypatch.setattr(db_sync.os, "getpid", lambda: 84)
    monkeypatch.setattr(db_sync.tempfile, "TemporaryDirectory", FixedTemporaryDirectory)
    monkeypatch.setattr(
        db_sync.ssh,
        "run_local",
        lambda argv, input=None: local_calls.append((argv, input)) or "",
    )
    monkeypatch.setattr(
        db_sync.ssh,
        "run_remote_script",
        lambda script: remote_scripts.append(script) or "",
    )

    assert db_sync._push_database() == {"copied": True}
    assert local_calls == [
        (
            [
                "sqlite3",
                "/local/current.db",
                ".backup /tmp/local-snapshot/found_deals.db",
            ],
            None,
        ),
        (
            [
                "scp",
                "-q",
                "/tmp/local-snapshot/found_deals.db",
                "adam-server:/tmp/legoscout-push-84.db",
            ],
            None,
        ),
    ]
    assert remote_scripts == [
        "set -euo pipefail\n"
        "mkdir -p /remote\n"
        "mv /tmp/legoscout-push-84.db /remote/found.db\n"
    ]


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
            return ">f+++++++++|aa/new.jpg\n"
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
            [
                "rsync",
                "-a",
                "--ignore-existing",
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
            return ">f+++++++++|bb/new.webp\n"
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
            [
                "rsync",
                "-a",
                "--ignore-existing",
                source,
                destination,
            ],
            None,
        ),
    ]
    assert remote_scripts == ["mkdir -p /remote/shared/crops\n"]
    assert all(not any(arg.startswith("--delete") for arg in argv) for argv, _ in calls)


def test_should_block_collision_crop_leg_without_changing_database_outcome(
    monkeypatch, tmp_path
):
    local_root = tmp_path / "crops"
    local_root.mkdir()
    monkeypatch.setattr(config, "LOCAL_SHARED_CROPS", str(local_root))
    monkeypatch.setattr(config, "REMOTE_SHARED_CROPS", "/remote/shared/crops")
    calls: list[list[str]] = []

    def fake_run_local(argv: list[str], input: str | None = None) -> str:
        assert input is None
        calls.append(argv)
        return ">fcst......|aa/collision.jpg\n>f+++++++++|bb/new.jpg\n"

    monkeypatch.setattr(db_sync.ssh, "run_local", fake_run_local)
    monkeypatch.setattr(db_sync.ssh, "run_remote_script", lambda _script: "")
    monkeypatch.setattr(db_sync, "_push_database", lambda: {"copied": True})

    report = cast(dict[str, Any], db_sync.push())

    assert report == {
        "ok": False,
        "db": {"ok": True, "result": {"copied": True}},
        "crops": {
            "ok": False,
            "error": "crop content collision: aa/collision.jpg",
        },
        "retention": {
            "ok": False,
            "skipped": True,
            "reason": "database and crop push must both succeed",
        },
    }
    assert len(calls) == 1
    assert "--dry-run" in calls[0]


def test_should_report_pull_database_and_crop_outcomes_independently(monkeypatch):
    events: list[str] = []

    def pull_db():
        events.append("db")
        raise RuntimeError("database unavailable")

    def pull_crops():
        events.append("crops")
        return {"transferred": True, "collisions": []}

    monkeypatch.setattr(db_sync, "_pull_database", pull_db)
    monkeypatch.setattr(db_sync, "_pull_crops", pull_crops)

    report = cast(dict[str, Any], db_sync.pull())

    assert events == ["db", "crops"]
    assert report == {
        "ok": False,
        "db": {"ok": False, "error": "database unavailable"},
        "crops": {
            "ok": True,
            "result": {"transferred": True, "collisions": []},
        },
    }


def test_should_attempt_push_legs_independently_and_skip_retention_on_failure(
    monkeypatch,
):
    events: list[str] = []

    def push_db():
        events.append("db")
        raise RuntimeError("database unavailable")

    def push_crops():
        events.append("crops")
        return {"transferred": True, "collisions": []}

    def retain():
        events.append("retention")
        return {"deleted": []}

    monkeypatch.setattr(db_sync, "_push_database", push_db)
    monkeypatch.setattr(db_sync, "_push_crops", push_crops)
    monkeypatch.setattr(db_sync, "_retention", retain)

    report = cast(dict[str, Any], db_sync.push())

    assert events == ["db", "crops"]
    assert report == {
        "ok": False,
        "db": {"ok": False, "error": "database unavailable"},
        "crops": {
            "ok": True,
            "result": {"transferred": True, "collisions": []},
        },
        "retention": {
            "ok": False,
            "skipped": True,
            "reason": "database and crop push must both succeed",
        },
    }


def test_should_run_retention_only_after_both_push_legs_succeed(monkeypatch):
    events: list[str] = []
    monkeypatch.setattr(
        db_sync,
        "_push_database",
        lambda: events.append("db") or {"copied": True},
    )
    monkeypatch.setattr(
        db_sync,
        "_push_crops",
        lambda: events.append("crops")
        or {"transferred": True, "collisions": []},
    )
    monkeypatch.setattr(
        db_sync,
        "_retention",
        lambda: events.append("retention") or {"deleted": ["old.jpg"]},
    )

    report = cast(dict[str, Any], db_sync.push())

    assert events == ["db", "crops", "retention"]
    assert report == {
        "ok": True,
        "db": {"ok": True, "result": {"copied": True}},
        "crops": {
            "ok": True,
            "result": {"transferred": True, "collisions": []},
        },
        "retention": {
            "ok": True,
            "result": {"deleted": ["old.jpg"]},
        },
    }


def test_should_collect_canonical_references_before_deleting_only_old_unreferenced(
    monkeypatch,
):
    events: list[object] = []
    analysis = _analysis("aa/referenced.jpg")
    analysis[0]["detections"].append({"crop_ref": "aa/evidence.jpg"})
    deals = [
        {
            "listing_key": "source|1",
            "minifig_analysis": analysis,
        }
    ]
    inventory = [
        {"path": "aa/referenced.jpg", "mtime": NOW - 60 * DAY},
        {"path": "aa/evidence.jpg", "mtime": NOW - 60 * DAY},
        {"path": "bb/old.jpg", "mtime": NOW - 31 * DAY},
        {"path": "cc/exact.jpg", "mtime": NOW - 30 * DAY},
        {"path": "dd/recent.jpg", "mtime": NOW - DAY},
    ]
    monkeypatch.setattr(
        db_sync.ledger_db,
        "load_deals",
        lambda path: events.append(("ledger", path)) or deals,
    )
    monkeypatch.setattr(
        db_sync,
        "_remote_inventory",
        lambda: events.append("inventory") or inventory,
    )
    monkeypatch.setattr(
        db_sync,
        "_delete_remote_candidates",
        lambda paths: events.append(("delete", paths)) or list(paths),
    )
    monkeypatch.setattr(config, "LOCAL_DB", "/authoritative/current.db")

    report = db_sync._retention(now=NOW)

    assert events == [
        ("ledger", "/authoritative/current.db"),
        "inventory",
        ("delete", ["bb/old.jpg"]),
    ]
    assert report == {
        "scanned": 5,
        "referenced": 2,
        "deleted": ["bb/old.jpg"],
    }


def _inventory(*, old: int, young: int) -> list[dict[str, Any]]:
    return [
        {"path": f"old/{index}.jpg", "mtime": NOW - 31 * DAY}
        for index in range(old)
    ] + [
        {"path": f"young/{index}.jpg", "mtime": NOW - DAY}
        for index in range(young)
    ]


def test_should_allow_exactly_25_percent_deletion():
    assert db_sync.retention_candidates(
        _inventory(old=2, young=6), set(), now=NOW
    ) == ["old/0.jpg", "old/1.jpg"]


def test_should_block_more_than_25_percent_deletion():
    with pytest.raises(ValueError, match="25%"):
        db_sync.retention_candidates(_inventory(old=3, young=7), set(), now=NOW)


def test_should_allow_exactly_1000_deletions():
    selected = db_sync.retention_candidates(
        _inventory(old=1000, young=3000), set(), now=NOW
    )
    assert len(selected) == 1000
    assert selected[0] == "old/0.jpg"
    assert selected[-1] == "old/999.jpg"


def test_should_block_1001_deletions():
    with pytest.raises(ValueError, match="1,000"):
        db_sync.retention_candidates(
            _inventory(old=1001, young=3003), set(), now=NOW
        )


def test_should_fail_closed_on_malformed_analysis_without_deletion(monkeypatch):
    malformed = {
        "listing_key": "k-bid|bad",
        "minifig_analysis": [
            {
                "representative_crop_ref": "../../escape.jpg",
                "detections": [],
                "verification": {"status": "unknown"},
                "quantity": 1,
                "null_value_reason": "unknown",
            }
        ],
    }
    events: list[str] = []
    monkeypatch.setattr(db_sync.ledger_db, "load_deals", lambda _path: [malformed])
    monkeypatch.setattr(
        db_sync,
        "_remote_inventory",
        lambda: events.append("inventory") or [],
    )
    monkeypatch.setattr(
        db_sync,
        "_delete_remote_candidates",
        lambda _paths: events.append("delete") or [],
    )

    with pytest.raises(ValueError, match=r"k-bid\|bad.*minifig_analysis"):
        db_sync._retention(now=NOW)

    assert events == []


def test_should_fail_closed_on_unreadable_ledger_without_deletion(
    monkeypatch, tmp_path
):
    bad_db = tmp_path / "ledger.db"
    bad_db.write_text("not sqlite")
    events: list[str] = []
    monkeypatch.setattr(config, "LOCAL_DB", str(bad_db))
    monkeypatch.setattr(
        db_sync,
        "_remote_inventory",
        lambda: events.append("inventory") or [],
    )
    monkeypatch.setattr(
        db_sync,
        "_delete_remote_candidates",
        lambda _paths: events.append("delete") or [],
    )

    with pytest.raises(Exception):
        db_sync._retention(now=NOW)

    assert events == []


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


def test_pull_command_should_print_independent_failure_report_and_exit_nonzero(
    monkeypatch,
):
    report = {
        "ok": False,
        "db": {"ok": True, "result": {"copied": True}},
        "crops": {"ok": False, "error": "crop unavailable"},
    }
    printed: list[dict[str, Any]] = []
    monkeypatch.setattr(deploy_commands.db_sync, "pull", lambda: report)
    monkeypatch.setattr(deploy_commands, "print_json", printed.append)

    with pytest.raises(typer.Exit) as raised:
        deploy_commands.pull_db()

    assert raised.value.exit_code == 1
    assert printed == [report]


def test_push_command_should_not_deploy_code_when_a_sync_leg_failed(monkeypatch):
    sync = {
        "ok": False,
        "db": {"ok": True, "result": {"copied": True}},
        "crops": {"ok": False, "error": "crop collision"},
        "retention": {"ok": False, "skipped": True},
    }
    printed: list[dict[str, Any]] = []
    deployed: list[bool] = []
    monkeypatch.setattr(deploy_commands.db_sync, "push", lambda: sync)
    monkeypatch.setattr(
        deploy_commands.release,
        "deploy_code",
        lambda: deployed.append(True),
    )
    monkeypatch.setattr(deploy_commands, "print_json", printed.append)

    with pytest.raises(typer.Exit) as raised:
        deploy_commands.push()

    assert raised.value.exit_code == 1
    assert deployed == []
    assert printed == [{"ok": False, "sync": sync, "code_deployed": False}]
