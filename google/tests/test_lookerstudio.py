import json
from urllib.parse import parse_qs, urlparse

import pytest
from typer.testing import CliRunner

from google_cli.client import ClientError
from google_cli.commands import lookerstudio as lookerstudio_commands
from google_cli.lookerstudio_client import (
    LookerStudioClient,
    build_report_link,
    parse_linking_parameter,
)
from google_cli.main import app
from google_cli.models.lookerstudio import (
    LookerStudioAsset,
    LookerStudioDataSourceParameter,
    LookerStudioRole,
)


class FakeResponse:
    def __init__(self, payload, status_code=200, url=None):
        self.payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)
        self.url = url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise AssertionError(f"{self.status_code} error for {self.url}: {self.text}")

    def json(self):
        return self.payload


class CapturingSession:
    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.requests = []

    def request(self, method, url, **kwargs):
        self.requests.append({"method": method, "url": url, **kwargs})
        response = self.payloads.pop(0)
        if isinstance(response, FakeResponse):
            return response
        return FakeResponse(response)


class FakeLookerStudioClient:
    def __init__(self):
        self.search_calls = []
        self.permission_calls = []
        self.assets = [
            LookerStudioAsset(
                assetType="REPORT",
                name="report-123",
                title="ATA Blog",
                trashed=False,
            )
        ]

    def search_reports(
        self,
        *,
        title=None,
        owner=None,
        include_trashed=False,
        order_by=None,
        page_size=1000,
        page_token=None,
    ):
        self.search_calls.append(
            {
                "title": title,
                "owner": owner,
                "include_trashed": include_trashed,
                "order_by": order_by,
                "page_size": page_size,
                "page_token": page_token,
            }
        )
        return self.assets

    def get_report(self, report_id):
        if report_id != "report-123":
            raise ValueError(f"Report not found: {report_id}")
        return self.assets[0]

    def get_permissions(self, asset_name):
        self.permission_calls.append({"action": "get", "asset_name": asset_name})
        return {"permissions": {"VIEWER": {"members": ["user:client@example.com"]}}, "etag": "abc"}

    def add_members(self, asset_name, role, members):
        self.permission_calls.append(
            {"action": "add", "asset_name": asset_name, "role": role, "members": members}
        )
        return {"permissions": {role: {"members": members}}, "etag": "def"}


def query_params(url):
    return {key: values[0] for key, values in parse_qs(urlparse(url).query).items()}


def test_lookerstudio_reports_command_group_is_registered():
    result = CliRunner().invoke(app, ["lookerstudio", "reports", "--help"])

    assert result.exit_code == 0
    for command_name in (
        "list",
        "get",
        "create-link",
        "update-link",
        "permissions-get",
        "permissions-add-members",
        "permissions-patch",
        "permissions-revoke-all",
    ):
        assert command_name in result.stdout


def test_reports_list_outputs_report_assets_and_sends_search_options(monkeypatch):
    client = FakeLookerStudioClient()
    monkeypatch.setattr(
        lookerstudio_commands,
        "get_lookerstudio_client",
        lambda profile=None: client,
    )

    result = CliRunner().invoke(
        app,
        [
            "lookerstudio",
            "reports",
            "list",
            "--title",
            "ATA",
            "--owner",
            "owner@example.com",
            "--include-trashed",
            "--order-by",
            "title",
            "--limit",
            "25",
            "--page-token",
            "next-token",
            "--properties",
            "name,title",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == [{"name": "report-123", "title": "ATA Blog"}]
    assert client.search_calls == [
        {
            "title": "ATA",
            "owner": "owner@example.com",
            "include_trashed": True,
            "order_by": "title",
            "page_size": 25,
            "page_token": "next-token",
        }
    ]


def test_reports_get_outputs_single_report(monkeypatch):
    client = FakeLookerStudioClient()
    monkeypatch.setattr(
        lookerstudio_commands,
        "get_lookerstudio_client",
        lambda profile=None: client,
    )

    result = CliRunner().invoke(
        app,
        ["lookerstudio", "reports", "get", "report-123", "--properties", "name,title"],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"name": "report-123", "title": "ATA Blog"}


def test_parse_linking_parameter_requires_alias_key_value_shape():
    parameter = parse_linking_parameter("ds0.accountId=54516992")

    assert parameter == LookerStudioDataSourceParameter(
        alias="ds0",
        key="accountId",
        value="54516992",
    )


def test_build_report_link_outputs_ga4_linking_api_url():
    link = build_report_link(
        report_id="report-123",
        report_name="ATA Blog Dashboard",
        page_id="page-1",
        mode="view",
        explain=True,
        measurement_id="G-ABC123",
        keep_measurement_id=False,
        data_source_parameters=[
            LookerStudioDataSourceParameter(
                alias="ds0", key="connector", value="googleAnalytics"
            ),
            LookerStudioDataSourceParameter(alias="ds0", key="accountId", value="54516992"),
            LookerStudioDataSourceParameter(alias="ds0", key="propertyId", value="213025502"),
            LookerStudioDataSourceParameter(alias="ds0", key="refreshFields", value=False),
        ],
        embed=False,
    )

    assert link.url.startswith("https://lookerstudio.google.com/reporting/create?")
    assert query_params(link.url) == {
        "c.reportId": "report-123",
        "c.pageId": "page-1",
        "c.mode": "view",
        "c.explain": "true",
        "r.reportName": "ATA Blog Dashboard",
        "r.measurementId": "G-ABC123",
        "r.keepMeasurementId": "false",
        "ds.ds0.connector": "googleAnalytics",
        "ds.ds0.accountId": "54516992",
        "ds.ds0.propertyId": "213025502",
        "ds.ds0.refreshFields": "false",
    }


def test_reports_create_link_command_outputs_link_without_api_call():
    result = CliRunner().invoke(
        app,
        [
            "lookerstudio",
            "reports",
            "create-link",
            "--report-id",
            "report-123",
            "--report-name",
            "ATA Blog Dashboard",
            "--ga-alias",
            "ds0",
            "--ga-account-id",
            "54516992",
            "--ga-property-id",
            "213025502",
            "--ga-refresh-fields",
            "false",
        ],
    )

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["report_id"] == "report-123"
    assert query_params(output["url"]) == {
        "c.reportId": "report-123",
        "r.reportName": "ATA Blog Dashboard",
        "ds.ds0.connector": "googleAnalytics",
        "ds.ds0.accountId": "54516992",
        "ds.ds0.propertyId": "213025502",
        "ds.ds0.refreshFields": "false",
    }


def test_reports_update_link_command_outputs_link_for_existing_report_id():
    result = CliRunner().invoke(
        app,
        [
            "lookerstudio",
            "reports",
            "update-link",
            "report-123",
            "--data-source",
            "ds0.propertyId=213025502",
        ],
    )

    assert result.exit_code == 0
    output = json.loads(result.stdout)
    assert output["report_id"] == "report-123"
    assert query_params(output["url"]) == {
        "c.reportId": "report-123",
        "ds.ds0.propertyId": "213025502",
    }


def test_lookerstudio_client_search_reports_calls_assets_search_endpoint():
    session = CapturingSession(
        {
            "assets": [
                {
                    "assetType": "REPORT",
                    "name": "report-123",
                    "title": "ATA Blog",
                    "trashed": False,
                }
            ],
            "nextPageToken": "next-token",
        }
    )
    client = LookerStudioClient(session=session)

    reports = client.search_reports(
        title="ATA",
        owner="owner@example.com",
        include_trashed=True,
        order_by="title",
        page_size=25,
        page_token="page-token",
    )

    assert [report.name for report in reports] == ["report-123"]
    assert session.requests == [
        {
            "method": "GET",
            "url": "https://datastudio.googleapis.com/v1/assets:search",
            "params": {
                "assetTypes": ["REPORT"],
                "title": "ATA",
                "includeTrashed": True,
                "owner": "owner@example.com",
                "orderBy": "title",
                "pageSize": 25,
                "pageToken": "page-token",
            },
        }
    ]


def test_lookerstudio_client_accepts_search_report_assets_without_trashed_field():
    session = CapturingSession(
        {
            "assets": [
                {
                    "assetType": "REPORT",
                    "name": "report-123",
                    "title": "ATA Blog",
                }
            ],
        }
    )
    client = LookerStudioClient(session=session)

    reports = client.search_reports(page_size=1)

    assert reports == [
        LookerStudioAsset(
            assetType="REPORT",
            name="report-123",
            title="ATA Blog",
            trashed=None,
        )
    ]


def test_lookerstudio_client_explains_workspace_admin_authorization_for_assets_search_403():
    session = CapturingSession(
        FakeResponse(
            {"error": {"code": 403, "message": "Forbidden", "status": "PERMISSION_DENIED"}},
            status_code=403,
            url="https://datastudio.googleapis.com/v1/assets:search?assetTypes=REPORT&includeTrashed=False&pageSize=100",
        )
    )
    client = LookerStudioClient(session=session, profile="example-user")

    with pytest.raises(ClientError) as error:
        client.search_reports(page_size=100)

    assert str(error.value) == (
        "Looker Studio REST API is not authorized for this Google Workspace / Cloud Identity "
        "environment. Google returned 403 Forbidden for "
        "https://datastudio.googleapis.com/v1/assets:search?assetTypes=REPORT&includeTrashed=False&pageSize=100. "
        "The OAuth token can still be valid and include https://www.googleapis.com/auth/datastudio. "
        "If this profile uses a personal Gmail account, authenticate with a Google Workspace "
        "or Cloud Identity account instead. "
        "Ask the Google Workspace admin to authorize the OAuth app/client for Looker Studio API "
        "access and the datastudio scope, then rerun "
        "`google auth login --profile example-user --force`."
    )


def test_lookerstudio_client_explains_disabled_lookerstudio_api_403():
    session = CapturingSession(
        FakeResponse(
            {
                "error": {
                    "code": 403,
                    "message": "Looker Studio API has not been used in project 153584548092 before or it is disabled.",
                    "status": "PERMISSION_DENIED",
                    "details": [
                        {
                            "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                            "reason": "SERVICE_DISABLED",
                            "domain": "googleapis.com",
                            "metadata": {
                                "service": "datastudio.googleapis.com",
                                "consumer": "projects/153584548092",
                            },
                        }
                    ],
                }
            },
            status_code=403,
            url="https://datastudio.googleapis.com/v1/assets:search?assetTypes=REPORT&includeTrashed=False&pageSize=100",
        )
    )
    client = LookerStudioClient(session=session, profile="example-user")

    with pytest.raises(ClientError) as error:
        client.search_reports(page_size=100)

    assert str(error.value) == (
        "Looker Studio API is disabled for Google Cloud project 153584548092. "
        "Enable it with `google cloud services enable datastudio.googleapis.com "
        "--project 153584548092 --profile example-user`, then retry."
    )


def test_permissions_add_members_outputs_updated_permissions(monkeypatch):
    client = FakeLookerStudioClient()
    monkeypatch.setattr(
        lookerstudio_commands,
        "get_lookerstudio_client",
        lambda profile=None: client,
    )

    result = CliRunner().invoke(
        app,
        [
            "lookerstudio",
            "reports",
            "permissions-add-members",
            "report-123",
            "--role",
            "VIEWER",
            "--member",
            "user:client@example.com",
        ],
    )

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {
        "permissions": {"VIEWER": {"members": ["user:client@example.com"]}},
        "etag": "def",
    }
    assert client.permission_calls == [
        {
            "action": "add",
            "asset_name": "report-123",
            "role": LookerStudioRole.VIEWER,
            "members": ["user:client@example.com"],
        }
    ]


def test_parse_linking_parameter_rejects_invalid_shape():
    with pytest.raises(ValueError, match="Expected data source parameter"):
        parse_linking_parameter("propertyId")
