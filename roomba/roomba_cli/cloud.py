"""Read only the exact cloud resources evidenced by an authorized app capture.

No discovery, login, refresh, mutation, or regional fallback is performed here.
"""
from datetime import datetime, timezone
import hashlib
import hmac
import re
from urllib.parse import quote, urlsplit

import requests

from .client import ClientError, CloudAuthenticationError

# Each origin and route was observed returning HTTP 200 in the app capture.
ROUTES = {
    "history": (("auth1.prod.iot.irobotapi.com", "auth3.prod.iot.irobotapi.com"), r"/v1/([^/]+)/missionhistory", {"app_id", "filterType", "supportedDoneCodes"}),
    "schedule": ("auth3.prod.iot.irobotapi.com", r"/v1/households/([^/]+)/settings/schedule", set()),
    "setup": ("auth3.prod.iot.irobotapi.com", r"/v1/robots/([^/]+)/setupinfo", {"sku"}),
    "entitlements": ("ecomm.prod.user-services.irobotapi.com", r"/v1/ecommerce/entitlements-app/user/entitlements", set()),
    "favorites": ("auth3.prod.iot.irobotapi.com", r"/v1/user/favorites", set()),
    "timeline": (("auth1.prod.iot.irobotapi.com", "auth3.prod.iot.irobotapi.com"), r"/v1/robots/([^/]+)/timeline", {"app_version", "details_type_filter", "limit", "event_type"}),
    "parts": (("auth1.prod.iot.irobotapi.com", "auth3.prod.iot.irobotapi.com"), r"/v1/robots/([^/]+)/parts", set()),
    "robot": (("auth1.prod.iot.irobotapi.com", "auth3.prod.iot.irobotapi.com"), r"/v1/robots", {"robot_id"}),
    "maps": ("auth3.prod.iot.irobotapi.com", r"/v1/([^/]+)/pmaps", {"visible", "activeDetails"}),
    "map-version": ("auth3.prod.iot.irobotapi.com", r"/v1/([^/]+)/pmaps/[^/]+/versions/[^/]+", set()),
    "clean-score": ("auth3.prod.iot.irobotapi.com", r"/v1/pmaps/clean-score", {"pmap_id"}),
    "evac-history": ("auth3.prod.iot.irobotapi.com", r"/v1/evachistory", {"robotId", "maxAge"}),
    "time-estimates": ("auth3.prod.iot.irobotapi.com", r"/v1/robots/([^/]+)/time-estimates", {"app_id"}),
    "team": ("auth1.prod.iot.irobotapi.com", r"/v1/([^/]+)/team", {"app_id"}),
    "team-report": ("auth1.prod.iot.irobotapi.com", r"/v1/([^/]+)/team/report", {"app_id"}),
    "settings": ("auth3.prod.iot.irobotapi.com", r"/v1/user/settings", set()),
    "automations": ("auth3.prod.iot.irobotapi.com", r"/v1/user/automations", set()),
    "households": ("auth3.prod.iot.irobotapi.com", r"/v1/user/households", set()),
    "ifttt": ("auth3.prod.iot.irobotapi.com", r"/v1/ifttt/connections", set()),
    "user-ifttt": ("auth3.prod.iot.irobotapi.com", r"/v1/user/ifttt/connections", set()),
}
ROBOT_PATH_RESOURCES = {"history", "setup", "timeline", "parts", "maps", "map-version", "time-estimates", "team", "team-report"}
ROBOT_QUERY_FIELDS = {"robot": "robot_id", "evac-history": "robotId"}
ROBOT_RESOURCES = ROBOT_PATH_RESOURCES | set(ROBOT_QUERY_FIELDS) | {"clean-score"}
TARGETED_RESOURCES = ROBOT_RESOURCES | {"schedule"}

SIGNED_HEADERS = ("accept", "content-type", "host", "user-agent", "x-amz-date", "x-amz-security-token")


def validate_template(kind, template, robot_id=None):
    """Reject arbitrary URLs, missing query evidence, and unrelated robots."""
    if kind not in ROUTES or not isinstance(template, dict):
        raise ClientError("Unsupported captured cloud resource")
    host, pattern, query_keys = ROUTES[kind]
    if not isinstance(template.get("url"), str):
        raise ClientError("Captured cloud URL is invalid")
    try:
        url = urlsplit(template["url"])
    except ValueError:
        raise ClientError("Captured cloud URL is invalid") from None
    match = re.fullmatch(pattern, url.path)
    query = template.get("query")
    headers = template.get("headers")
    if (url.scheme != "https" or url.netloc not in ((host,) if isinstance(host, str) else host) or url.query or url.fragment
            or not match or not isinstance(query, list)
            or any(not isinstance(p, list) or len(p) != 2 or not all(isinstance(v, str) for v in p) for p in query)
            or {p[0] for p in query} != query_keys
            or len(query) != len(query_keys)
            or not isinstance(headers, dict)
            or set(headers) != {"accept", "content-type", "user-agent"}
            or any(not isinstance(v, str) or '\r' in v or '\n' in v for v in headers.values())
            or template.get("method") != "GET"):
        raise ClientError("Captured cloud request does not match the supported read contract")
    if kind in ROBOT_PATH_RESOURCES and (not robot_id or match.group(1) != robot_id):
        raise ClientError("Captured cloud resource does not match the selected configured robot")
    if kind in ROBOT_QUERY_FIELDS and (not robot_id or dict(query).get(ROBOT_QUERY_FIELDS[kind]) != robot_id):
        raise ClientError("Captured cloud resource does not match the selected cloud robot")
    if kind == "schedule" and (not robot_id or not isinstance(template.get("household_robot_ids"), list) or robot_id not in template["household_robot_ids"]):
        raise ClientError("Captured household schedule is not bound to this robot's household")
    if kind == "clean-score" and (not robot_id or template.get("map_robot_id") != robot_id or template.get("owned_pmap_id") != dict(query).get("pmap_id")):
        raise ClientError("Captured clean score has no verified map ownership for this robot")
    return template


def validate_credentials(credentials, now=None):
    """Fail closed on missing or expired temporary AWS session credentials."""
    if not isinstance(credentials, dict) or any(not isinstance(credentials.get(k), str) or not credentials[k] for k in ("AccessKeyId", "SecretKey", "SessionToken", "Expiration")):
        raise ClientError("Cloud session credentials are missing; import a fresh authorized login capture")
    try:
        expiration = datetime.fromisoformat(credentials["Expiration"].replace("Z", "+00:00"))
        if expiration.tzinfo is None:
            raise ValueError
    except ValueError:
        raise ClientError("Cloud session expiration is invalid") from None
    if expiration <= (now or datetime.now(timezone.utc)):
        raise ClientError("Cloud session expired; import a fresh authorized login capture")


def signed_request(template, credentials, region, now=None):
    """Build AWS SigV4 for an already validated exact captured GET template."""
    now = now or datetime.now(timezone.utc)
    validate_credentials(credentials, now)
    if region != "us-east-1":
        raise ClientError("Cloud signing region is not evidenced by this capture")
    parsed = urlsplit(template["url"])
    headers = dict(template["headers"], host=parsed.netloc)
    headers["x-amz-date"] = now.strftime("%Y%m%dT%H%M%SZ")
    headers["x-amz-security-token"] = credentials["SessionToken"]
    canonical_headers = ''.join(f"{k}:{' '.join(headers[k].split())}\n" for k in SIGNED_HEADERS)
    signed_headers = ';'.join(SIGNED_HEADERS)
    query = '&'.join(f'{quote(k, safe="-_.~")}={quote(v, safe="-_.~")}' for k, v in sorted(template["query"], key=lambda p: (quote(p[0], safe="-_.~"), quote(p[1], safe="-_.~"))))
    canonical = '\n'.join(("GET", quote(parsed.path, safe="/-_.~"), query, canonical_headers, signed_headers, hashlib.sha256(b'').hexdigest()))
    day = now.strftime("%Y%m%d")
    scope = f"{day}/{region}/execute-api/aws4_request"
    to_sign = '\n'.join(("AWS4-HMAC-SHA256", headers["x-amz-date"], scope, hashlib.sha256(canonical.encode()).hexdigest()))
    key = ("AWS4" + credentials["SecretKey"]).encode()
    for part in (day, region, "execute-api", "aws4_request"):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    headers["authorization"] = f"AWS4-HMAC-SHA256 Credential={credentials['AccessKeyId']}/{scope}, SignedHeaders={signed_headers}, Signature={signature}"
    return template["url"] + ('?' + query if query else ''), headers


def read_resource(kind, template, credentials, region, robot_id=None, timeout=15):
    """Make one bounded signed GET, without redirects, retries, or proxy inheritance."""
    validate_template(kind, template, robot_id)
    url, headers = signed_request(template, credentials, region)
    session = requests.Session()
    session.trust_env = False
    try:
        response = session.get(url, headers=headers, timeout=(5, timeout), allow_redirects=False)
        if response.status_code in (401, 403):
            raise CloudAuthenticationError("Cloud authorization rejected")
        if not 200 <= response.status_code < 300:
            raise ClientError(f"Cloud read failed (HTTP {response.status_code})")
        try:
            data = response.json()
        except ValueError:
            raise ClientError("Cloud read returned invalid JSON") from None
        if not isinstance(data, (dict, list)):
            raise ClientError("Cloud read returned an unsupported JSON shape")
        return {"source": "live_cloud", "resource": kind, "device_status": "not_observed", "data": data}
    except requests.RequestException:
        raise ClientError("Cloud read transport failed") from None
    finally:
        session.close()
