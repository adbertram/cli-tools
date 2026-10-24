import json

import pytest
import typer

from slack_cli.client import ClientError, SlackClient
from slack_cli.commands import files

CHANNEL_ID = "C123"
COMMENT = "Approved source audio"
FILE_ID = "F123"
THREAD_TS = "1785166619.133709"
TITLE = "Source audio"


class _UploadResponse:
    ok = True


def _fake_slack(monkeypatch):
    """Return (client, requests, posts) with Slack HTTP calls mocked."""
    client = object.__new__(SlackClient)
    requests = []
    posts = []
    counter = iter(range(1, 100))

    def fake_request(method, endpoint, **kwargs):
        requests.append((method, endpoint, kwargs))
        if endpoint == "files.getUploadURLExternal":
            n = next(counter)
            return {"ok": True, "upload_url": f"https://upload.example/{n}", "file_id": f"F{n}"}
        return {"ok": True, "files": [dict(f) for f in kwargs["data"]["files"]]}

    def fake_post(url, **kwargs):
        posts.append(url)
        return _UploadResponse()

    monkeypatch.setattr(client, "_make_request", fake_request)
    monkeypatch.setattr("slack_cli.client.requests.post", fake_post)
    return client, requests, posts


def _make_files(tmp_path, names):
    paths = []
    for name in names:
        p = tmp_path / name
        p.write_bytes(b"data")
        paths.append(str(p))
    return paths


def test_upload_command_passes_thread_timestamp(monkeypatch, tmp_path, capsys):
    (source,) = _make_files(tmp_path, ["source.wav"])
    calls = []

    class FakeClient:
        def upload_file(self, **kwargs):
            calls.append(kwargs)
            return {"ok": True, "file": {"id": FILE_ID, "title": TITLE}, "files": [{"id": FILE_ID, "title": TITLE}]}

    monkeypatch.setattr(files, "get_client", lambda: FakeClient())

    files.upload_file(
        file_paths=[source],
        channels=CHANNEL_ID,
        title=TITLE,
        comment=COMMENT,
        thread_ts=THREAD_TS,
    )

    assert calls == [
        {
            "file_paths": [source],
            "channels": CHANNEL_ID,
            "title": TITLE,
            "initial_comment": COMMENT,
            "thread_ts": THREAD_TS,
        }
    ]
    # Single file keeps the original {"id","title"} output shape
    assert json.loads(capsys.readouterr().out) == {"id": FILE_ID, "title": TITLE}


def test_upload_command_multiple_files_prints_files_array(monkeypatch, tmp_path, capsys):
    paths = _make_files(tmp_path, ["a.pptx", "b.pptx"])
    uploaded = [{"id": "F1", "title": "a.pptx"}, {"id": "F2", "title": "b.pptx"}]

    class FakeClient:
        def upload_file(self, **kwargs):
            return {"ok": True, "file": uploaded[0], "files": uploaded}

    monkeypatch.setattr(files, "get_client", lambda: FakeClient())

    files.upload_file(file_paths=paths, channels=CHANNEL_ID, title=None, comment=COMMENT, thread_ts=None)

    assert json.loads(capsys.readouterr().out) == {"files": uploaded}


def test_upload_command_validates_every_path_before_uploading(monkeypatch, tmp_path):
    (good,) = _make_files(tmp_path, ["a.pptx"])
    missing = str(tmp_path / "missing.pptx")

    def boom():
        raise AssertionError("client must not be created when a path is missing")

    monkeypatch.setattr(files, "get_client", boom)

    with pytest.raises(typer.Exit) as exc:
        files.upload_file(file_paths=[good, missing], channels=CHANNEL_ID, title=None, comment=None, thread_ts=None)
    assert exc.value.exit_code != 0


def test_upload_client_adds_thread_timestamp_to_complete_request(monkeypatch, tmp_path):
    (source,) = _make_files(tmp_path, ["source.wav"])
    client, requests, _ = _fake_slack(monkeypatch)

    result = client.upload_file(
        file_paths=[source],
        channels=CHANNEL_ID,
        title=TITLE,
        initial_comment=COMMENT,
        thread_ts=THREAD_TS,
    )

    assert result == {
        "ok": True,
        "file": {"id": "F1", "title": TITLE},
        "files": [{"id": "F1", "title": TITLE}],
    }
    assert requests[-1] == (
        "POST",
        "files.completeUploadExternal",
        {
            "data": {
                "files": [{"id": "F1", "title": TITLE}],
                "channel_id": CHANNEL_ID,
                "initial_comment": COMMENT,
                "thread_ts": THREAD_TS,
            }
        },
    )


def test_upload_client_multiple_files_completes_once(monkeypatch, tmp_path):
    paths = _make_files(tmp_path, ["a.pptx", "b.pptx", "c.pptx"])
    client, requests, posts = _fake_slack(monkeypatch)

    result = client.upload_file(file_paths=paths, channels=CHANNEL_ID, initial_comment=COMMENT)

    endpoints = [endpoint for _, endpoint, _ in requests]
    assert endpoints.count("files.getUploadURLExternal") == 3
    assert endpoints.count("files.completeUploadExternal") == 1
    assert endpoints[-1] == "files.completeUploadExternal"
    assert posts == [f"https://upload.example/{n}" for n in (1, 2, 3)]
    expected = [
        {"id": "F1", "title": "a.pptx"},
        {"id": "F2", "title": "b.pptx"},
        {"id": "F3", "title": "c.pptx"},
    ]
    assert requests[-1][2]["data"] == {
        "files": expected,
        "channel_id": CHANNEL_ID,
        "initial_comment": COMMENT,
    }
    assert result == {"ok": True, "file": expected[0], "files": expected}


def test_upload_client_rejects_more_than_ten_files(monkeypatch, tmp_path):
    paths = _make_files(tmp_path, [f"f{i}.txt" for i in range(11)])
    client, requests, posts = _fake_slack(monkeypatch)

    with pytest.raises(ClientError, match="at most 10"):
        client.upload_file(file_paths=paths, channels=CHANNEL_ID)

    assert requests == [] and posts == []


def test_upload_client_accepts_exactly_ten_files(monkeypatch, tmp_path):
    paths = _make_files(tmp_path, [f"f{i}.txt" for i in range(10)])
    client, requests, _ = _fake_slack(monkeypatch)

    result = client.upload_file(file_paths=paths, channels=CHANNEL_ID)

    assert len(requests[-1][2]["data"]["files"]) == 10
    assert len(result["files"]) == 10


def test_upload_client_rejects_title_with_multiple_files(monkeypatch, tmp_path):
    paths = _make_files(tmp_path, ["a.txt", "b.txt"])
    client, requests, posts = _fake_slack(monkeypatch)

    with pytest.raises(ClientError, match="--title"):
        client.upload_file(file_paths=paths, channels=CHANNEL_ID, title="One title")

    assert requests == [] and posts == []
