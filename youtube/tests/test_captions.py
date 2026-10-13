import json

from googleapiclient.errors import HttpError
from httplib2 import Response
from typer.testing import CliRunner

from youtube_cli.commands import channel
from youtube_cli.main import app

runner = CliRunner()


class _Request:
    def __init__(self, result=None, error=None, chunks=None):
        self.result = result
        self.error = error
        self.chunks = chunks

    def execute(self):
        if self.error:
            raise self.error
        return self.result

    def next_chunk(self):
        return None, self.result


class FakeService:
    def __init__(self, caption_error=None):
        self.caption_error = caption_error
        self.caption_calls = []
        self.video_calls = []

    def videos(self):
        return self

    def insert(self, **kwargs):
        if "media_body" in kwargs and kwargs.get("part") == "snippet,status":
            self.video_calls.append(kwargs)
            return _Request({"id": "VID1"})
        self.caption_calls.append(kwargs)
        return _Request({"id": "CAP1"}, error=self.caption_error)

    def captions(self):
        return self


class _ThumbnailFailure:
    def set(self, **kwargs):
        raise ConnectionResetError("reset by peer")


class FakeClient:
    def __init__(self, service):
        self.service = service

    def get_youtube_service(self):
        return self.service


def _setup(monkeypatch, service):
    monkeypatch.setattr(channel, "get_api_client", lambda profile=None: FakeClient(service))
    monkeypatch.setattr(channel, "MediaFileUpload", lambda path, **kwargs: ("media", path, kwargs))


def _files(tmp_path):
    video = tmp_path / "short.mp4"
    video.write_bytes(b"video")
    srt = tmp_path / "short.srt"
    srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n")
    return video, srt


def test_upload_commands_have_no_caption_flags(monkeypatch, tmp_path):
    service = FakeService()
    _setup(monkeypatch, service)
    video, srt = _files(tmp_path)

    for group in (["shorts", "upload"], ["channel", "videos", "upload"]):
        result = runner.invoke(app, [*group, str(video), "--title", "T", "--caption-file", str(srt)])
        assert result.exit_code == 2
        assert "No such option" in result.output

    assert service.video_calls == []


def test_upload_prints_result_without_caption_fields(monkeypatch, tmp_path):
    service = FakeService()
    _setup(monkeypatch, service)
    video, _ = _files(tmp_path)

    result = runner.invoke(app, ["shorts", "upload", str(video), "--title", "T"])

    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["id"] == "VID1"
    assert "caption_id" not in payload
    assert "caption_error" not in payload
    assert service.caption_calls == []


def test_thumbnail_failure_still_prints_uploaded_video_id(monkeypatch, tmp_path):
    service = FakeService()
    service.thumbnails = lambda: _ThumbnailFailure()
    _setup(monkeypatch, service)
    video, _ = _files(tmp_path)
    thumb = tmp_path / "t.jpg"
    thumb.write_bytes(b"jpg")

    result = runner.invoke(
        app, ["shorts", "upload", str(video), "--title", "T", "--thumbnail", str(thumb)]
    )

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["id"] == "VID1"
    assert payload["thumbnail_uploaded"] is False
    assert "thumbnail upload failed" in result.stderr


def test_captions_add_inserts_track_on_existing_video(monkeypatch, tmp_path):
    service = FakeService()
    _setup(monkeypatch, service)
    _, srt = _files(tmp_path)

    result = runner.invoke(
        app,
        ["channel", "videos", "captions", "add", "VID9", str(srt), "--language", "fr", "--name", "Francais"],
    )

    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout) == {
        "video_id": "VID9", "caption_id": "CAP1", "language": "fr", "name": "Francais"
    }
    assert service.caption_calls[0]["body"]["snippet"]["videoId"] == "VID9"
    assert service.video_calls == []


def test_captions_add_http_error_exits_nonzero(monkeypatch, tmp_path):
    error = HttpError(Response({"status": "403"}), b"forbidden")
    _setup(monkeypatch, FakeService(caption_error=error))
    _, srt = _files(tmp_path)

    result = runner.invoke(app, ["channel", "videos", "captions", "add", "VID9", str(srt)])

    assert result.exit_code == 1
    assert "HTTP error" in result.stderr
