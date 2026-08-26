"""Task 2 security-audit repairs: crop-serving and sync/deploy defects.

Covers five proved defects from the Phase H crop-deploy security review that
the rescue commits did not already close: remote crop root on the deployed
host, MIME magic validation, NUL-byte request paths, rsync file-vs-symlink
destination collisions, and structured deploy-failure reporting.
"""
from __future__ import annotations

import contextlib
import http.client
import json
import threading
from pathlib import Path
from typing import Any

import pytest
import typer

from legoscout_cli import paths
from legoscout_cli.commands import deploy as deploy_command
from legoscout_cli.deploy import config, db_sync, release
from legoscout_cli.display import server
from legoscout_cli.ledger import db as ledger_db


JPEG_MAGIC = b"\xff\xd8\xff\xe0" + b"\x00" * 16
PNG_MAGIC = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


def _reload_display_server():
    import importlib

    importlib.reload(paths)
    return importlib.reload(server)


@contextlib.contextmanager
def _crop_server(monkeypatch, tmp_path: Path, crops: dict[str, bytes]):
    """Serve one crop root seeded with `crops` relative-path -> bytes."""
    db_path = tmp_path / "ledger.db"
    ledger_db.init(str(db_path)).close()
    crop_root = tmp_path / "crops"
    for relative, payload in crops.items():
        target = crop_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    monkeypatch.setattr(server, "DB_OVERRIDE", str(db_path))
    monkeypatch.setattr(server, "CROP_ROOT", crop_root)
    original_hosts = set(server.ALLOWED_HOSTS)
    httpd = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
    server.ALLOWED_HOSTS.add(f"127.0.0.1:{httpd.server_port}")
    server.ALLOWED_HOSTS.add(f"localhost:{httpd.server_port}")
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_port
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()
        server.ALLOWED_HOSTS.clear()
        server.ALLOWED_HOSTS.update(original_hosts)


def _get(port: int, path: str):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path, headers={"Host": f"localhost:{port}"})
    response = conn.getresponse()
    body = response.read()
    ctype = response.getheader("Content-Type")
    conn.close()
    return response.status, ctype, body


# --- defect 1: deployed server must read ITS OWN crop root -------------------


def test_crop_root_default_is_project_relative_not_machine_literal():
    """The default derives from LEGOSCOUT_ROOT so a mirrored deploy layout
    resolves its own tree; no second hardcoded /Users/adam absolute lives
    outside paths.py."""
    expected = str(
        paths.LEGOSCOUT_ROOT / "agent_workspaces" / "shared" / "minifig-crops"
    )
    assert paths.MINIFIG_CROP_ROOT == expected


def test_crop_root_env_override_redirects_the_server(
    monkeypatch, tmp_path,
):
    """A deployed host exports LEGOSCOUT_MINIFIG_CROP_ROOT and serves crops
    from its own shared tree without code edits."""
    custom = tmp_path / "remote-shared" / "minifig-crops"
    custom.mkdir(parents=True)
    monkeypatch.setenv("LEGOSCOUT_MINIFIG_CROP_ROOT", str(custom))
    try:
        _reload_display_server()
        assert Path(str(server.CROP_ROOT)) == custom
    finally:
        monkeypatch.delenv("LEGOSCOUT_MINIFIG_CROP_ROOT")
        _reload_display_server()


# --- defect 3: NUL-byte request paths get 400, never drop the connection -----


def test_nul_byte_crop_path_answers_400_instead_of_dropping(
    monkeypatch, tmp_path,
):
    with _crop_server(
        monkeypatch, tmp_path, {"aa/figcrop-v1-x.jpg": JPEG_MAGIC}
    ) as port:
        status, ctype, body = _get(port, "/crops/aa%00figcrop-v1-x.jpg")
    assert status == 400
    assert json.loads(body)["error"]


def test_nul_byte_inside_relative_segments_answers_400(monkeypatch, tmp_path):
    with _crop_server(
        monkeypatch, tmp_path, {"aa/figcrop-v1-x.jpg": JPEG_MAGIC}
    ) as port:
        status, _, _ = _get(port, "/crops/aa%00/figcrop-v1-x.jpg")
    assert status == 400


# --- MIME defect: extension alone must not bless arbitrary bytes -------------


def test_matching_jpeg_magic_serves_image_jpeg(monkeypatch, tmp_path):
    with _crop_server(
        monkeypatch, tmp_path, {"aa/figcrop-v1-ok.jpg": JPEG_MAGIC}
    ) as port:
        status, ctype, body = _get(port, "/crops/aa/figcrop-v1-ok.jpg")
    assert status == 200
    assert ctype == "image/jpeg"
    assert body.startswith(JPEG_MAGIC[:2])


def test_png_bytes_in_jpg_rejected_415(monkeypatch, tmp_path):
    with _crop_server(
        monkeypatch, tmp_path, {"aa/figcrop-v1-fake.jpg": PNG_MAGIC}
    ) as port:
        status, _, body = _get(port, "/crops/aa/figcrop-v1-fake.jpg")
    assert status == 415
    assert json.loads(body)["error"]


def test_png_extension_with_png_magic_serves_image_png(monkeypatch, tmp_path):
    with _crop_server(
        monkeypatch, tmp_path, {"bb/figcrop-v1-real.png": PNG_MAGIC}
    ) as port:
        status, ctype, _ = _get(port, "/crops/bb/figcrop-v1-real.png")
    assert status == 200
    assert ctype == "image/png"


# --- defect 4: rsync must refuse non-regular destination collisions ----------


def test_push_crops_refuses_when_destination_holds_symlinks(
    monkeypatch, tmp_path,
):
    """--ignore-existing silently skips a same-name destination entry. The
    crop leg must re-verify after transfer and block loudly when an addition
    never landed (destination holds a symlink/directory/non-regular entry)."""
    local_root = tmp_path / "local-crops"
    (local_root / "aa").mkdir(parents=True)
    (local_root / "aa" / "evil.jpg").write_bytes(JPEG_MAGIC)
    monkeypatch.setattr(config, "LOCAL_SHARED_CROPS", str(local_root))
    monkeypatch.setattr(config, "REMOTE_SHARED_CROPS", "/remote/crops")
    calls: list[list[str]] = []

    def fake_run_local(argv: list[str], input: str | None = None) -> str:
        calls.append(argv)
        if "--dry-run" in argv:
            # Every dry-run still shows the file as new: the simulated remote
            # has a symlink named evil.jpg that --ignore-existing skips.
            return ">f+++++++++|aa/evil.jpg\n"
        return ""

    monkeypatch.setattr(db_sync.ssh, "run_local", fake_run_local)

    with pytest.raises(ValueError, match="aa/evil\\.jpg"):
        db_sync._push_crops()
    # mkdir leg (ssh via run_local), preflight, transfer, verification
    assert len(calls) == 4
    assert all(
        not any(arg.startswith("--delete") for arg in argv) for argv in calls
    )


def test_push_crops_still_reports_transferred_when_verification_clean(
    monkeypatch, tmp_path,
):
    local_root = tmp_path / "local-crops"
    (local_root / "aa").mkdir(parents=True)
    (local_root / "aa" / "ok.jpg").write_bytes(JPEG_MAGIC)
    monkeypatch.setattr(config, "LOCAL_SHARED_CROPS", str(local_root))
    monkeypatch.setattr(config, "REMOTE_SHARED_CROPS", "/remote/crops")
    calls: list[list[str]] = []

    def fake_run_local(argv: list[str], input: str | None = None) -> str:
        calls.append(argv)
        if "--dry-run" in argv:
            # First dry-run sees the addition; after the transfer the file is
            # really there, so the verification dry-run reports nothing.
            if not any(
                previous is not argv and "--dry-run" in previous
                for previous in calls[:-1]
            ):
                return ">f+++++++++|aa/ok.jpg\n"
            return ""
        return ""

    monkeypatch.setattr(db_sync.ssh, "run_local", fake_run_local)

    report: dict[str, Any] = db_sync._push_crops()
    # mkdir leg (ssh via run_local), preflight, transfer, verification
    assert len(calls) == 4
    assert report == {"transferred": True, "collisions": []}


# --- defect 6: failed code deploy must still report the sync outcomes --------


def _sample_sync() -> dict[str, Any]:
    return {
        "ok": True,
        "db": {"ok": True, "result": {"copied": True}},
        "crops": {
            "ok": True,
            "result": {"transferred": True, "collisions": []},
        },
        "retention": {"ok": True, "result": {"scanned": 1, "referenced": 1, "deleted": []}},
    }


def test_failed_code_deploy_reports_sync_outcomes_structured(monkeypatch):
    monkeypatch.setattr(db_sync, "push", _sample_sync)

    def failing_deploy():
        raise release.DeployError("pm2 restart failed")

    monkeypatch.setattr(release, "deploy_code", failing_deploy)
    printed: list[dict[str, Any]] = []
    monkeypatch.setattr(deploy_command, "print_json", printed.append)

    with pytest.raises(typer.Exit) as excinfo:
        deploy_command.push()

    assert excinfo.value.exit_code == 1
    payload = printed[-1]
    assert payload["ok"] is False
    assert payload["code_deployed"] is False
    # The already-successful legs stay visible in structured output.
    assert payload["sync"]["db"]["ok"] is True
    assert payload["sync"]["crops"]["ok"] is True
