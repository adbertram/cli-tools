"""Regression tests for Descript raw asset export downloads."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from descript_cli.client import ClientError, DescriptClient
from descript_cli.models import ExportPlaylist


class FakeResponse:
    def __init__(self, status_code: int, content: bytes = b"", headers: dict | None = None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self.text = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status_code < 300

    def json(self):
        return {}


def _make_client(tmp_path: Path) -> DescriptClient:
    config = SimpleNamespace(
        base_url="https://web.descript.com",
        get_profile_data_dir=lambda: tmp_path / "profile-data",
    )
    return DescriptClient(config=config, base_delay=1, max_delay=1, jitter=0)


def _make_playlist() -> ExportPlaylist:
    return ExportPlaylist(
        url="https://media.descriptusercontent.com/proxy-big/video",
        params="asset=test",
        end=6,
        expiry=999999,
        fragment_starts=[0, 2, 4],
    )


def test_download_export_retries_rate_limited_segment(monkeypatch, tmp_path):
    client = _make_client(tmp_path)
    playlist = _make_playlist()
    responses = iter([
        FakeResponse(200, b"aa"),
        FakeResponse(429, headers={"Retry-After": "3"}),
        FakeResponse(200, b"bb"),
        FakeResponse(200, b"cc"),
    ])
    requested_urls = []
    sleeps = []

    def fake_get(url, timeout):
        requested_urls.append((url, timeout))
        return next(responses)

    monkeypatch.setattr("descript_cli.client.requests.get", fake_get)
    monkeypatch.setattr("descript_cli.client.time.sleep", lambda seconds: sleeps.append(seconds))

    output_path = tmp_path / "asset.mp4"
    result = client.download_export(playlist, str(output_path))

    assert result == str(output_path)
    assert output_path.read_bytes() == b"aabbcc"
    assert not output_path.with_name("asset.mp4.part").exists()
    assert not output_path.with_name("asset.mp4.part.json").exists()
    assert sleeps == [3.0]
    assert requested_urls == [
        ("https://media.descriptusercontent.com/proxy-big/video?asset=test&start=0&end=2", 60),
        ("https://media.descriptusercontent.com/proxy-big/video?asset=test&start=2&end=4", 60),
        ("https://media.descriptusercontent.com/proxy-big/video?asset=test&start=2&end=4", 60),
        ("https://media.descriptusercontent.com/proxy-big/video?asset=test&start=4&end=6", 60),
    ]


def test_download_export_resumes_matching_partial_download(monkeypatch, tmp_path):
    client = _make_client(tmp_path)
    playlist = _make_playlist()
    resumed_playlist = ExportPlaylist(
        url=playlist.url,
        params="asset=test&fresh=1",
        end=playlist.end,
        expiry=playlist.expiry,
        fragment_starts=playlist.fragment_starts,
    )
    output_path = tmp_path / "asset.mp4"
    part_path = output_path.with_name("asset.mp4.part")
    state_path = output_path.with_name("asset.mp4.part.json")
    part_path.write_bytes(b"aa")
    client._save_download_state(
        state_path,
        client._download_playlist_key(playlist),
        next_segment=1,
        downloaded_bytes=2,
    )
    responses = iter([
        FakeResponse(200, b"bb"),
        FakeResponse(200, b"cc"),
    ])
    requested_urls = []

    def fake_get(url, timeout):
        requested_urls.append((url, timeout))
        return next(responses)

    monkeypatch.setattr("descript_cli.client.requests.get", fake_get)

    result = client.download_export(resumed_playlist, str(output_path))

    assert result == str(output_path)
    assert output_path.read_bytes() == b"aabbcc"
    assert not part_path.exists()
    assert not state_path.exists()
    assert requested_urls == [
        ("https://media.descriptusercontent.com/proxy-big/video?asset=test&fresh=1&start=2&end=4", 60),
        ("https://media.descriptusercontent.com/proxy-big/video?asset=test&fresh=1&start=4&end=6", 60),
    ]


def test_download_export_fails_when_partial_state_mismatches(tmp_path):
    client = _make_client(tmp_path)
    playlist = _make_playlist()
    output_path = tmp_path / "asset.mp4"
    part_path = output_path.with_name("asset.mp4.part")
    state_path = output_path.with_name("asset.mp4.part.json")
    part_path.write_bytes(b"aa")
    state_path.write_text('{"playlist_key":"other","next_segment":1,"downloaded_bytes":2}')

    with pytest.raises(ClientError, match="does not match this playlist"):
        client.download_export(playlist, str(output_path))


def test_download_export_fails_when_playlist_has_no_segments(tmp_path):
    client = _make_client(tmp_path)
    playlist = ExportPlaylist(
        url="https://media.descriptusercontent.com/proxy-big/video",
        params="asset=test",
        end=0,
        expiry=999999,
        fragment_starts=[],
    )

    with pytest.raises(ClientError, match="Export playlist has no media segments"):
        client.download_export(playlist, str(tmp_path / "asset.mp4"))
