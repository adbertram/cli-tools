"""Contract tests for the Microworkers proof-submission boundary."""

import pytest

from cli_tools_shared.auth import AuthResult

from microworkers_cli.client import (
    APPLY_STATE_JS,
    DETAIL_JS,
    ClientError,
    MicroworkersClient,
)
from microworkers_cli.parsers import parse_apply_target


BASIC_TASK = "https://www.microworkers.com/jobs_details.php?Id=a46464q2c4e4k5d494347474"
BASIC_ACTION = "https://www.microworkers.com/jobs_i_did_it.php"
BASIC_ALREADY_TAKEN = "https://www.microworkers.com/jobs_user_already_took.php"
HG_TASK = "https://www.microworkers.com/hm_jobs_details.php?Id=22d858642cca"
HG_ACTION = "https://www.microworkers.com/hm_jobs_i_did_it.php"


def _state(
    *,
    url=BASIC_TASK,
    action=BASIC_ACTION,
    hidden_id="a46464q2c4e4k5d494347474",
    already_submitted=False,
    form_count=1,
):
    return {
        "url": url,
        "form_count": form_count,
        "action": action if form_count == 1 else None,
        "method": "post" if form_count == 1 else None,
        "hidden_id_count": 1 if form_count == 1 else 0,
        "hidden_id": hidden_id if form_count == 1 else None,
        "submit_count": 1 if form_count == 1 else 0,
        "already_submitted": already_submitted,
    }


def _detail(*, file_fields=None, text_fields=None):
    return {
        "title": "Exact test task",
        "work_summary": [],
        "employer": "Employer",
        "employer_url": None,
        "employer_details": [],
        "country_notice": None,
        "instructions_and_proof": [],
        "apply_action": BASIC_ACTION,
        "apply_id_field": "a46464q2c4e4k5d494347474",
        "proof_file_fields": file_fields or [],
        "proof_text_fields": text_fields or [],
    }


class _Submit:
    def __init__(self, page):
        self.page = page

    @property
    def first(self):
        return self

    def count(self):
        return 1

    def is_visible(self):
        return True

    def click(self):
        self.page.clicks += 1
        if self.page.click_error:
            raise self.page.click_error


class _Page:
    def __init__(self, states, detail=None, *, network_idle=True, click_error=None):
        self.states = list(states)
        self.detail = detail or _detail()
        self.network_idle = network_idle
        self.click_error = click_error
        self.clicks = 0
        self.goto_calls = []
        self.fills = []
        self.uploads = []

    def wait_for_timeout(self, _ms):
        pass

    def wait_for_network_idle(self, *, timeout, idle_ms):
        assert timeout == 15.0
        assert idle_ms == 500
        return self.network_idle

    def evaluate(self, script):
        if script == APPLY_STATE_JS:
            return self.states.pop(0)
        if script == DETAIL_JS:
            return dict(self.detail)
        return None

    def fill(self, selector, value):
        self.fills.append((selector, value))

    def set_input_files(self, selector, path):
        self.uploads.append((selector, path))

    def locator(self, _selector):
        return _Submit(self)

    def goto(self, url):
        self.goto_calls.append(url)


class _Browser:
    def __init__(self, page):
        self.page = page
        self.page_urls = []
        self.close_calls = 0

    def ensure_fresh_session(self):
        return AuthResult(authenticated=True, live_check=True, refreshed=False)

    def get_page(self, url):
        self.page_urls.append(url)
        return self.page

    def close(self):
        self.close_calls += 1


def _client(page):
    client = object.__new__(MicroworkersClient)
    client.config = None
    client._browser = _Browser(page)
    client._refresh_checked = False
    return client


def test_parse_apply_target_binds_basic_and_hire_group_actions():
    assert parse_apply_target(BASIC_TASK) == (
        "microworkers",
        "a46464q2c4e4k5d494347474",
        BASIC_ACTION,
    )
    assert parse_apply_target(HG_TASK) == ("hire_group", "22d858642cca", HG_ACTION)


@pytest.mark.parametrize(
    "url",
    [
        "http://www.microworkers.com/jobs_details.php?Id=abc",
        "https://evil.example/jobs_details.php?Id=abc",
        "https://www.microworkers.com.evil.example/jobs_details.php?Id=abc",
        "https://www.microworkers.com/jobs_details.php",
        "https://www.microworkers.com/jobs_details.php?Id=abc&Id=def",
        "https://www.microworkers.com/jobs_details.php?Id=abc&next=evil",
        "https://www.microworkers.com/jobs_details.php?Id=abc#fragment",
        "https://www.microworkers.com/worker.php?Id=abc",
    ],
)
def test_parse_apply_target_rejects_non_exact_mutation_targets(url):
    with pytest.raises(ValueError):
        parse_apply_target(url)


def test_dry_run_preflights_exact_task_without_mutation():
    page = _Page([_state()], detail=_detail(text_fields=["Proof_text"]))

    result = _client(page).apply_task(BASIC_TASK, proof_text="proof")

    assert result["state"] == "ready"
    assert result["submitted"] is False
    assert result["mutation_attempted"] is False
    assert result["post_verified"] is False
    assert page.clicks == 0
    assert page.fills == []


def test_already_submitted_is_idempotent_and_does_not_mutate():
    page = _Page([_state(already_submitted=True, form_count=0)])

    result = _client(page).apply_task(BASIC_TASK, confirm=True)

    assert result["state"] == "already_submitted"
    assert result["submitted"] is True
    assert result["mutation_attempted"] is False
    assert result["post_verified"] is True
    assert page.clicks == 0


def test_redirected_already_submitted_is_idempotent_and_does_not_mutate():
    page = _Page(
        [_state(url=BASIC_ALREADY_TAKEN, already_submitted=True, form_count=0)]
    )

    result = _client(page).apply_task(BASIC_TASK, confirm=True)

    assert result["state"] == "already_submitted"
    assert result["submitted"] is True
    assert result["mutation_attempted"] is False
    assert result["post_verified"] is True
    assert page.clicks == 0


def test_apply_state_recognizes_live_already_submitted_wording():
    assert "sorry but you already submitted this task." in APPLY_STATE_JS.lower()


@pytest.mark.parametrize(
    ("change", "field"),
    [
        ({"form_count": 2}, "form_count"),
        ({"action": HG_ACTION}, "action"),
        ({"method": "get"}, "method"),
        ({"hidden_id": "different"}, "hidden_id"),
        ({"submit_count": 2}, "submit_count"),
    ],
)
def test_preflight_mismatch_fails_before_mutation(change, field):
    state = _state()
    state.update(change)
    page = _Page([state])

    with pytest.raises(ClientError, match=field):
        _client(page).apply_task(BASIC_TASK, confirm=True)

    assert page.clicks == 0


def test_preflight_redirect_to_different_task_fails_before_mutation():
    page = _Page([_state(url=HG_TASK, action=HG_ACTION, hidden_id="22d858642cca")])

    with pytest.raises(ClientError, match="identity does not match"):
        _client(page).apply_task(BASIC_TASK, confirm=True)

    assert page.clicks == 0


def test_confirm_clicks_once_then_requires_authoritative_exact_task_marker():
    page = _Page([_state(), _state(already_submitted=True, form_count=0)])

    result = _client(page).apply_task(BASIC_TASK, proof_text="proof", confirm=True)

    assert result["state"] == "submitted"
    assert result["submitted"] is True
    assert result["mutation_attempted"] is True
    assert result["post_verified"] is True
    assert page.clicks == 1
    assert page.goto_calls == [BASIC_TASK]


def test_confirm_accepts_authoritative_already_taken_redirect():
    page = _Page(
        [
            _state(),
            _state(url=BASIC_ALREADY_TAKEN, already_submitted=True, form_count=0),
        ]
    )

    result = _client(page).apply_task(BASIC_TASK, proof_text="proof", confirm=True)

    assert result["state"] == "submitted"
    assert result["submitted"] is True
    assert result["mutation_attempted"] is True
    assert result["post_verified"] is True
    assert page.clicks == 1
    assert page.goto_calls == [BASIC_TASK]


def test_post_marker_on_different_task_does_not_verify_submission():
    wrong_task_marker = _state(
        url=HG_TASK,
        action=HG_ACTION,
        hidden_id="22d858642cca",
        already_submitted=True,
        form_count=0,
    )
    page = _Page([_state(), wrong_task_marker])

    with pytest.raises(ClientError, match="Do not retry automatically"):
        _client(page).apply_task(BASIC_TASK, confirm=True)

    assert page.clicks == 1


def test_network_timeout_after_click_is_ambiguous_without_second_click():
    page = _Page([_state()], network_idle=False)

    with pytest.raises(ClientError, match="did not become idle"):
        _client(page).apply_task(BASIC_TASK, confirm=True)

    assert page.clicks == 1
    assert page.goto_calls == []


def test_unverified_post_state_is_ambiguous_and_never_retried():
    page = _Page([_state(), _state()])

    with pytest.raises(ClientError, match="Do not retry automatically"):
        _client(page).apply_task(BASIC_TASK, confirm=True)

    assert page.clicks == 1
    assert page.goto_calls == [BASIC_TASK]


def test_click_exception_is_ambiguous_because_mutation_boundary_was_crossed():
    page = _Page([_state()], click_error=RuntimeError("connection lost"))

    with pytest.raises(ClientError, match="clicked exactly once"):
        _client(page).apply_task(BASIC_TASK, confirm=True)

    assert page.clicks == 1
    assert page.goto_calls == []


def test_missing_required_file_fails_before_mutation():
    page = _Page([_state()], detail=_detail(file_fields=["Proof_file"]))

    with pytest.raises(ClientError, match="requires uploading a proof file"):
        _client(page).apply_task(BASIC_TASK, confirm=True)

    assert page.clicks == 0
    assert page.uploads == []
