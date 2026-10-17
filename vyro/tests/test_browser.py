import json
import shutil
import subprocess

import pytest

from vyro_cli.browser import AUTH_CONTEXT_URL, VyroBrowser
from vyro_cli.config import Config


def _run_auth_probe(fetch_body: str) -> dict:
    node = shutil.which("node")
    assert node, "Node is required to validate the browser auth probe"
    script = f"""
    let request;
    global.fetch = async (url, options) => {{
        request = {{url, options}};
        {fetch_body}
    }};
    const probe = ({VyroBrowser.AUTH_FAILURE_PAGE_JS});
    probe().then(failed => console.log(JSON.stringify({{
        failed,
        url: request?.url,
        method: request?.options?.method,
        credentials: request?.options?.credentials,
        realm: request?.options?.headers?.['x-realm'],
        timeout: request?.options?.signal instanceof AbortSignal,
    }})));
    """
    result = subprocess.run(
        [node], input=script, text=True, capture_output=True, check=True
    )
    return json.loads(result.stdout)


def test_auth_probe_accepts_live_refresh_and_uses_vyro_contract():
    result = _run_auth_probe(
        "return {ok: true, json: async () => ({accessToken: 'live'})};"
    )
    assert result == {
        "failed": False,
        "url": "https://api.vyro.com/auth/refresh",
        "method": "POST",
        "credentials": "include",
        "realm": "vyro-app",
        "timeout": True,
    }


@pytest.mark.parametrize(
    "fetch_body",
    [
        "return {ok: false, status: 401, json: async () => ({errorCode: 'SESSION_REJECTED'})};",
        "return {ok: true, json: async () => ({})};",
        "return {ok: true, json: async () => ({accessToken: ''})};",
        "throw new Error('network unavailable');",
    ],
)
def test_auth_probe_rejects_unusable_refresh(fetch_body):
    assert _run_auth_probe(fetch_body)["failed"] in {
        "http_status_401_code_session_rejected",
        "missing_access_token",
        "request_failed",
    }


def test_auth_probe_does_not_trust_refresh_cookie_presence():
    assert VyroBrowser.AUTH_COOKIE_PATTERNS == []
    assert VyroBrowser.AUTH_CHECK_URL == AUTH_CONTEXT_URL


def test_vyro_uses_installed_chrome_user_agent_for_headless_reads(monkeypatch):
    monkeypatch.setattr(
        "vyro_cli.config.derive_real_chrome_user_agent",
        lambda: (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/155.0.8059.84 Safari/537.36"
        ),
    )
    assert Config().browser_user_agent.endswith(
        "Chrome/155.0.0.0 Safari/537.36"
    )
