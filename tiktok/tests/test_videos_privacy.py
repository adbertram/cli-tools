"""`videos privacy`: request shape, validation, and the Studio readback gate.

The Studio reads are stubbed with records shaped like normalize_item output;
a fake page records the in-page modify/visibility request.
"""
import json

import pytest
from typer.testing import CliRunner

from tiktok_cli.client import ClientError, TikTokWebClient
from tiktok_cli.commands import videos as videos_cmd

ID = "7696592655307787533"
ACCOUNT = "7692213003349443597"


def record(visibility):
    return {"id": ID, "url": f"https://www.tiktok.com/@ata_clipper/video/{ID}", "author": "ata_clipper",
            "account_id": ACCOUNT, "profile": "clipper", "visibility": visibility,
            "observed_at": "2026-10-14T12:00:00+00:00",
            "provenance": "https://www.tiktok.com/tiktok/creator/manage/item_list/v1/"}


class FakePage:
    def __init__(self, body):
        self.body, self.requests = body, []

    def evaluate(self, js, arg=None):
        self.requests.append(arg)
        return {"status": 200, "statusText": "", "body": json.dumps(self.body)}


class FakeBrowser:
    def __init__(self, page):
        self.page, self.urls = page, []

    def get_page(self, url):
        self.urls.append(url)
        return self.page

    def close(self):
        pass


class FakeConfig:
    base_url = "https://www.tiktok.com"

    def __init__(self, page):
        self.browser = FakeBrowser(page)

    def get_browser(self):
        return self.browser


def client_with(readbacks, body=None):
    page = FakePage({"status_code": 0} if body is None else body)
    client = TikTokWebClient(config=FakeConfig(page), max_retries=0)
    reads = []
    def get_studio_video(username, video_id, expected_account_id=None):
        reads.append((username, video_id, expected_account_id))
        return record(readbacks.pop(0))
    client.get_studio_video = get_studio_video
    return client, page, reads


def test_private_post_set_public_posts_observed_request_and_confirms_readback():
    client, page, reads = client_with([2, 1])
    result = client.set_video_privacy("ata_clipper", ID, "public", expected_account_id=ACCOUNT)
    assert page.requests == [{"path": f"/api/aweme/modify/visibility/?aid=1988&aweme_id={ID}&type=1",
                              "method": "POST", "csrf": True}]
    assert client.config.browser.urls == [f"https://www.tiktok.com/@ata_clipper/video/{ID}"]
    assert reads == [("ata_clipper", ID, ACCOUNT)] * 2
    assert result["requested"] == "public" and result["requested_visibility"] == 1
    assert (result["previous_visibility"], result["visibility"], result["changed"]) == (2, 1, True)
    assert result["observed_at"] == "2026-10-14T12:00:00+00:00"
    assert result["endpoint"] == "https://www.tiktok.com/api/aweme/modify/visibility/"


def test_same_value_still_sends_request_and_reports_unchanged():
    client, page, _ = client_with([1, 1])
    result = client.set_video_privacy("ata_clipper", ID, "public", expected_account_id=ACCOUNT)
    assert len(page.requests) == 1 and result["changed"] is False and result["visibility"] == 1


@pytest.mark.parametrize("setting,code", [("public", 1), ("private", 2), ("friends", 3)])
def test_settings_map_to_observed_type_codes(setting, code):
    client, page, _ = client_with([1, code])
    assert client.set_video_privacy("ata_clipper", ID, setting, expected_account_id=ACCOUNT)["visibility"] == code
    assert page.requests[0]["path"].endswith(f"&type={code}")


@pytest.mark.parametrize("observed", [2, None])
def test_unconfirmed_readback_fails_instead_of_reporting_success(observed):
    client, _, _ = client_with([2, observed])
    with pytest.raises(ClientError, match="privacy_unconfirmed") as error:
        client.set_video_privacy("ata_clipper", ID, "public", expected_account_id=ACCOUNT)
    assert error.value.code == "privacy_unconfirmed"


def test_provider_rejection_fails_without_claiming_a_readback():
    client, _, reads = client_with([2, 1], body={"status_code": 8, "status_msg": "Login expired"})
    with pytest.raises(ClientError, match="status code 8"):
        client.set_video_privacy("ata_clipper", ID, "public", expected_account_id=ACCOUNT)
    assert len(reads) == 1


@pytest.mark.parametrize("setting,account", [("everyone", ACCOUNT), ("PUBLIC", ACCOUNT), ("public", None)])
def test_invalid_input_sends_nothing(setting, account):
    client, page, reads = client_with([1, 1])
    with pytest.raises(ClientError):
        client.set_video_privacy("ata_clipper", ID, setting, expected_account_id=account)
    assert page.requests == [] and reads == []


class FakeWebClient:
    def __init__(self, error=None):
        self.error, self.calls, self.closed = error, [], False

    def set_video_privacy(self, username, video_id, setting, *, expected_account_id):
        self.calls.append((username, video_id, setting, expected_account_id))
        if self.error:
            raise self.error
        return {"id": video_id, "requested": setting, "previous_visibility": 2, "visibility": 1, "changed": True}

    def close(self):
        self.closed = True


def invoke(monkeypatch, fake, extra=()):
    monkeypatch.setattr(videos_cmd, "get_web_client", lambda: fake)
    argv = ["privacy", ID, "--to", "public", "--username", "ata_clipper", *extra]
    return CliRunner().invoke(videos_cmd.app, argv)


def test_command_outputs_json_and_closes(monkeypatch):
    fake = FakeWebClient()
    result = invoke(monkeypatch, fake, ["--expected-account-id", ACCOUNT])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["visibility"] == 1
    assert fake.calls == [("ata_clipper", ID, "public", ACCOUNT)] and fake.closed


def test_command_exits_nonzero_on_unconfirmed_readback(monkeypatch):
    fake = FakeWebClient(ClientError("privacy_unconfirmed: readback shows visibility 2", code="privacy_unconfirmed"))
    result = invoke(monkeypatch, fake, ["--expected-account-id", ACCOUNT])
    assert result.exit_code == 1 and result.stdout == "" and fake.closed
    assert "privacy_unconfirmed" in result.output


def test_command_requires_expected_account_id(monkeypatch):
    fake = FakeWebClient()
    result = invoke(monkeypatch, fake)
    assert result.exit_code == 2 and fake.calls == []
