import json

import pytest
from typer.testing import CliRunner

from frameio_cli import client
from frameio_cli.main import app

from conftest import (ASSET, IMAGE, SHARE, SHARE_URL, SIGNED, URL, Response, collection_of,
                      image_metadata, metadata, public_share)

runner = CliRunner()

VIDEO_ROW = {"id": ASSET, "share_id": SHARE, "name": "approved.mp4", "type": "VideoAsset", "video": True,
             "size": 5, "mime_type": "video/mp4", "status": "TRANSCODED", "url": URL, "download_url": SIGNED}
IMAGE_ROW = {"id": IMAGE, "share_id": SHARE, "name": "still.png", "type": "ImageAsset", "video": False,
             "size": None, "mime_type": None, "status": "TRANSCODED", "url": client.stable_url(SHARE, IMAGE),
             "download_url": None}


@pytest.fixture
def two_assets(monkeypatch):
    return public_share(monkeypatch, collection=collection_of(ASSET, IMAGE),
                        assets={ASSET: metadata(), IMAGE: image_metadata()})


def run(*args):
    result = runner.invoke(app, list(args))
    return result, result.stdout


def test_shares_get_shape(two_assets):
    result, out = run("shares", "get", SHARE_URL)
    assert result.exit_code == 0, result.output
    assert json.loads(out) == {"id": SHARE, "url": SHARE_URL, "enabled": True,
                               "downloadingEnabled": True, "expiration": None}


def test_shares_get_properties_and_table(two_assets):
    result, out = run("shares", "get", SHARE_URL, "-p", "id,enabled")
    assert json.loads(out) == [{"id": SHARE, "enabled": True}]
    result, out = run("shares", "get", SHARE_URL, "--table")
    assert result.exit_code == 0 and "downloadingEnabled" in out


def test_shares_get_reports_disabled_share_without_failing(monkeypatch):
    public_share(monkeypatch, settings={"id": SHARE, "enabled": False, "downloadingEnabled": False,
                                        "expiration": "2000-01-01T00:00:00Z"})
    result, out = run("shares", "get", SHARE_URL)
    assert result.exit_code == 0
    assert json.loads(out)["enabled"] is False


def test_assets_list_shape(two_assets):
    result, out = run("assets", "list", SHARE_URL)
    assert result.exit_code == 0, result.output
    assert json.loads(out) == [VIDEO_ROW, IMAGE_ROW]


def test_assets_list_limit_filter_properties_table(two_assets):
    _, out = run("assets", "list", SHARE_URL, "--limit", "1")
    assert json.loads(out) == [VIDEO_ROW]
    _, out = run("assets", "list", SHARE_URL, "--filter", "video:eq:false", "-p", "id,name")
    assert json.loads(out) == [{"id": IMAGE, "name": "still.png"}]
    result, out = run("assets", "list", SHARE_URL, "--table")
    assert result.exit_code == 0 and "approved.mp4" in out and "still.png" in out


def test_assets_list_permission_error_goes_to_stderr(monkeypatch):
    public_share(monkeypatch, settings={"id": SHARE, "enabled": True, "downloadingEnabled": False,
                                        "expiration": None})
    result, out = run("assets", "list", SHARE_URL)
    assert result.exit_code == 1
    assert out == ""
    assert "does not allow downloads" in result.stderr


def test_assets_get_shape_and_membership(two_assets):
    _, out = run("assets", "get", SHARE_URL, ASSET)
    assert json.loads(out) == VIDEO_ROW
    result, out = run("assets", "get", SHARE_URL, "9a9a9a9a-0000-4000-8000-000000000000")
    assert result.exit_code == 1 and out == "" and "not in the share" in result.stderr


def test_assets_download_prints_result_and_writes_file(two_assets, monkeypatch, tmp_path):
    monkeypatch.setattr(client, "urlopen", lambda *a, **k: Response(b"video"))
    target = tmp_path / "out.mp4"
    result, out = run("assets", "download", SHARE_URL, ASSET, "--output", str(target))
    assert result.exit_code == 0, result.output
    assert json.loads(out) == {"id": ASSET, "name": "approved.mp4", "size": 5, "path": str(target)}
    assert target.read_bytes() == b"video"


def test_assets_download_refuses_non_video(two_assets, tmp_path):
    result, out = run("assets", "download", SHARE_URL, IMAGE, "-o", str(tmp_path / "x.png"))
    assert result.exit_code == 1 and out == "" and "not a video" in result.stderr
    assert list(tmp_path.iterdir()) == []


def test_assets_download_requires_output(two_assets):
    result, _ = run("assets", "download", SHARE_URL, ASSET)
    assert result.exit_code == 2
