"""Per-post penalty decoding against payloads captured from @ata_clipper on 2026-10-06."""
import json
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from tiktok_cli.account_check import PENALTY_PATH, normalize_penalty
from tiktok_cli.client import ClientError, TikTokWebClient
from tiktok_cli.commands import account as account_cmd
from tiktok_cli.main import app

ID = "7692252984792681742"
GONE = "7693639883012705549"
OWNER = {"username": "ata_clipper", "account_id": "7692213003349443597", "profile": "clipper"}
# Verbatim GET /mod/v1/getPenaltyDetails/?vid=7692252984792681742 response.
RESTRICTED = '{"ab_result":"0","appeal_status":0,"extra":{"fatal_item_ids":[],"logid":"2026100621521712E90A816B1376A05BCA","now":1791323537000},"feedback_status":1,"improve_views":0,"log_pb":{"impr_id":"2026100621521712E90A816B1376A05BCA"},"penalties":[{"date":"1790992383","issuer":"FQ","penalty_id":{"id":"0"},"reason_codes":["9"]}],"status_code":0,"status_msg":"","top_penalty_details":{"is_adult_group":false,"penalty_source":0,"penalty_trigger":0,"penalty_type":0}}'
# Verbatim response for an upload Studio accepted that no longer exists.
UNAVAILABLE = '{"log_pb":{"impr_id":"20261006215522550C69C515807E233C59"},"status_code":4,"status_msg":"Server is currently unavailable. Please try again later."}'
ITEM = {"id": ID, "url": f"https://www.tiktok.com/@ata_clipper/video/{ID}",
        "caption": "Steve Aoki pulls a $60 card on UNPACKED 😱 @hardscope #unpacked",
        "posted_at": 1790992233, "status": 102, "visibility": 1, "in_review": False, "metrics": {"views": 7}}


def test_captured_restriction_decodes_to_the_reason_the_phone_app_shows():
    assert normalize_penalty(json.loads(RESTRICTED)) == {
        "eligibility": "restricted",
        "reasons": [{"code": 9, "title": "Unoriginal, low-quality, and QR code content"}],
        "appeal_status": "can_submit", "penalty_type": "NR", "penalized_at": 1790992383,
        "penalty_issuer": "FQ", "penalty_error": None,
    }


def test_captured_unavailable_read_stays_unknown():
    result = normalize_penalty(json.loads(UNAVAILABLE))
    assert result["eligibility"] is None and result["reasons"] == [] and result["appeal_status"] is None
    assert result["penalty_error"] == "status_code 4: Server is currently unavailable. Please try again later."


def test_no_penalties_is_no_penalty_and_carries_no_penalty_type():
    body = json.loads(RESTRICTED)
    body.update(penalties=[], appeal_status=2)
    result = normalize_penalty(body)
    assert result["eligibility"] == "no_penalty" and result["appeal_status"] == "no_penalty"
    assert result["penalty_type"] is None and result["penalized_at"] is None


def test_undecoded_reason_uses_server_title_or_stays_null():
    body = json.loads(RESTRICTED)
    body["penalties"] = [{"reason_codes": ["110", "999"], "penalty_reason_info_list": [{"code": "110", "title": "Server title"}]}]
    body["appeal_status"] = 42
    result = normalize_penalty(body)
    assert result["reasons"] == [{"code": 110, "title": "Server title"}, {"code": 999, "title": None}]
    assert result["appeal_status"] is None


@pytest.mark.parametrize("body", [
    None, [], {}, {"status_code": "0"}, {"status_code": True},
    {"status_code": 0, "penalties": {}}, {"status_code": 0, "penalties": [{}]},
    {"status_code": 0, "penalties": [{"reason_codes": ["x"]}]}, {"status_code": 0, "penalties": ["9"]},
    {"status_code": 0, "penalties": [], "appeal_status": "0"},
])
def test_malformed_read_never_becomes_a_clean_post(body):
    result = normalize_penalty(body)
    assert result["eligibility"] is None and result["penalty_error"] == "malformed penalty response"


class Reader:
    identity = {**OWNER, "observed_at": "OBSERVED", "provenance": "PASSPORT"}

    def __init__(self, pages):
        self.pages, self.page = pages, SimpleNamespace(paths=[])
        self.page.evaluate = self.evaluate

    def read_page(self, cursor):
        return self.pages[cursor]

    def evaluate(self, js, args):
        self.page.paths.append(args)
        return {"status": 200, "statusText": "", "body": RESTRICTED if ID in args["path"] else UNAVAILABLE}


def client(reader):
    web = TikTokWebClient(config=SimpleNamespace(), max_retries=0)

    @contextmanager
    def session(username, expected_account_id):
        assert (username, expected_account_id) == (OWNER["username"], OWNER["account_id"])
        yield reader
    web._studio_session = session
    return web


def test_check_reports_restricted_post_and_upload_missing_from_complete_feed():
    reader = Reader({0: ([ITEM], False, 1)})
    result = client(reader).check_account("ata_clipper", expected_account_id=OWNER["account_id"], video_ids=[GONE])
    assert result["account"] == {**OWNER, "standing": None, "standing_note": result["account"]["standing_note"]}
    assert result["feed_complete"] is True
    assert result["summary"] == {"posts": 2, "restricted": 1, "no_penalty": 0, "unknown": 1, "missing_from_feed": 1}
    live, gone = result["posts"]
    assert live["id"] == ID and live["in_studio_feed"] is True and live["caption"] == ITEM["caption"]
    assert live["posted_at"] == 1790992233 and live["eligibility"] == "restricted"
    assert live["reasons"][0]["title"] == "Unoriginal, low-quality, and QR code content"
    assert "metrics" not in live
    assert gone == {"id": GONE, "in_studio_feed": False, "url": None, "caption": None, "posted_at": None,
                    "status": None, "visibility": None, "in_review": None, "eligibility": None, "reasons": [],
                    "appeal_status": None, "penalty_type": None, "penalized_at": None, "penalty_issuer": None,
                    "penalty_error": "status_code 4: Server is currently unavailable. Please try again later."}
    assert reader.page.paths == [{"path": f"{PENALTY_PATH}?aid=1988&vid={value}", "method": "GET", "csrf": False} for value in (ID, GONE)]


def test_bounded_scan_never_calls_an_unseen_id_missing():
    other = {**ITEM, "id": "7000000000000000002"}
    pages = {cursor: ([{**other, "id": str(7000000000000000002 + cursor)}], True, cursor + 1) for cursor in range(20)}
    result = client(Reader(pages)).check_account("ata_clipper", limit=1, expected_account_id=OWNER["account_id"], video_ids=[GONE])
    assert result["feed_complete"] is False and len(result["posts"]) == 2
    assert result["posts"][1]["in_studio_feed"] is None and result["summary"]["missing_from_feed"] == 0


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": 1001}, {"video_ids": ["abc"]}, {"video_ids": ["0"]}])
def test_invalid_arguments_fail_before_any_read(kwargs):
    with pytest.raises(ClientError):
        client(Reader({})).check_account("ata_clipper", expected_account_id=OWNER["account_id"], **kwargs)


def test_command_prints_json_and_table(monkeypatch):
    reader = Reader({0: ([ITEM], False, 1)})
    web = client(reader)
    web.close = lambda: None
    monkeypatch.setattr(account_cmd, "TikTokWebClient", lambda: web)
    args = ["account", "check", "--username", "ata_clipper", "--expected-account-id", OWNER["account_id"]]
    result = CliRunner().invoke(account_cmd.app, args[1:])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["posts"][0]["eligibility"] == "restricted"
    table = CliRunner().invoke(account_cmd.app, args[1:] + ["--table"])
    assert table.exit_code == 0 and "eligibil" in table.output and "7692" in table.output
    assert "check" in CliRunner().invoke(app, ["account", "--help"]).output
