"""Tests for the youtube analytics report command (mocked API services)."""

import json
import re

import pytest
from googleapiclient.errors import HttpError
from typer.testing import CliRunner

from youtube_cli.commands import analytics
from youtube_cli.main import app

RUNNER = CliRunner()
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def _plain(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _output_json(result) -> list:
    text = _plain(result.output)
    start = text.find("[")
    end = text.rfind("]") + 1
    return json.loads(text[start:end])


class _Callable:
    """Mimics googleapiclient's chainable resource: .list(**kw).execute()."""

    def __init__(self, handler):
        self._handler = handler
        self.kwargs = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return self

    def execute(self):
        return self._handler(self.kwargs)


class _Resource:
    def __init__(self, handler):
        self._handler = handler

    def list(self, **kwargs):
        return _Callable(self._handler)(**kwargs)


class FakeDataService:
    """Mimics the subset of the Data API used: uploads playlist + video titles."""

    UPLOADS_ID = "UU_fake_uploads_playlist"

    def __init__(self, videos):
        # videos: list of (video_id, title)
        self._videos = videos
        self.playlist_calls = []
        self.videos_calls = []

    def channels(self):
        def handler(kwargs):
            return {
                "items": [
                    {
                        "contentDetails": {
                            "relatedPlaylists": {"uploads": self.UPLOADS_ID}
                        }
                    }
                ]
            }

        return _Resource(handler)

    def playlistItems(self):
        def handler(kwargs):
            self.playlist_calls.append(kwargs)
            items = [
                {
                    "snippet": {
                        "resourceId": {"videoId": vid},
                    }
                }
                for vid, _title in self._videos
            ]
            return {"items": items}

        return _Resource(handler)

    def videos(self):
        def handler(kwargs):
            self.videos_calls.append(kwargs)
            wanted = set(kwargs.get("id", "").split(","))
            return {
                "items": [
                    {"id": vid, "snippet": {"title": title}}
                    for vid, title in self._videos
                    if vid in wanted
                ]
            }

        return _Resource(handler)


class FakeAnalyticsService:
    """Mimics youtubeAnalytics.reports().query() with per-video rows."""

    def __init__(self, views_by_video=None, rows=None):
        # views_by_video: {video_id: views} -> rows built per filter chunk.
        self._views = views_by_video or {}
        self._fixed_rows = rows
        self.query_calls = []

    def reports(self):
        service = self

        class _Reports:
            def query(self, **kwargs):
                service.query_calls.append(kwargs)
                return _Callable(_Reports.handler)(**kwargs)

            @staticmethod
            def handler(kwargs):
                if service._fixed_rows is not None:
                    rows = service._fixed_rows
                    headers = [
                        {"name": "day", "columnType": "DIMENSION", "dataType": "STRING"},
                        {"name": "views", "columnType": "METRIC", "dataType": "INTEGER"},
                    ]
                else:
                    filters = kwargs.get("filters", "")
                    ids = []
                    if filters.startswith("video=="):
                        ids = filters[len("video==") :].split(",")
                    rows = [
                        [vid, service._views.get(vid, 0)]
                        for vid in ids
                    ]
                    headers = [
                        {"name": "video", "columnType": "DIMENSION", "dataType": "STRING"},
                        {"name": "views", "columnType": "METRIC", "dataType": "INTEGER"},
                    ]
                return {"columnHeaders": headers, "rows": rows}

        return _Reports()


class FakeClient:
    def __init__(self, data_service, analytics_service):
        self._data = data_service
        self._analytics = analytics_service

    def get_youtube_service(self):
        return self._data

    def get_analytics_service(self):
        return self._analytics


VIDEOS = [("aaa111bbb22", "First Video"), ("ccc333ddd44", "Second Video")]


@pytest.fixture()
def fakes(monkeypatch):
    data = FakeDataService(VIDEOS)
    analytics_svc = FakeAnalyticsService(
        views_by_video={"aaa111bbb22": 100, "ccc333ddd44": 500}
    )
    client = FakeClient(data, analytics_svc)
    monkeypatch.setattr(analytics, "get_api_client", lambda profile=None: client)
    return data, analytics_svc


def test_report_queries_all_uploads_and_maps_titles(fakes):
    data, analytics_svc = fakes
    result = RUNNER.invoke(app, ["analytics", "report"])
    assert result.exit_code == 0, _plain(result.output)
    rows = _output_json(result)
    assert len(rows) == 2
    # Default sort is -views: higher-view video first.
    assert rows[0]["video"] == "ccc333ddd44"
    assert rows[0]["views"] == 500
    assert rows[0]["title"] == "Second Video"
    assert rows[1]["video"] == "aaa111bbb22"
    # The uploads playlist was paged and filters covered both videos.
    assert len(analytics_svc.query_calls) == 1
    call = analytics_svc.query_calls[0]
    assert call["filters"] == "video==aaa111bbb22,ccc333ddd44"
    assert call["ids"] == "channel==MINE"
    assert call["dimensions"] == "video"
    assert len(data.playlist_calls) == 1


def test_report_restricts_to_requested_videos(fakes):
    _data, analytics_svc = fakes
    result = RUNNER.invoke(
        app,
        ["analytics", "report", "--video", "ccc333ddd44", "--video", "aaa111bbb22"],
    )
    assert result.exit_code == 0, _plain(result.output)
    rows = _output_json(result)
    assert {r["video"] for r in rows} == {"aaa111bbb22", "ccc333ddd44"}


def test_report_accepts_video_url(fakes):
    _data, analytics_svc = fakes
    result = RUNNER.invoke(
        app,
        ["analytics", "report", "--video", "https://www.youtube.com/watch?v=aaa111bbb22"],
    )
    assert result.exit_code == 0, _plain(result.output)
    assert analytics_svc.query_calls[0]["filters"] == "video==aaa111bbb22"


def test_report_rejects_invalid_video(fakes):
    result = RUNNER.invoke(app, ["analytics", "report", "--video", "!!!not-a-video!!!"])
    assert result.exit_code == 1
    assert "Not a YouTube video ID or URL" in _plain(result.output)


def test_report_channel_mode_queries_by_day(fakes):
    _data, analytics_svc = fakes
    analytics_svc._fixed_rows = [["2026-09-28", 1200], ["2026-09-29", 900]]
    result = RUNNER.invoke(app, ["analytics", "report", "--channel", "--metrics", "views"])
    assert result.exit_code == 0, _plain(result.output)
    call = analytics_svc.query_calls[0]
    assert call["dimensions"] == "day"
    assert "filters" not in call
    rows = _output_json(result)
    assert rows[0] == {"day": "2026-09-28", "views": 1200}


def test_report_rejects_bad_dates(fakes):
    result = RUNNER.invoke(app, ["analytics", "report", "--start-date", "2026-13-99"])
    assert result.exit_code == 1
    assert "YYYY-MM-DD" in _plain(result.output)

    result = RUNNER.invoke(
        app,
        ["analytics", "report", "--start-date", "2026-09-30", "--end-date", "2026-09-01"],
    )
    assert result.exit_code == 1
    assert "on or before" in _plain(result.output)


def test_report_table_output(fakes):
    result = RUNNER.invoke(app, ["analytics", "report", "--table", "-t"])
    assert result.exit_code == 0, _plain(result.output)
    text = _plain(result.output)
    assert "Second Video" in text
    assert "500" in text


def test_report_filter_and_properties(fakes):
    result = RUNNER.invoke(
        app,
        ["analytics", "report", "--filter", "views:gt:200", "--properties", "title,views"],
    )
    assert result.exit_code == 0, _plain(result.output)
    rows = _output_json(result)
    assert rows == [{"title": "Second Video", "views": 500}]


def test_report_access_not_configured_message(monkeypatch):
    class _Resp:
        status = 403
        reason = "Forbidden"

    def boom(**kwargs):
        raise HttpError(_Resp(), b'{"error":{"errors":[{"reason":"accessNotConfigured"}]}}')

    class _Analytics:
        def reports(self):
            class _R:
                def query(self, **kwargs):
                    return _Callable(lambda kw: boom(**kw))(**kwargs)

            return _R()

    data = FakeDataService(VIDEOS)
    monkeypatch.setattr(
        analytics, "get_api_client", lambda profile=None: FakeClient(data, _Analytics())
    )
    result = RUNNER.invoke(app, ["analytics", "report"])
    assert result.exit_code == 1
    assert "YouTube Analytics API is not enabled" in _plain(result.output)
