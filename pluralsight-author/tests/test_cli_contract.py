import json

from cli_tools_shared.data_cache import reset_cache_hit
from typer.testing import CliRunner

from pluralsight_author_cli.client import PluralsightAuthorClient
from pluralsight_author_cli.main import app


ITEMS = [
    {
        "id": "security-course-may-11-2026",
        "title": "Security Course",
        "opportunity_type": "Video Course",
        "category": "Security",
        "posted_date": "May 11, 2026",
        "is_new": True,
        "page_number": 1,
    },
    {
        "id": "ux-course-may-10-2026",
        "title": "UX Course",
        "opportunity_type": "Video Course",
        "category": "Product & UX",
        "posted_date": "May 10, 2026",
        "is_new": False,
        "page_number": 1,
    },
]


def install_client(monkeypatch):
    monkeypatch.setattr(PluralsightAuthorClient, "list_opportunities", lambda self, limit=1000: ITEMS[:limit])
    monkeypatch.setattr(
        PluralsightAuthorClient,
        "search",
        lambda self, query, limit=100: [
            item for item in ITEMS if query.casefold() in f"{item['title']} {item['category']}".casefold()
        ][:limit],
    )
    monkeypatch.setattr(
        PluralsightAuthorClient,
        "get_item",
        lambda self, item_id: {
            **next(item for item in ITEMS if item["id"] == item_id),
            "learning_objectives": [
                "1. Evaluate a strategic decision against a chain of evidence",
                "2. Distinguish signal from noise in product data",
            ],
        },
    )
    monkeypatch.setattr(
        PluralsightAuthorClient,
        "apply",
        lambda self, item_id, params: {
            "id": item_id,
            "title": next(item for item in ITEMS if item["id"] == item_id)["title"],
            "detail_url": "https://app.pluralsight.com/author-home/opportunity/detail-id-2",
            "submitted_param_keys": sorted(params.keys()),
            "form_markers": [
                "Application for:",
                "Tell us about your availability and domain expertise.",
                "Send application",
            ],
            "post_submit_state": "application_form_closed",
        },
    )


def invoke(monkeypatch, args):
    install_client(monkeypatch)
    reset_cache_hit()
    result = CliRunner().invoke(app, args)
    reset_cache_hit()
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def test_opportunities_list_filters_and_selects_properties(monkeypatch):
    assert invoke(
        monkeypatch,
        ["opportunities", "list", "--filter", "category:eq:Security", "--properties", "id,title"],
    ) == [{"id": "security-course-may-11-2026", "title": "Security Course"}]


def test_opportunities_get_returns_single_opportunity(monkeypatch):
    assert invoke(monkeypatch, ["opportunities", "get", "ux-course-may-10-2026"]) == {
        **ITEMS[1],
        "learning_objectives": [
            "1. Evaluate a strategic decision against a chain of evidence",
            "2. Distinguish signal from noise in product data",
        ],
    }


def test_opportunities_apply_returns_verified_submission_state(monkeypatch):
    assert invoke(
        monkeypatch,
        [
            "opportunities",
            "apply",
            "ux-course-may-10-2026",
            "--start_date",
            "06/01/2026",
            "--estimated_completion_weeks",
            "8",
            "--experience",
            "Built several accessibility-focused UX courses.",
        ],
    ) == {
        "id": "ux-course-may-10-2026",
        "title": "UX Course",
        "detail_url": "https://app.pluralsight.com/author-home/opportunity/detail-id-2",
        "submitted_param_keys": ["estimated_completion_weeks", "experience", "start_date"],
        "form_markers": [
            "Application for:",
            "Tell us about your availability and domain expertise.",
            "Send application",
        ],
        "post_submit_state": "application_form_closed",
    }


def test_opportunities_apply_accepts_explicit_options_and_passes_dict(monkeypatch):
    captured = {}

    def fake_apply(self, item_id, params):
        captured["item_id"] = item_id
        captured["params"] = params
        return {
            "id": item_id,
            "title": "Security Course",
            "detail_url": "https://app.pluralsight.com/author-home/opportunity/detail-id-1",
            "submitted_param_keys": sorted(params.keys()),
            "form_markers": [
                "Application for:",
                "Tell us about your availability and domain expertise.",
                "Send application",
            ],
            "post_submit_state": "application_form_closed",
        }

    monkeypatch.setattr(PluralsightAuthorClient, "list_opportunities", lambda self, limit=1000: ITEMS[:limit])
    monkeypatch.setattr(PluralsightAuthorClient, "apply", fake_apply)
    reset_cache_hit()
    result = CliRunner().invoke(
        app,
        [
            "opportunities",
            "apply",
            "security-course-may-11-2026",
            "--start_date",
            "06/01/2026",
            "--estimated_completion_weeks",
            "8",
            "--experience",
            "Hands-on security course delivery.",
        ],
    )
    reset_cache_hit()

    assert result.exit_code == 0, result.output
    assert captured == {
        "item_id": "security-course-may-11-2026",
        "params": {
            "start_date": "06/01/2026",
            "estimated_completion_weeks": "8",
            "experience": "Hands-on security course delivery.",
        },
    }


def test_opportunities_apply_fails_when_required_option_is_missing_before_client_invocation(monkeypatch):
    invoked = {"apply_called": False}

    def fail_if_called(self, item_id, params):
        del self, item_id, params
        invoked["apply_called"] = True
        raise AssertionError("apply should not be called when required options are missing")

    monkeypatch.setattr(PluralsightAuthorClient, "apply", fail_if_called)
    reset_cache_hit()
    result = CliRunner().invoke(
        app,
        [
            "opportunities",
            "apply",
            "security-course-may-11-2026",
            "--start_date",
            "06/01/2026",
            "--estimated_completion_weeks",
            "8",
        ],
    )
    reset_cache_hit()

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "Missing option '--experience'" in result.stderr
    assert invoked["apply_called"] is False


def test_opportunities_apply_fails_when_start_date_option_is_missing_before_client_invocation(monkeypatch):
    invoked = {"apply_called": False}

    def fail_if_called(self, item_id, params):
        del self, item_id, params
        invoked["apply_called"] = True
        raise AssertionError("apply should not be called when required options are missing")

    monkeypatch.setattr(PluralsightAuthorClient, "apply", fail_if_called)
    reset_cache_hit()
    result = CliRunner().invoke(
        app,
        [
            "opportunities",
            "apply",
            "security-course-may-11-2026",
            "--estimated_completion_weeks",
            "8",
            "--experience",
            "Hands-on security course delivery.",
        ],
    )
    reset_cache_hit()

    assert result.exit_code == 2
    assert result.stdout == ""
    assert "Missing option '--start_date'" in result.stderr
    assert invoked["apply_called"] is False


def test_search_query_selects_properties(monkeypatch):
    assert invoke(monkeypatch, ["search", "query", "security", "--properties", "id,category"]) == [
        {"id": "security-course-may-11-2026", "category": "Security"}
    ]
