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
