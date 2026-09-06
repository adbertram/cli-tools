"""Read-only TTV task-detail contract tests."""

import pytest

from cli_tools_shared.auth import AuthResult

from microworkers_cli.client import (
    ClientError,
    MicroworkersClient,
    TTV_ALLOCATION_STATE_JS,
    TTV_DETAIL_JS,
)
from microworkers_cli.parsers import parse_ttv_detail_target


TTV_TASK = "https://ttv.microworkers.com/dotask/info/d472ac0550fb_HG"


class _Visible:
    def __init__(self, page=None):
        self.page = page

    @property
    def first(self):
        return self

    def is_visible(self, timeout=None):
        assert timeout in (None, 3000)
        return True

    def count(self):
        return 1

    def click(self):
        self.page.clicks += 1


class _Page:
    url = TTV_TASK

    def __init__(self):
        self.evaluated = []
        self.clicks = 0

    def wait_for_timeout(self, _ms):
        pass

    def locator(self, selector):
        assert selector in {
            ".vn-bootstrap .ttv-task-data",
            'form[action="/dotask/allocateposition"] button[type="submit"]',
        }
        return _Visible(self)

    def wait_for_network_idle(self, *, timeout, idle_ms):
        assert timeout == 15.0 and idle_ms == 500
        return True

    def evaluate(self, script, arg=None):
        self.evaluated.append(script)
        if script == TTV_ALLOCATION_STATE_JS:
            assert arg == {"campaign_id": "d472ac0550fb_HG"}
            return {
                "url": "https://ttv.microworkers.com/dotask/run/d472ac0550fb_HG",
                "allocation_form_count": 0,
                "task_form_count": 1,
                "task_form_action": "https://ttv.microworkers.com/dotask/save",
                "instruction_panel_count": 1,
            }
        return {
            "title": "TTV task",
            "work_summary": ["Work done: 3/5", "You will earn: $1.00000"],
            "employer": "Member_1326556503",
            "employer_url": "https://www.microworkers.com/userinfo.php?Id=b45d755a",
            "employer_details": ["Tasks will be rated within 7 days"],
            "country_notice": None,
            "instructions_and_proof": ["Do the work", "Important: one task only"],
            "apply_action": "https://ttv.microworkers.com/dotask/allocateposition",
            "apply_method": "post",
            "apply_id_field": "d472ac0550fb_HG",
            "apply_hidden_fields": [
                {"name": "CampaignId", "value": "d472ac0550fb_HG"}
            ],
            "apply_submit_label": "Accept and Start",
            "proof_file_fields": [],
            "proof_text_fields": [],
        }


class _Browser:
    def __init__(self, page):
        self.page = page

    def ensure_fresh_session(self):
        return AuthResult(authenticated=True, live_check=True, refreshed=False)

    def get_page(self, url):
        assert url == TTV_TASK
        return self.page

    def close(self):
        pass


def _client(page):
    client = object.__new__(MicroworkersClient)
    client.config = None
    client._browser = _Browser(page)
    client._refresh_checked = False
    return client


def test_parse_ttv_detail_target_accepts_exact_task_url():
    assert parse_ttv_detail_target(TTV_TASK) == "d472ac0550fb_HG"
    assert parse_ttv_detail_target(
        "https://ttv.microworkers.com/dotask/info/aa1d25908d0b_B"
    ) == "aa1d25908d0b_B"


@pytest.mark.parametrize(
    "url",
    [
        "http://ttv.microworkers.com/dotask/info/d472ac0550fb_HG",
        "https://evil.example/dotask/info/d472ac0550fb_HG",
        "https://ttv.microworkers.com.evil.example/dotask/info/d472ac0550fb_HG",
        "https://ttv.microworkers.com/dotask/info/d472ac0550fb_HG?next=evil",
        "https://ttv.microworkers.com/dotask/info/d472ac0550fb_HG#fragment",
        "https://ttv.microworkers.com/dotask/info/not-a-campaign",
        "https://ttv.microworkers.com/dotask/info/aa1d25908d0b_X",
    ],
)
def test_parse_ttv_detail_target_rejects_non_exact_urls(url):
    with pytest.raises(ValueError):
        parse_ttv_detail_target(url)


def test_get_ttv_task_reads_detail_and_exact_apply_metadata_without_mutation():
    page = _Page()

    result = _client(page).get_task(TTV_TASK)

    assert page.evaluated == [TTV_DETAIL_JS]
    assert result["provider"] == "ttv"
    assert result["title"] == "TTV task"
    assert result["instructions_and_proof"] == [
        "Do the work",
        "Important: one task only",
    ]
    assert result["apply_action"] == (
        "https://ttv.microworkers.com/dotask/allocateposition"
    )
    assert result["apply_method"] == "post"
    assert result["apply_hidden_fields"] == [
        {"name": "CampaignId", "value": "d472ac0550fb_HG"}
    ]
    assert result["apply_submit_label"] == "Accept and Start"
    assert result["proof_file_fields"] == []
    assert result["proof_text_fields"] == []


def test_get_ttv_task_rejects_unexpected_apply_metadata():
    page = _Page()
    original_evaluate = page.evaluate

    def evaluate(script):
        result = original_evaluate(script)
        result["apply_method"] = "get"
        return result

    page.evaluate = evaluate

    with pytest.raises(ClientError, match="unexpected apply form metadata"):
        _client(page).get_task(TTV_TASK)


def test_ttv_apply_dry_run_preflights_without_clicking():
    page = _Page()

    result = _client(page).apply_task(TTV_TASK)

    assert result["state"] == "ready_to_allocate"
    assert result["allocated"] is False
    assert result["mutation_attempted"] is False
    assert page.clicks == 0


def test_ttv_confirm_clicks_once_and_requires_campaign_bound_postflight():
    page = _Page()

    result = _client(page).apply_task(TTV_TASK, confirm=True)

    assert result["state"] == "allocated"
    assert result["allocated"] is True
    assert result["submitted"] is False
    assert result["post_verified"] is True
    assert page.clicks == 1


def test_ttv_confirm_fails_ambiguous_after_one_click_without_retry():
    page = _Page()
    original_evaluate = page.evaluate

    def evaluate(script, arg=None):
        result = original_evaluate(script, arg)
        if script == TTV_ALLOCATION_STATE_JS:
            result["task_form_count"] = 0
        return result

    page.evaluate = evaluate

    with pytest.raises(ClientError, match="outcome is ambiguous"):
        _client(page).apply_task(TTV_TASK, confirm=True)

    assert page.clicks == 1


def test_ttv_apply_rejects_proof_options_without_navigation_or_click():
    page = _Page()

    with pytest.raises(ClientError, match="proof-text"):
        _client(page).apply_task(TTV_TASK, proof_text="not accepted")

    assert page.evaluated == []
    assert page.clicks == 0


def test_ttv_work_fails_before_allocation_and_saves_visible_detail(tmp_path):
    page = _Page()

    with pytest.raises(ClientError, match="requires allocation first"):
        _client(page).work_task(TTV_TASK, str(tmp_path))

    assert page.clicks == 0
    assert (tmp_path / "d472ac0550fb_HG" / "task-detail.json").is_file()
