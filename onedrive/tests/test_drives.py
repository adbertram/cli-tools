"""Tests for drive enumeration scopes and loud failures.

Microsoft Graph answers drive collections with an empty ``200`` when the caller
holds no Files/Sites permission, so an empty list must never be produced by a
failed or unauthorized call.
"""

import base64
import json

import pytest

from onedrive_cli import msal_auth
from onedrive_cli.client import ClientError, OneDriveClient


def make_token(scp: str = "", roles=None) -> str:
    """Build a JWT-shaped token carrying the given Graph permissions."""
    claims = {"aud": "https://graph.microsoft.com"}
    if scp:
        claims["scp"] = scp
    if roles is not None:
        claims["roles"] = roles
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode("utf-8")).decode("ascii").rstrip("=")
    return f"header.{payload}.signature"


# ==================== Drive scope endpoints ====================


@pytest.mark.parametrize(
    "kwargs,expected",
    [
        ({}, "/me/drives"),
        ({"user": "someone@contoso.com"}, "/users/someone@contoso.com/drives"),
        ({"group": "group-id"}, "/groups/group-id/drives"),
        ({"site": "contoso.sharepoint.com,site-guid,web-guid"},
         "/sites/contoso.sharepoint.com,site-guid,web-guid/drives"),
        ({"site": "contoso.sharepoint.com:/sites/Marketing"},
         "/sites/contoso.sharepoint.com:/sites/Marketing:/drives"),
        ({"site": "contoso.sharepoint.com:/sites/Marketing:"},
         "/sites/contoso.sharepoint.com:/sites/Marketing:/drives"),
    ],
)
def test_drives_endpoint_builds_requested_scope(kwargs, expected):
    assert OneDriveClient._drives_endpoint(**kwargs) == expected


def test_drives_endpoint_rejects_multiple_scopes():
    with pytest.raises(ClientError) as excinfo:
        OneDriveClient._drives_endpoint(user="someone@contoso.com", site="contoso.sharepoint.com")

    assert "--site" in str(excinfo.value)
    assert "--user" in str(excinfo.value)


def test_list_drives_issues_one_request_for_the_scope():
    client = OneDriveClient()
    calls = []

    def fake_request(method, endpoint, **kwargs):
        calls.append((method, endpoint, kwargs.get("params")))
        return {"value": [{"id": "drive-1", "name": "Documents", "driveType": "documentLibrary"}]}

    client._make_request = fake_request

    drives = client.list_drives(limit=5, site="contoso.sharepoint.com:/sites/Marketing")

    assert calls == [("GET", "/sites/contoso.sharepoint.com:/sites/Marketing:/drives", {"$top": 5})]
    assert [d.id for d in drives] == ["drive-1"]


def test_list_drives_propagates_graph_errors():
    """A failed drive query must raise, never degrade into an empty list."""
    client = OneDriveClient()

    def fake_request(method, endpoint, **kwargs):
        raise ClientError("API request failed (404): Item not found")

    client._make_request = fake_request

    with pytest.raises(ClientError) as excinfo:
        client.list_drives()

    assert "404" in str(excinfo.value)


def test_list_drives_rejects_response_without_collection():
    client = OneDriveClient()
    client._make_request = lambda method, endpoint, **kwargs: {"error": "unexpected"}

    with pytest.raises(ClientError) as excinfo:
        client.list_drives()

    assert "no 'value' collection" in str(excinfo.value)


# ==================== Token permission assertions ====================


def test_token_graph_permissions_reads_delegated_and_application_claims():
    token = make_token(scp="Files.ReadWrite.All User.Read", roles=["Sites.Read.All"])

    assert msal_auth._token_graph_permissions(token) == [
        "Files.ReadWrite.All",
        "User.Read",
        "Sites.Read.All",
    ]


@pytest.mark.parametrize(
    "token",
    [
        make_token(scp="Files.ReadWrite.All User.Read"),
        make_token(scp="Files.Read"),
        make_token(scp="Sites.Read.All"),
        make_token(roles=["Files.ReadWrite.All"]),
    ],
)
def test_assert_drive_permissions_accepts_drive_capable_tokens(token):
    msal_auth._assert_drive_permissions(token)


def test_assert_drive_permissions_rejects_token_without_files_or_sites():
    """The real az_cli defect: a directory-scoped token reads drives as empty."""
    token = make_token(scp="Directory.AccessAsUser.All User.Read.All Group.ReadWrite.All")

    with pytest.raises(RuntimeError) as excinfo:
        msal_auth._assert_drive_permissions(token)

    message = str(excinfo.value)
    assert "no Files.* or Sites.* permission" in message
    assert "Directory.AccessAsUser.All" in message
    assert "az login --scope https://graph.microsoft.com/Files.ReadWrite.All" in message


def test_assert_drive_permissions_rejects_token_with_no_permissions():
    with pytest.raises(RuntimeError) as excinfo:
        msal_auth._assert_drive_permissions(make_token())

    assert "(none)" in str(excinfo.value)


def test_decode_token_claims_rejects_non_jwt():
    with pytest.raises(RuntimeError) as excinfo:
        msal_auth._decode_token_claims("not-a-jwt")

    assert "not a JWT" in str(excinfo.value)


def test_verify_drive_access_checks_permissions_before_calling_graph(monkeypatch):
    def fail_get(*args, **kwargs):
        raise AssertionError("permission-less tokens must be rejected before the Graph call")

    monkeypatch.setattr(msal_auth.requests, "get", fail_get)

    with pytest.raises(RuntimeError) as excinfo:
        msal_auth._verify_drive_access(make_token(scp="Directory.AccessAsUser.All"))

    assert "no Files.* or Sites.* permission" in str(excinfo.value)


def test_get_access_token_asserts_drive_permissions(monkeypatch):
    """Every command path validates the token, not just auth status."""
    monkeypatch.setattr(
        msal_auth, "get_config", lambda: type("Config", (), {"auth_method": "az_cli"})()
    )
    monkeypatch.setattr(
        msal_auth, "_get_az_cli_token", lambda: make_token(scp="Directory.AccessAsUser.All")
    )

    with pytest.raises(RuntimeError) as excinfo:
        msal_auth.get_access_token()

    assert "no Files.* or Sites.* permission" in str(excinfo.value)


def test_get_access_token_returns_drive_capable_token(monkeypatch):
    token = make_token(scp="Files.ReadWrite.All")
    monkeypatch.setattr(
        msal_auth, "get_config", lambda: type("Config", (), {"auth_method": "az_cli"})()
    )
    monkeypatch.setattr(msal_auth, "_get_az_cli_token", lambda: token)

    assert msal_auth.get_access_token() == token
