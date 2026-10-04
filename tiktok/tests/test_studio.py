"""Observed Studio schema boundaries without remote browser writes."""
import json

import pytest

from tiktok_cli.studio import StudioContractError, normalize_item, validate_page

ID = "7692252984792681742"
OWNER = {"username": "ata_clipper", "account_id": "7692213003349443597", "profile": "clipper"}


def raw_item():
    return {"item_id": ID, "desc": "Observed caption", "create_time": "1790992233", "post_time": "1790992233",
            "play_count": "5", "like_count": "0", "comment_count": "0", "share_count": "0", "favorite_count": "0",
            "visibility": 1, "status": 102, "in_review": False, "is_pinned": False,
            "play_addr": ["DO-NOT-OUTPUT"], "download_info": {"secret": "DO-NOT-OUTPUT"}}


def page():
    return {"status_code": 0, "item_list": [raw_item()], "has_more": False, "cursor": 50,
            "is_limited": False, "extra": {"now": 1791116180000, "fatal_item_ids": []}}


def test_observed_item_preserves_ids_and_actual_zero_counts_without_media_secrets():
    result = normalize_item(raw_item(), OWNER, "2026-10-04T12:00:00+00:00", 1791116180000)
    assert result["id"] == ID and result["account_id"] == OWNER["account_id"]
    assert result["metrics"] == {"views": 5, "likes": 0, "comments": 0, "shares": 0, "favorites": 0}
    assert result["server_timestamp_ms"] == 1791116180000
    assert result["url"] == f"https://www.tiktok.com/@ata_clipper/video/{ID}"
    assert "DO-NOT-OUTPUT" not in json.dumps(result)


def test_missing_measurements_are_unknown():
    raw = raw_item()
    del raw["play_count"]
    raw["like_count"] = None
    result = normalize_item(raw, OWNER, "OBSERVED", None)
    assert result["metrics"]["views"] is None and result["metrics"]["likes"] is None
    assert result["server_timestamp_ms"] is None
    assert "revenue" not in result["metrics"]


@pytest.mark.parametrize("value", [True, -1, 1, 1.0, "-1", "1.0", "NaN", "inf", "", "1" * 65])
def test_invalid_counter_never_becomes_zero_or_float(value):
    raw = raw_item()
    raw["play_count"] = value
    with pytest.raises(StudioContractError):
        normalize_item(raw, OWNER, "OBSERVED", None)


@pytest.mark.parametrize("value", [True, 7692252984792681742, "0", "", "-1", "1.0"])
def test_video_id_requires_exact_positive_string(value):
    raw = raw_item()
    raw["item_id"] = value
    with pytest.raises(StudioContractError):
        normalize_item(raw, OWNER, "OBSERVED", None)


@pytest.mark.parametrize("change", [
    {"status_code": True}, {"status_code": "0"}, {"status_code": 1}, {"status_code": None},
    {"item_list": None}, {"item_list": {}}, {"has_more": None}, {"has_more": 0},
    {"cursor": True}, {"cursor": "50"}, {"cursor": -1}, {"is_limited": True}, {"is_limited": None},
    {"extra": []}, {"extra": {"now": True}}, {"extra": {"fatal_item_ids": [ID]}},
])
def test_malformed_or_limited_feed_cannot_establish_absence(change):
    payload = page()
    payload.update(change)
    with pytest.raises(StudioContractError):
        validate_page(payload)


def test_explicit_terminal_pagination_and_server_timestamp():
    payload = page()
    items, more, cursor, measured = validate_page(payload)
    assert items[0]["item_id"] == ID and more is False and cursor == 50 and measured == 1791116180000


@pytest.mark.parametrize("key", ["has_more", "item_list", "cursor", "is_limited", "status_code"])
def test_required_pagination_fields_cannot_be_missing(key):
    payload = page()
    del payload[key]
    with pytest.raises(StudioContractError):
        validate_page(payload)


class FakePage:
    def __init__(self, responses, ready=True):
        self.responses = list(responses)
        self.ready = ready
        self.requests = []
        self.cleaned = False
        self.clicked = False
    def evaluate(self, script, value=None):
        from tiktok_cli.studio import CAPTURE_JS, READY_JS, FETCH_JS, CLEANUP_JS
        if script == CAPTURE_JS:
            return True
        if script == READY_JS:
            return self.ready
        if script == CLEANUP_JS:
            self.cleaned = True
            return True
        assert script == FETCH_JS
        self.requests.append(value)
        response = self.responses.pop(0)
        return {"status": 200, "body": json.dumps(response)} if isinstance(response, dict) else response
    def get_by_role(self, role, **kwargs):
        assert (role, kwargs) == ("button", {"name": "Views", "exact": True})
        return self
    def count(self):
        return 1
    def click(self):
        self.clicked = True
    def wait_for_timeout(self, duration):
        assert duration == 250


def instance(fake):
    from types import SimpleNamespace
    from tiktok_cli.client import TikTokWebClient
    browser = SimpleNamespace(get_page=lambda url: fake, close=lambda: None)
    client = TikTokWebClient(config=SimpleNamespace(get_browser=lambda: browser), max_retries=0)
    guards = []
    def identity(**kwargs):
        guards.append(kwargs)
        assert kwargs["expected_username"] == OWNER["username"]
        if kwargs.get("expected_account_id") not in (None, OWNER["account_id"]):
            from tiktok_cli.client import ClientError
            raise ClientError("identity mismatch")
        return OWNER.copy()
    client.get_account = identity
    client.guards = guards
    return client


def test_studio_rechecks_same_numeric_owner_and_always_removes_capture():
    fake = FakePage([page()])
    client = instance(fake)
    result = client.list_studio_videos("ata_clipper", 1, OWNER["account_id"])
    assert result[0]["metrics"]["views"] == 5
    assert fake.clicked and fake.cleaned
    assert client.guards == [{"expected_username": "ata_clipper", "expected_account_id": OWNER["account_id"]}] * 2


def test_wrong_owner_id_fails_before_studio_action():
    from tiktok_cli.client import ClientError
    fake = FakePage([])
    with pytest.raises(ClientError, match="identity mismatch"):
        instance(fake).list_studio_videos("ata_clipper", 1, "1")
    assert not fake.clicked and not fake.requests


@pytest.mark.parametrize("change", [{"has_more": None}, {"is_limited": True}, {"cursor": "50"}])
def test_malformed_runtime_feed_never_returns_empty_or_not_found(change):
    from tiktok_cli.client import ClientError
    value = page()
    value.update(change)
    fake = FakePage([value])
    with pytest.raises(ClientError, match="inconclusive"):
        instance(fake).get_studio_video("ata_clipper", "2")
    assert fake.cleaned


def test_advancing_pagination_uses_only_server_cursor():
    first = page()
    first.update(has_more=True, cursor=50)
    second = page()
    second["item_list"][0]["item_id"] = "7692252984792681743"
    fake = FakePage([first, second])
    assert len(instance(fake).list_studio_videos("ata_clipper", 2)) == 2
    assert [call["cursor"] for call in fake.requests] == [0, 50]


@pytest.mark.parametrize("kind", ["repeated_cursor", "duplicate_video", "empty_nonterminal"])
def test_pagination_failures_are_inconclusive(kind):
    from tiktok_cli.client import ClientError
    first = page()
    first.update(has_more=True, cursor=50)
    second = page()
    if kind == "repeated_cursor":
        second.update(has_more=True, cursor=50)
        second["item_list"][0]["item_id"] = "2"
    if kind == "empty_nonterminal":
        second.update(has_more=True, cursor=100, item_list=[])
    fake = FakePage([first, second])
    with pytest.raises(ClientError, match="inconclusive"):
        instance(fake).list_studio_videos("ata_clipper", 10)
    assert fake.cleaned


def test_explicit_complete_feed_missing_id_is_distinct_from_bounded_inconclusive():
    from tiktok_cli.client import ClientError
    fake = FakePage([page()])
    with pytest.raises(ClientError, match="studio_video_not_found"):
        instance(fake).get_studio_video("ata_clipper", "2")
    assert fake.cleaned


@pytest.mark.parametrize("response", [{"status": 403, "body": "SECRET"}, {"status": 200, "body": "{bad SECRET"}, {"status": 200, "body": None}])
def test_transport_errors_are_sanitized_and_cleanup_still_runs(response):
    from tiktok_cli.client import ClientError
    fake = FakePage([])
    original = fake.evaluate
    def evaluate(script, value=None):
        from tiktok_cli.studio import FETCH_JS
        return response if script == FETCH_JS else original(script, value)
    fake.evaluate = evaluate
    with pytest.raises(ClientError) as error:
        instance(fake).list_studio_videos("ata_clipper", 1)
    assert "SECRET" not in str(error.value) and fake.cleaned


def test_native_read_timeout_is_inconclusive_and_cleanup_runs():
    from tiktok_cli.client import ClientError
    fake = FakePage([], ready=False)
    with pytest.raises(ClientError, match="unavailable.*inconclusive"):
        instance(fake).list_studio_videos("ata_clipper", 1)
    assert fake.cleaned


def test_identity_change_after_read_returns_no_record_and_cleans_capture():
    from tiktok_cli.client import ClientError
    fake = FakePage([page()])
    client = instance(fake)
    original = client.get_account
    calls = []
    def changed(**kwargs):
        calls.append(kwargs)
        if len(calls) > 1:
            raise ClientError("identity mismatch")
        return original(**kwargs)
    client.get_account = changed
    with pytest.raises(ClientError, match="identity mismatch"):
        client.list_studio_videos("ata_clipper", 1)
    assert fake.cleaned


def test_full_bound_without_terminal_signal_does_not_claim_absence():
    from tiktok_cli.client import ClientError
    responses = []
    for index in range(20):
        payload = page()
        payload.update(has_more=True, cursor=(index + 1) * 50)
        payload["item_list"][0]["item_id"] = str(index + 1)
        responses.append(payload)
    fake = FakePage(responses)
    with pytest.raises(ClientError, match="studio_lookup_inconclusive"):
        instance(fake).get_studio_video("ata_clipper", ID)
    assert len(fake.requests) == 20 and fake.cleaned


@pytest.mark.parametrize("body", ['{"status_code":0,"status_code":0}', '{"status_code":NaN}', 'x'*8000001])
def test_invalid_json_cannot_be_coerced_to_success(body):
    from tiktok_cli.client import ClientError
    from tiktok_cli.studio import FETCH_JS
    fake = FakePage([])
    original = fake.evaluate
    fake.evaluate = lambda script,value=None: {"status": 200, "body": body} if script == FETCH_JS else original(script,value)
    with pytest.raises(ClientError):
        instance(fake).list_studio_videos("ata_clipper", 1)
    assert fake.cleaned


@pytest.mark.parametrize("action", ["list", "get", "metrics"])
def test_cli_studio_dispatch_and_close(monkeypatch, action):
    from typer.testing import CliRunner
    from tiktok_cli.commands import videos
    from tiktok_cli.main import app
    closed = []
    calls = []
    record = normalize_item(raw_item(), OWNER, "2026-10-04T12:00:00+00:00", None)
    class Client:
        def list_studio_videos(self, username, **kwargs):
            calls.append((username, kwargs))
            return [record]
        def get_studio_video(self, username, video_id, **kwargs):
            calls.append((username, video_id, kwargs))
            return record
        def close(self):
            closed.append(True)
    monkeypatch.setattr(videos, "get_web_client", Client)
    argv = ["videos", action]
    if action != "list":
        argv.append(ID)
    argv += ["--profile", "clipper", "--username", "ata_clipper", "--expected-account-id", OWNER["account_id"]]
    if action != "metrics":
        argv.append("--studio")
    result = CliRunner().invoke(app, argv)
    assert result.exit_code == 0, result.output
    assert closed == [True] and calls[0][0] == "ata_clipper"
    output = json.loads(result.stdout)
    if action == "metrics":
        assert output["views"] == 5 and output["profile"] == "clipper"
    else:
        assert (output[0] if action == "list" else output)["metrics"]["views"] == 5


@pytest.mark.parametrize("value", [None, 0, "", {}, False])
def test_falsy_malformed_fatal_items_cannot_establish_absence(value):
    payload = page()
    payload["extra"]["fatal_item_ids"] = value
    with pytest.raises(StudioContractError, match="inconclusive"):
        validate_page(payload)


@pytest.mark.parametrize("text", ['{"value":1e999}', '{"value":NaN}', '{"value":Infinity}', '{"value":1,"value":2}'])
def test_strict_json_nonfinite_and_duplicate_unknown_fields_fail(text):
    from tiktok_cli.studio import parse_response
    with pytest.raises(StudioContractError):
        parse_response(text)


def test_utf8_byte_payload_limit_is_enforced_even_with_valid_json():
    from tiktok_cli.studio import parse_response, MAX_RESPONSE_BYTES
    text = json.dumps({"caption": "é" * (MAX_RESPONSE_BYTES // 2)}, ensure_ascii=False)
    assert len(text) < MAX_RESPONSE_BYTES
    with pytest.raises(StudioContractError, match="bounded"):
        parse_response(text)
