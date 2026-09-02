import json

from typer.testing import CliRunner

from google_cli.commands import analytics as analytics_commands
from google_cli.main import app


class FakeExecute:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class FakeAccountSummaries:
    def __init__(self, payload):
        self.payload = payload
        self.page_size = None

    def list(self, pageSize):
        self.page_size = pageSize
        return FakeExecute(self.payload)


class FakeAnalyticsAdminService:
    def __init__(self, payload):
        self.account_summaries = FakeAccountSummaries(payload)

    def accountSummaries(self):
        return self.account_summaries


class FakeClient:
    def __init__(self, service):
        self.service = service

    def get_analytics_admin_service(self):
        return self.service


def test_analytics_properties_command_lists_ga4_properties(monkeypatch):
    service = FakeAnalyticsAdminService(
        {
            "accountSummaries": [
                {
                    "account": "accounts/123",
                    "displayName": "Example",
                    "propertySummaries": [
                        {
                            "property": "properties/456",
                            "displayName": "example.com",
                        }
                    ],
                }
            ]
        }
    )
    monkeypatch.setattr(
        analytics_commands,
        "get_client",
        lambda profile=None: FakeClient(service),
    )

    result = CliRunner().invoke(app, ["analytics", "properties", "--limit", "10"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [
        {
            "account_name": "Example",
            "account_id": "123",
            "property_name": "example.com",
            "property_id": "456",
        }
    ]
    assert service.account_summaries.page_size == 10


MULTI_ACCOUNT_SUMMARIES = {
    "accountSummaries": [
        {
            "account": "accounts/214224240",
            "displayName": "Coin Smarts",
            "propertySummaries": [
                {"property": "properties/295429923", "displayName": "Coin Smarts"}
            ],
        },
        {
            "account": "accounts/44523008",
            "displayName": "Adam the Automator",
            "propertySummaries": [
                {"property": "properties/256056970", "displayName": "Action Blogger"},
                {
                    "property": "properties/322716704",
                    "displayName": "adamtheautomator.com - GA4",
                },
            ],
        },
    ]
}


def _run_accounts(monkeypatch, args):
    service = FakeAnalyticsAdminService(MULTI_ACCOUNT_SUMMARIES)
    monkeypatch.setattr(
        analytics_commands,
        "get_client",
        lambda profile=None: FakeClient(service),
    )
    return CliRunner().invoke(app, ["analytics", "accounts", *args])


def test_analytics_accounts_filter_contains_narrows_results(monkeypatch):
    result = _run_accounts(
        monkeypatch, ["--filter", "property_name:contains:adamtheautomator"]
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [
        {
            "account_name": "Adam the Automator",
            "account_id": "44523008",
            "property_name": "adamtheautomator.com - GA4",
            "property_id": "322716704",
        }
    ]


def test_analytics_accounts_filter_eq_narrows_results(monkeypatch):
    result = _run_accounts(monkeypatch, ["--filter", "property_id:eq:256056970"])

    assert result.exit_code == 0
    assert [row["property_name"] for row in json.loads(result.stdout)] == [
        "Action Blogger"
    ]


def test_analytics_accounts_filters_before_properties_projection(monkeypatch):
    """A filter must work on a field that --properties does not display."""
    result = _run_accounts(
        monkeypatch,
        [
            "--filter",
            "property_name:contains:adamtheautomator",
            "--properties",
            "property_id",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [{"property_id": "322716704"}]


def test_analytics_accounts_without_filter_returns_every_property(monkeypatch):
    result = _run_accounts(monkeypatch, [])

    assert result.exit_code == 0
    assert len(json.loads(result.stdout)) == 3


def test_analytics_accounts_rejects_unknown_filter_field(monkeypatch):
    result = _run_accounts(monkeypatch, ["--filter", "propertyName:contains:adam"])

    assert result.exit_code == 1
