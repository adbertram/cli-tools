from slack_cli.client import SlackClient
from slack_cli.commands import files

CHANNEL_ID = "C123"
COMMENT = "Approved source audio"
FILE_ID = "F123"
THREAD_TS = "1785166619.133709"
TITLE = "Source audio"


class _UploadResponse:
    ok = True


def test_upload_command_passes_thread_timestamp(monkeypatch, tmp_path, capsys):
    source = tmp_path / "source.wav"
    source.write_bytes(b"audio")
    calls = []

    class FakeClient:
        def upload_file(self, **kwargs):
            calls.append(kwargs)
            return {"ok": True, "file": {"id": FILE_ID, "title": TITLE}}

    monkeypatch.setattr(files, "get_client", lambda: FakeClient())

    files.upload_file(
        file_path=str(source),
        channels=CHANNEL_ID,
        title=TITLE,
        comment=COMMENT,
        thread_ts=THREAD_TS,
    )

    assert calls == [
        {
            "file_path": str(source),
            "channels": CHANNEL_ID,
            "title": TITLE,
            "initial_comment": COMMENT,
            "thread_ts": THREAD_TS,
        }
    ]
    assert f'"id": "{FILE_ID}"' in capsys.readouterr().out


def test_upload_client_adds_thread_timestamp_to_complete_request(
    monkeypatch,
    tmp_path,
):
    source = tmp_path / "source.wav"
    source.write_bytes(b"audio")
    client = object.__new__(SlackClient)
    requests = []

    def fake_request(method, endpoint, **kwargs):
        requests.append((method, endpoint, kwargs))
        if endpoint == "files.getUploadURLExternal":
            return {"ok": True, "upload_url": "https://upload.example", "file_id": FILE_ID}
        return {"ok": True, "files": [{"id": FILE_ID, "title": TITLE}]}

    monkeypatch.setattr(client, "_make_request", fake_request)
    monkeypatch.setattr(
        "slack_cli.client.requests.post",
        lambda *args, **kwargs: _UploadResponse(),
    )

    result = client.upload_file(
        file_path=str(source),
        channels=CHANNEL_ID,
        title=TITLE,
        initial_comment=COMMENT,
        thread_ts=THREAD_TS,
    )

    assert result == {"ok": True, "file": {"id": FILE_ID, "title": TITLE}}
    assert requests[-1] == (
        "POST",
        "files.completeUploadExternal",
        {
            "data": {
                "files": [{"id": FILE_ID, "title": TITLE}],
                "channel_id": CHANNEL_ID,
                "initial_comment": COMMENT,
                "thread_ts": THREAD_TS,
            }
        },
    )
