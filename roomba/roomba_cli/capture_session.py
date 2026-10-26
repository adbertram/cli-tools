"""Private pinned-mitmproxy decoder. stdout is consumed privately by the CLI.

Never exports account request bodies, passwords, user certificates or profiles.
"""
import json
import re
import sys


def _flows(paths):
    from mitmproxy.io import FlowReader
    for path in paths:
        with open(path, "rb") as handle:
            try:
                yield from FlowReader(handle).stream()
            except Exception as error:
                # An active capture can end in an incomplete trailing record.
                if error.__class__.__name__ != "FlowReadException":
                    raise


def decode(path):
    paths = path if isinstance(path, (list, tuple)) else [path]
    credentials = None
    requests = []
    robots = []
    connection_tokens = []
    deployments = {}
    map_owners = {}
    household_owners = {}
    login_records = []
    latest_identity = None
    latest_membership = {}
    gigya_sessions = {}
    account_info_requests = []
    latest_login_body = None
    for flow in _flows(paths):
        request = getattr(flow, "request", None)
        response = getattr(flow, "response", None)
        if request is None or response is None or response.status_code != 200:
            continue
        if request.scheme != "https" or request.port != 443:
            continue
        route = request.path.split("?", 1)[0]
        if request.method == "POST" and request.host == "accounts.us1.gigya.com" and route == "/accounts.login" and isinstance(response.content, (bytes, str)):
            account = json.loads(response.content)
            info = account.get("sessionInfo", {})
            if account.get("errorCode") == 0 and isinstance(info, dict) and isinstance(info.get("sessionToken"), str) and isinstance(info.get("sessionSecret"), str):
                gigya_sessions[info["sessionToken"]] = {"session_secret": info["sessionSecret"], "uid": account.get("UID")}
        if request.method == "POST" and request.host == "accounts.us1.gigya.com" and route == "/accounts.getAccountInfo" and isinstance(response.content, (bytes, str)):
            account = json.loads(response.content)
            if account.get("errorCode") == 0:
                account_info_requests.append((dict(request.urlencoded_form), account.get("UID")))
        if request.method == "GET" and request.host == "disc-prod.iot.irobotapi.com" and route == "/v1/discover/endpoints":
            discovery = json.loads(response.content)
            deployments = {key: {field: value.get(field) for field in ("mqtt", "awsRegion", "svcDeplId", "irbtTopics", "iotTopics")} for key, value in discovery.get("deployments", {}).items() if isinstance(value, dict)}
        if request.method == "POST" and request.host == "unauth3.prod.iot.irobotapi.com" and route == "/v2/login":
            data = json.loads(response.content)
            candidate = data.get("credentials", {})
            if all(candidate.get(key) for key in ("AccessKeyId", "SecretKey", "SessionToken", "Expiration")):
                credentials = {key: candidate[key] for key in ("AccessKeyId", "SecretKey", "SessionToken", "Expiration")}
                connection_tokens = [{key: token.get(key) for key in ("client_id", "expires", "devices", "iot_token", "iot_signature", "iot_authorizer_name")} for token in data.get("connection_tokens", []) if isinstance(token, dict)]
                roster = data.get("robots")
                latest_identity = candidate.get("CognitoId")
                latest_login_body = json.loads(request.content) if isinstance(getattr(request, "content", None), (bytes, str)) else None
                if isinstance(latest_login_body, dict):
                    latest_login_body = {key: value for key, value in latest_login_body.items() if key in ("app_id", "app_info", "authorizer_params", "multiple_authorizer_token_support", "skip_ownership_check", "gigya")}
                    latest_login_body["gigya"] = {"uid": latest_login_body.get("gigya", {}).get("uid")}
                latest_membership = {rid: info.get("svcDeplId") for rid, info in roster.items() if isinstance(info, dict)} if isinstance(roster, dict) else {}
                login_records.append((candidate["AccessKeyId"], latest_identity, latest_membership))
                robots = [{"id": rid, "name": info.get("name"), "sku": info.get("sku"), "software_version": info.get("softwareVer"), "deployment_id": info.get("svcDeplId")} for rid, info in roster.items() if isinstance(rid, str) and isinstance(info, dict)] if isinstance(roster, dict) else []
        if request.method != "GET" or not request.host.endswith(".irobotapi.com"):
            continue
        auth = request.headers.get("authorization", "")
        if not auth.startswith("AWS4-HMAC-SHA256 "):
            continue
        scope = auth.split("Credential=", 1)[-1].split(",", 1)[0].split("/")
        if len(scope) != 5 or scope[3:] != ["execute-api", "aws4_request"]:
            continue
        item = {"method": "GET", "url": "https://" + request.host + route, "query": [list(pair) for pair in request.query.items(multi=True)], "headers": {key: request.headers.get(key, "") for key in ("accept", "content-type", "user-agent")}, "region": scope[2], "_access_key": scope[0]}
        requests.append(item)
        if route == "/v1/user/households" and isinstance(response.content, (bytes, str)):
            households = json.loads(response.content)
            if isinstance(households, list):
                for household in households:
                    if isinstance(household, dict) and isinstance(household.get("household_id"), str) and isinstance(household.get("household_robots"), list):
                        household_owners[(scope[0], household["household_id"])] = [robot["robot_id"] for robot in household["household_robots"] if isinstance(robot, dict) and isinstance(robot.get("robot_id"), str)]
        match = re.fullmatch(r'/v1/([^/]+)/pmaps', route)
        if match and isinstance(response.content, (bytes, str)):
            data = json.loads(response.content)
            if isinstance(data, list):
                for pmap in data:
                    if isinstance(pmap, dict) and isinstance(pmap.get("pmap_id"), str) and pmap.get("robot_id") == match.group(1):
                        map_owners[(scope[0], pmap["pmap_id"])] = match.group(1)
    allowed_keys = {credentials["AccessKeyId"]} if credentials else set()
    if isinstance(latest_identity, str) and latest_identity:
        allowed_keys.update(key for key, identity, membership in login_records if identity == latest_identity and membership == latest_membership)
    def proven_map_owners(pmap_id):
        return {owner for (key, mapped_id), owner in map_owners.items() if key in allowed_keys and mapped_id == pmap_id and owner in latest_membership}
    def bound_clean_score(item):
        if item["url"] != "https://auth3.prod.iot.irobotapi.com/v1/pmaps/clean-score" or len(item["query"]) != 1 or item["query"][0][0] != "pmap_id":
            return False
        return len(proven_map_owners(item["query"][0][1])) == 1
    requests = [item for item in requests if item["_access_key"] in allowed_keys or bound_clean_score(item)]
    for item in requests:
        pmap_id = next((value for key, value in item["query"] if key == "pmap_id"), None)
        if pmap_id:
            owners = proven_map_owners(pmap_id)
            item["map_robot_id"] = next(iter(owners)) if len(owners) == 1 else None
            item["owned_pmap_id"] = pmap_id
            item["binding_evidence"] = "current_account_map_ownership"
        household = re.fullmatch(r'https://auth3\.prod\.iot\.irobotapi\.com/v1/households/([^/]+)/settings/schedule', item["url"])
        if household:
            memberships = [owners for (key, household_id), owners in household_owners.items() if key in allowed_keys and household_id == household.group(1)]
            item["household_robot_ids"] = memberships[-1] if memberships else []
        del item["_access_key"]
    refresh_material = None
    expected_uid = latest_login_body.get("gigya", {}).get("uid") if isinstance(latest_login_body, dict) else None
    for params, uid in reversed(account_info_requests):
        saved = gigya_sessions.get(params.get("oauth_token"))
        if saved and uid == expected_uid == saved["uid"] and isinstance(uid, str):
            refresh_material = {"account_info_url": "https://accounts.us1.gigya.com/accounts.getAccountInfo", "account_info_params": params,
                                "session_token": params["oauth_token"], "session_secret": saved["session_secret"], "uid": uid,
                                "login_url": "https://unauth3.prod.iot.irobotapi.com/v2/login", "login_body": latest_login_body}
            break
    return {"credentials": credentials, "requests": requests, "robots": robots, "connection_tokens": connection_tokens, "deployments": deployments,
            "account_identity": latest_identity, "refresh_material": refresh_material}


if __name__ == "__main__":
    try:
        json.dump(decode(sys.argv[1:]), sys.stdout)
    except Exception:
        sys.stderr.write("Capture decoding failed\n")
        sys.exit(1)
