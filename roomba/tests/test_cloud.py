"""Synthetic cloud read safety and faithful signing coverage; no real captures."""
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest

from roomba_cli.client import ClientError
from roomba_cli.cloud import read_resource, signed_request, validate_template

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
CREDS = {"AccessKeyId": "SYNTHETIC", "SecretKey": "synthetic-secret", "SessionToken": "synthetic-token", "Expiration": "2099-01-01T00:00:00Z"}


def template(kind="setup"):
    return {"method": "GET", "url": "https://auth3.prod.iot.irobotapi.com/v1/robots/synthetic-robot/setupinfo", "headers": {"accept": "application/json", "content-type": "application/json", "user-agent": "Synthetic App"}, "query": [["sku", "synthetic-sku"]]}


def test_sigv4_matches_independently_verified_signature():
    # Cross-checked with botocore SigV4Auth including the app's signed User-Agent.
    url, headers = signed_request(template(), CREDS, "us-east-1", NOW)
    assert url.endswith("?sku=synthetic-sku")
    assert headers["authorization"] == (
        "AWS4-HMAC-SHA256 Credential=SYNTHETIC/20260101/us-east-1/execute-api/aws4_request, "
        "SignedHeaders=accept;content-type;host;user-agent;x-amz-date;x-amz-security-token, "
        "Signature=967dcb63ae8b3debcc2ba9cae5ce6fd3febe573e5f69061767871dc2c5f57d3d"
    )


@pytest.mark.parametrize("change", [
    {"url": "https://attacker.invalid/v1/robots/synthetic-robot/setupinfo"},
    {"url": "https://auth3.prod.iot.irobotapi.com.evil.invalid/v1/robots/synthetic-robot/setupinfo"},
    {"url": "https://auth3.prod.iot.irobotapi.com/v1/robots/synthetic-robot/setupinfo?extra=secret"},
    {"method": "POST"}, {"query": []}, {"query": [["sku", "x"], ["extra", "secret"]]},
    {"headers": {"accept": "x", "content-type": "x", "user-agent": "x", "authorization": "secret"}},
])
def test_rejects_unobserved_requests(change):
    t = template(); t.update(change)
    with pytest.raises(ClientError): validate_template("setup", t, "synthetic-robot")


def test_selected_robot_is_required_and_exact():
    for selected in (None, "another-robot"):
        with pytest.raises(ClientError, match="selected configured robot"):
            validate_template("setup", template(), selected)


@pytest.mark.parametrize("credentials", [{}, dict(CREDS, Expiration="bad"), dict(CREDS, Expiration="2000-01-01T00:00:00Z")])
def test_missing_invalid_expired_credentials_do_not_request(credentials):
    with patch("roomba_cli.cloud.requests.Session") as session:
        with pytest.raises(ClientError): read_resource("setup", template(), credentials, "us-east-1", "synthetic-robot")
        session.assert_not_called()


@pytest.mark.parametrize("status", [301, 401, 403, 500])
def test_http_errors_do_not_expose_secrets_or_follow_redirects(status):
    response = Mock(status_code=status, text="synthetic-secret")
    session = Mock(); session.get.return_value = response
    with patch("roomba_cli.cloud.requests.Session", return_value=session):
        with pytest.raises(ClientError) as error:
            read_resource("setup", template(), CREDS, "us-east-1", "synthetic-robot")
    assert "synthetic-secret" not in str(error.value)
    assert session.get.call_args.kwargs["allow_redirects"] is False
    assert session.get.call_args.kwargs["timeout"] == (5, 15)
    assert session.trust_env is False
    session.close.assert_called_once()


def test_success_is_explicitly_cloud_data_not_live_robot_status():
    response = Mock(status_code=200); response.json.return_value = {"synthetic": True}
    session = Mock(); session.get.return_value = response
    with patch("roomba_cli.cloud.requests.Session", return_value=session):
        result = read_resource("setup", template(), CREDS, "us-east-1", "synthetic-robot")
    assert result["source"] == "live_cloud"
    assert result["device_status"] == "not_observed"
    assert session.get.call_count == 1


@pytest.mark.parametrize("change", [{"url": None}, {"url": []}, {"query": "sku=x"}, {"query": [["sku", "x"], ["sku", "y"]]}, {"headers": []}])
def test_malformed_template_types_and_duplicate_query_are_rejected(change):
    t = template(); t.update(change)
    with pytest.raises(ClientError): validate_template("setup", t, "synthetic-robot")


def test_unsupported_region_never_creates_http_session():
    with patch("roomba_cli.cloud.requests.Session") as session:
        with pytest.raises(ClientError, match="region"):
            read_resource("setup", template(), CREDS, "eu-west-1", "synthetic-robot")
        session.assert_not_called()


@pytest.mark.parametrize("failure", ["transport", "json", "scalar"])
def test_transport_and_bad_response_shapes_have_safe_errors(failure):
    import requests
    response = Mock(status_code=200)
    session = Mock(); session.get.return_value = response
    if failure == "transport": session.get.side_effect = requests.ConnectionError("secret URL synthetic-secret")
    if failure == "json": response.json.side_effect = ValueError("synthetic-secret")
    if failure == "scalar": response.json.return_value = "synthetic-secret"
    with patch("roomba_cli.cloud.requests.Session", return_value=session):
        with pytest.raises(ClientError) as error:
            read_resource("setup", template(), CREDS, "us-east-1", "synthetic-robot")
    assert "synthetic-secret" not in str(error.value)
    session.close.assert_called_once()


def test_query_scoped_robot_and_household_resources_cannot_cross_target():
    robot = {"method": "GET", "url": "https://auth1.prod.iot.irobotapi.com/v1/robots", "headers": template()["headers"], "query": [["robot_id", "robot-a"]]}
    assert validate_template("robot", robot, "robot-a") is robot
    with pytest.raises(ClientError): validate_template("robot", robot, "robot-b")
    household = {"method": "GET", "url": "https://auth3.prod.iot.irobotapi.com/v1/households/synthetic-household/settings/schedule", "headers": template()["headers"], "query": [], "household_robot_ids": ["robot-a"]}
    assert validate_template("schedule", household, "robot-a") is household
    with pytest.raises(ClientError): validate_template("schedule", household, "robot-b")


def test_clean_score_requires_exact_account_proven_map_and_robot_binding():
    score = {"method": "GET", "url": "https://auth3.prod.iot.irobotapi.com/v1/pmaps/clean-score", "headers": template()["headers"], "query": [["pmap_id", "map-a"]], "map_robot_id": "robot-a", "owned_pmap_id": "map-a"}
    assert validate_template("clean-score", score, "robot-a") is score
    with pytest.raises(ClientError): validate_template("clean-score", score, "robot-b")
    wrong = dict(score, query=[["pmap_id", "map-b"]])
    with pytest.raises(ClientError): validate_template("clean-score", wrong, "robot-a")
