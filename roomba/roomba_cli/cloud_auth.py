"""Renew captured Gigya sessions without retaining passwords or replaying proofs.

SAP's Swift SDK supplies the session-token HMAC-SHA1 protocol. All network calls
are bounded, redirect-free, and errors omit remote bodies and secret material.
"""
from contextlib import contextmanager, nullcontext
from datetime import datetime, timezone
import base64
import fcntl
import hashlib
import hmac
import json
import math
import os
import time
from urllib.parse import quote
import uuid

import requests

from .client import ClientError, CloudAuthenticationError
from .cloud import validate_credentials
from .cloud_mqtt import validate_connection_token
from .cloud_session import load_session, secret

REFRESH_WINDOW = 90
REFRESH_TIMEOUT = 30
ACCOUNT_URL = "https://accounts.us1.gigya.com/accounts.getAccountInfo"
LOGIN_URL = "https://unauth3.prod.iot.irobotapi.com/v2/login"


def gigya_signature(url, params, session_secret):
    """SAP Gigya Swift SignatureUtils' POST OAuth1 signature, before form encoding."""
    try:
        key = base64.b64decode(session_secret, validate=True)
        if not key:
            raise ValueError
        body = '&'.join(name + '=' + quote(value, safe='-_.~') for name, value in sorted(params.items()))
        message = 'POST&' + quote(url, safe='-_.~') + '&' + quote(body, safe='-_.~')
        return base64.b64encode(hmac.new(key, message.encode(), hashlib.sha1).digest()).decode()
    except (ValueError, TypeError, UnicodeError):
        raise ClientError("Saved Gigya session signing material is invalid; import a fresh login capture") from None


def prepare_refresh_material(candidate):
    """Verify the captured signature before retaining a minimal reusable session."""
    if not isinstance(candidate, dict) or candidate.get("account_info_url") != ACCOUNT_URL or candidate.get("login_url") != LOGIN_URL:
        raise ClientError("Captured refresh endpoints are unsupported")
    params = candidate.get("account_info_params")
    if not isinstance(params, dict) or any(not isinstance(key, str) or not isinstance(value, str) for key, value in params.items()):
        raise ClientError("Captured Gigya session parameters are invalid")
    session_secret = candidate.get("session_secret")
    token = candidate.get("session_token")
    uid = candidate.get("uid")
    if not all(isinstance(value, str) and value for value in (token, session_secret, uid)) or params.get("oauth_token") != token:
        raise ClientError("Captured Gigya session does not match its signed request")
    unsigned = {key: value for key, value in params.items() if key != "sig"}
    expected = gigya_signature(ACCOUNT_URL, unsigned, session_secret)
    if not hmac.compare_digest(expected, params.get("sig", "")):
        raise ClientError("Captured Gigya session signature did not verify")
    base_form = {key: value for key, value in unsigned.items() if key not in ("oauth_token", "nonce", "timestamp")}
    allowed = {"apikey", "extraProfileFields", "format", "gmid", "httpStatusCodes", "sdk", "targetEnv", "ucid"}
    if set(base_form) - allowed or not base_form.get("apikey") or base_form.get("targetEnv") != "mobile":
        raise ClientError("Captured Gigya session form is unsupported")
    body = candidate.get("login_body")
    if not isinstance(body, dict) or not isinstance(body.get("app_id"), str) or not body["app_id"]:
        raise ClientError("Captured iRobot app identity is missing")
    body = {key: body[key] for key in ("app_id", "app_info", "authorizer_params", "multiple_authorizer_token_support", "skip_ownership_check") if key in body}
    if body.get("multiple_authorizer_token_support") is not True or body.get("skip_ownership_check") != "0":
        raise ClientError("Captured iRobot session login contract is unsupported")
    body["assume_robot_ownership"] = "0"
    return {"account_info_url": ACCOUNT_URL, "account_info_form": base_form, "session_token": token, "session_secret": session_secret, "uid": uid, "login_url": LOGIN_URL, "login_body": body}


def fingerprint(credentials):
    # Used only in memory to coalesce concurrent renewals; never printed.
    return hashlib.sha256(json.dumps({key: credentials.get(key) for key in ("AccessKeyId", "SessionToken", "refreshed_at")}, sort_keys=True).encode()).hexdigest()


def expiry_timestamp(credentials):
    try:
        value = datetime.fromisoformat(credentials["Expiration"].replace("Z", "+00:00"))
        if value.tzinfo is None:
            raise ValueError
        return value.timestamp()
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        return None


def credentials_due(credentials, session, now=None, include_mqtt=True):
    current = time.time() if now is None else now
    expires = expiry_timestamp(credentials)
    if expires is None or expires <= current + REFRESH_WINDOW:
        return True
    if not include_mqtt:
        return False
    tokens = credentials.get("connection_tokens", [])
    for robot in session["robots"]:
        matches = [token for token in tokens if isinstance(token, dict) and isinstance(token.get("devices"), list) and robot["id"] in token["devices"]]
        if len(matches) != 1:
            return True
        try:
            validate_connection_token(matches[0], current + REFRESH_WINDOW)
        except ClientError:
            return True
    return False


@contextmanager
def profile_lock(config, kind, timeout=35):
    """Serialize refresh publication or a whole MQTT read sequence across processes."""
    if kind not in ("refresh", "mqtt"):
        raise ClientError("Unsupported cloud operation lock")
    directory = config.get_profile_data_dir()
    directory.mkdir(parents=True, exist_ok=True)
    descriptor = None
    acquired = False
    try:
        descriptor = os.open(directory / f".cloud-{kind}.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.fchmod(descriptor, 0o600)
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise ClientError("Another cloud operation did not finish before the lock deadline") from None
                time.sleep(0.05)
        yield
    except OSError:
        raise ClientError("Cloud operation lock unavailable") from None
    finally:
        if descriptor is not None:
            if acquired:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def _post_json(session, url, deadline, **kwargs):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ClientError("Cloud session renewal timed out")
    try:
        response = session.post(url, timeout=(min(5, remaining), remaining), allow_redirects=False, **kwargs)
        if response.status_code in (401, 403):
            raise ClientError("Saved cloud login session was rejected; sign in to the app and import a fresh login capture")
        if not 200 <= response.status_code < 300:
            raise ClientError(f"Cloud session renewal failed (HTTP {response.status_code})")
        data = response.json()
    except requests.RequestException:
        raise ClientError("Cloud session renewal transport failed") from None
    except ValueError:
        raise ClientError("Cloud session renewal returned invalid JSON") from None
    if not isinstance(data, dict):
        raise ClientError("Cloud session renewal returned an unsupported JSON shape")
    return data


def renew_credentials(credentials, metadata):
    material = credentials.get("refresh_material")
    if not isinstance(material, dict):
        raise ClientError("Automatic cloud renewal is not configured; import an authorized app login capture containing its Gigya session")
    if material.get("account_info_url") != ACCOUNT_URL or material.get("login_url") != LOGIN_URL:
        raise ClientError("Saved cloud renewal endpoints are unsupported")
    form = material.get("account_info_form")
    login_body = material.get("login_body")
    if (not isinstance(form, dict) or not form or any(not isinstance(key, str) or not isinstance(value, str) for key, value in form.items())
            or any(not isinstance(material.get(key), str) or not material[key] for key in ("session_token", "session_secret", "uid"))
            or not isinstance(login_body, dict) or not isinstance(login_body.get("app_id"), str)
            or login_body.get("skip_ownership_check") != "0" or login_body.get("multiple_authorizer_token_support") is not True):
        raise ClientError("Saved cloud renewal session is invalid; import a fresh login capture")
    identity = credentials.get("account_identity")
    if not isinstance(identity, str) or not identity:
        raise ClientError("Saved cloud account identity is missing; import a fresh login capture")
    deadline = time.monotonic() + REFRESH_TIMEOUT
    params = dict(material["account_info_form"], oauth_token=material["session_token"], timestamp=str(int(time.time())), nonce=uuid.uuid4().hex)
    params["sig"] = gigya_signature(ACCOUNT_URL, params, material["session_secret"])
    client = requests.Session()
    client.trust_env = False
    try:
        proof = _post_json(client, ACCOUNT_URL, deadline, data=params, headers={"Content-Type": "application/x-www-form-urlencoded"})
        if proof.get("errorCode") != 0:
            raise ClientError("Saved Gigya session was rejected; sign in to the app and import a fresh login capture")
        if proof.get("UID") != material["uid"] or any(not isinstance(proof.get(key), str) or not proof[key] for key in ("UID", "UIDSignature", "signatureTimestamp")):
            raise ClientError("Renewed Gigya proof does not match the saved cloud account")
        body = dict(material["login_body"], assume_robot_ownership="0", gigya={"uid": proof["UID"], "signature": proof["UIDSignature"], "timestamp": proof["signatureTimestamp"]})
        body.pop("push_info", None)
        renewed = _post_json(client, LOGIN_URL, deadline, json=body, headers={"Content-Type": "application/json"})
    finally:
        client.close()
    aws = renewed.get("credentials")
    if not isinstance(aws, dict) or aws.get("CognitoId") != identity:
        raise ClientError("Renewed cloud credentials belong to a different account; previous session preserved")
    fresh = {key: aws.get(key) for key in ("AccessKeyId", "SecretKey", "SessionToken", "Expiration")}
    validate_credentials(fresh)
    expected = {robot["id"]: (robot.get("sku"), robot.get("deployment_id")) for robot in metadata["robots"]}
    roster = renewed.get("robots")
    actual = {rid: (robot.get("sku"), robot.get("svcDeplId")) for rid, robot in roster.items() if isinstance(robot, dict)} if isinstance(roster, dict) else {}
    if actual != expected:
        raise ClientError("Renewed cloud robot membership or deployment changed; previous session preserved, import a fresh capture")
    tokens = renewed.get("connection_tokens")
    if not isinstance(tokens, list) or not tokens:
        raise ClientError("Renewed cloud MQTT session is missing; previous session preserved")
    allowed = {"client_id", "expires", "devices", "iot_token", "iot_signature", "iot_authorizer_name"}
    tokens = [{key: token.get(key) for key in allowed} for token in tokens if isinstance(token, dict)]
    for token in tokens:
        validate_connection_token(token)
        if set(token["devices"]) - set(expected):
            raise ClientError("Renewed cloud MQTT device membership changed; previous session preserved")
    for robot_id in expected:
        if sum(robot_id in token["devices"] for token in tokens) != 1:
            raise ClientError("Renewed cloud MQTT session does not unambiguously cover every robot")
    return dict(credentials, **fresh, connection_tokens=tokens, refreshed_at=time.time())


def refresh_auth(config, force=False, rejected_fingerprint=None):
    before = secret(config, "get")
    observed = rejected_fingerprint or fingerprint(before)
    with profile_lock(config, "refresh"):
        latest = secret(config, "get")
        metadata = load_session(config)
        changed = fingerprint(latest) != observed
        due = credentials_due(latest, metadata)
        if changed and not due:
            return latest, False
        if not force and not due and rejected_fingerprint is None:
            return latest, False
        if rejected_fingerprint is not None and time.time() - latest.get("refreshed_at", 0) < 30:
            raise CloudAuthenticationError("Cloud authorization was rejected after a recent renewal; previous session preserved")
        renewed = renew_credentials(latest, metadata)
        # One atomic keychain update. Metadata/defaults/templates never change
        # during renewal, so validation or store failure preserves that state.
        secret(config, "set", renewed)
        return renewed, True


def authenticated_read(config, operation, mqtt=False):
    # Lock order is always MQTT operation -> refresh. REST holds no MQTT lock.
    with profile_lock(config, "mqtt") if mqtt else nullcontext():
        metadata = load_session(config)
        credentials = secret(config, "get")
        if credentials_due(credentials, metadata, include_mqtt=mqtt):
            credentials, _ = refresh_auth(config)
        try:
            return operation(credentials)
        except CloudAuthenticationError:
            credentials, _ = refresh_auth(config, rejected_fingerprint=fingerprint(credentials))
            # Exactly one read retry; another rejection propagates unchanged.
            return operation(credentials)


def auth_status(config, credentials=None):
    credentials = secret(config, "get") if credentials is None else credentials
    metadata = load_session(config)
    expires = expiry_timestamp(credentials)
    tokens = credentials.get("connection_tokens", [])
    token_expiries = [token.get("expires") for token in tokens if isinstance(token, dict) and isinstance(token.get("expires"), (int, float)) and not isinstance(token["expires"], bool) and math.isfinite(token["expires"])]
    return {"credentials_saved": True, "automatic_refresh_configured": isinstance(credentials.get("refresh_material"), dict),
            "renewal_due": credentials_due(credentials, metadata), "aws_expires_at": credentials.get("Expiration"),
            "aws_seconds_remaining": max(0, expires - time.time()) if expires is not None else None,
            "mqtt_seconds_remaining": max(0, min(token_expiries) - time.time()) if token_expiries else None,
            "robot_count": len(metadata["robots"]), "last_refreshed_at": credentials.get("refreshed_at"),
            "saved_gigya_session_validity": "not_checked_by_status", "device_status": "not_observed"}
