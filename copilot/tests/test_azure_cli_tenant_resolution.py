import json
import subprocess

import pytest

from cli_tools_shared.exceptions import CredentialError

from copilot_cli import client as copilot_client
from copilot_cli import main as copilot_main
from copilot_cli.config import _reset_config


# ---------------------------------------------------------------------------
# Shared fixtures/helpers
# ---------------------------------------------------------------------------


def _setup_profiles_dir(tmp_path, monkeypatch):
    """Point cli-tools user data at tmp_path and return the profiles dir."""
    data_home = tmp_path / "data"
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.delenv("COPILOT_CONFIG_DIR", raising=False)
    monkeypatch.delenv("COPILOT_CACHE_DIR", raising=False)
    profiles = data_home / "cli-tools" / "copilot" / "authentication_profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    _reset_config()
    return profiles


def _write_profile(path, *, active, dataverse_url, tenant_id=None, expected_user=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"ACTIVE={'true' if active else 'false'}",
        f"DATAVERSE_URL={dataverse_url}",
    ]
    if tenant_id is not None:
        lines.append(f"AZURE_TENANT_ID={tenant_id}")
    if expected_user is not None:
        lines.append(f"AZURE_CLI_EXPECTED_USER={expected_user}")
    path.write_text("\n".join(lines) + "\n")


class FakeResult:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _az_subcommand(args):
    """Extract a dispatch signature from an az argv list, e.g.
    ['az', 'account', 'list', '-o', 'json'] -> ('account', 'list')."""
    rest = list(args[1:])
    if not rest:
        return ()
    if rest[0] == "--version":
        return ("--version",)
    if rest[0] in ("login", "logout"):
        return (rest[0],)
    if len(rest) >= 2:
        return (rest[0], rest[1])
    return (rest[0],)


def _make_fake_run(table, calls=None):
    """Build a subprocess.run replacement driven by a signature -> FakeResult
    (or list-of-FakeResult, popped in call order) table. Records every argv
    list into `calls` when provided. Raises CalledProcessError when the
    caller passes check=True and the matched result has a nonzero
    returncode, mirroring real subprocess.run (a bare nonzero-returncode
    double does not auto-raise otherwise). Unregistered signatures raise
    AssertionError so an unexpected az call fails the test loudly.
    """
    counters = {}

    def fake_run(args, **kwargs):
        if calls is not None:
            calls.append(list(args))
        sig = _az_subcommand(args)
        entry = table.get(sig)
        if entry is None:
            raise AssertionError(f"Unexpected subprocess call for signature {sig}: {args}")
        if isinstance(entry, list):
            idx = counters.get(sig, 0)
            counters[sig] = idx + 1
            result = entry[idx]
        else:
            result = entry
        if kwargs.get("check") and result.returncode != 0:
            raise subprocess.CalledProcessError(
                result.returncode, args, output=result.stdout, stderr=result.stderr
            )
        return result

    return fake_run


# ---------------------------------------------------------------------------
# _find_cached_azure_account
# ---------------------------------------------------------------------------


def test_find_cached_azure_account_matches_tenant_and_user(monkeypatch):
    accounts = [
        {"id": "sub-a", "tenantId": "tenant-a", "isDefault": True, "user": {"name": "user-a@example.com"}},
        {"id": "sub-b", "tenantId": "tenant-b", "isDefault": False, "user": {"name": "user-b@example.com"}},
    ]
    monkeypatch.setattr(
        copilot_client.subprocess, "run",
        _make_fake_run({("account", "list"): FakeResult(stdout=json.dumps(accounts))}),
    )
    result = copilot_client._find_cached_azure_account("az", "tenant-b", "user-b@example.com")
    assert result["id"] == "sub-b"


def test_find_cached_azure_account_prefers_is_default_among_matches(monkeypatch):
    accounts = [
        {"id": "sub-1", "tenantId": "tenant-a", "isDefault": False, "user": {"name": "user1@example.com"}},
        {"id": "sub-2", "tenantId": "tenant-a", "isDefault": True, "user": {"name": "user2@example.com"}},
    ]
    monkeypatch.setattr(
        copilot_client.subprocess, "run",
        _make_fake_run({("account", "list"): FakeResult(stdout=json.dumps(accounts))}),
    )
    result = copilot_client._find_cached_azure_account("az", "tenant-a")
    assert result["id"] == "sub-2"


def test_find_cached_azure_account_filters_by_user_when_given(monkeypatch):
    accounts = [
        {"id": "sub-1", "tenantId": "tenant-a", "isDefault": False, "user": {"name": "user1@example.com"}},
        {"id": "sub-2", "tenantId": "tenant-a", "isDefault": False, "user": {"name": "user2@example.com"}},
    ]
    monkeypatch.setattr(
        copilot_client.subprocess, "run",
        _make_fake_run({("account", "list"): FakeResult(stdout=json.dumps(accounts))}),
    )
    result = copilot_client._find_cached_azure_account("az", "tenant-a", "user2@example.com")
    assert result["id"] == "sub-2"


def test_find_cached_azure_account_returns_none_when_no_tenant_match(monkeypatch):
    accounts = [{"id": "x", "tenantId": "other-tenant", "user": {"name": "a@example.com"}}]
    monkeypatch.setattr(
        copilot_client.subprocess, "run",
        _make_fake_run({("account", "list"): FakeResult(stdout=json.dumps(accounts))}),
    )
    assert copilot_client._find_cached_azure_account("az", "tenant-a") is None


def test_find_cached_azure_account_returns_none_on_nonzero_exit(monkeypatch):
    monkeypatch.setattr(
        copilot_client.subprocess, "run",
        _make_fake_run({("account", "list"): FakeResult(returncode=1, stderr="not logged in")}),
    )
    assert copilot_client._find_cached_azure_account("az", "tenant-a") is None


def test_find_cached_azure_account_returns_none_on_malformed_json(monkeypatch):
    monkeypatch.setattr(
        copilot_client.subprocess, "run",
        _make_fake_run({("account", "list"): FakeResult(stdout="not json")}),
    )
    assert copilot_client._find_cached_azure_account("az", "tenant-a") is None


def test_find_cached_azure_account_returns_none_on_non_list_json(monkeypatch):
    monkeypatch.setattr(
        copilot_client.subprocess, "run",
        _make_fake_run({("account", "list"): FakeResult(stdout=json.dumps({"not": "a list"}))}),
    )
    assert copilot_client._find_cached_azure_account("az", "tenant-a") is None


def test_find_cached_azure_account_handles_null_tenant_and_user_fields(monkeypatch):
    accounts = [
        {"id": "sub-1", "tenantId": None, "user": None},
        {"id": "sub-2", "tenantId": "tenant-a", "isDefault": True, "user": {"name": "user2@example.com"}},
    ]
    monkeypatch.setattr(
        copilot_client.subprocess, "run",
        _make_fake_run({("account", "list"): FakeResult(stdout=json.dumps(accounts))}),
    )
    result = copilot_client._find_cached_azure_account("az", "tenant-a")
    assert result["id"] == "sub-2"


# ---------------------------------------------------------------------------
# get_access_token_from_azure_cli
# ---------------------------------------------------------------------------


def test_get_access_token_uses_cached_non_default_account_for_tenant(tmp_path, monkeypatch):
    profiles = _setup_profiles_dir(tmp_path, monkeypatch)
    _write_profile(
        profiles / "psdxautomation" / ".env",
        active=True,
        dataverse_url="https://progress.example.crm.dynamics.com",
        tenant_id="tenant-progress",
        expected_user="psdxautomation@progress.com",
    )

    accounts = [
        {"id": "sub-personal", "tenantId": "tenant-personal", "isDefault": True,
         "user": {"name": "adam@adamtheautomator.com"}},
        {"id": "sub-progress", "tenantId": "tenant-progress", "isDefault": False,
         "user": {"name": "psdxautomation@progress.com"}},
    ]
    calls = []
    fake_run = _make_fake_run(
        {
            ("account", "list"): FakeResult(stdout=json.dumps(accounts)),
            ("account", "get-access-token"): FakeResult(stdout="fake-token\n"),
        },
        calls=calls,
    )
    monkeypatch.setattr(copilot_client.subprocess, "run", fake_run)

    token = copilot_client.get_access_token_from_azure_cli("https://example.com/.default")

    assert token == "fake-token"
    token_call = next(c for c in calls if _az_subcommand(c) == ("account", "get-access-token"))
    assert "--subscription" in token_call
    assert token_call[token_call.index("--subscription") + 1] == "sub-progress"
    # Regression guard: must never touch the machine-wide default account.
    assert all(_az_subcommand(c) != ("account", "show") for c in calls)


def test_get_access_token_actionable_error_when_no_cached_match_and_user_expected(tmp_path, monkeypatch):
    profiles = _setup_profiles_dir(tmp_path, monkeypatch)
    _write_profile(
        profiles / "psdxautomation" / ".env",
        active=True,
        dataverse_url="https://progress.example.crm.dynamics.com",
        tenant_id="tenant-progress",
        expected_user="psdxautomation@progress.com",
    )

    accounts = [{"id": "sub-personal", "tenantId": "tenant-personal", "isDefault": True,
                 "user": {"name": "adam@adamtheautomator.com"}}]
    fake_run = _make_fake_run(
        {
            ("account", "list"): FakeResult(stdout=json.dumps(accounts)),
            ("account", "show"): FakeResult(stdout="adam@adamtheautomator.com\n"),
        }
    )
    monkeypatch.setattr(copilot_client.subprocess, "run", fake_run)

    with pytest.raises(CredentialError) as exc_info:
        copilot_client.get_access_token_from_azure_cli("https://example.com/.default")
    message = str(exc_info.value)
    assert "Azure CLI is logged in as 'adam@adamtheautomator.com'" in message
    assert "requires 'psdxautomation@progress.com'" in message
    assert "az login --tenant tenant-progress" in message


def test_get_access_token_falls_back_to_generic_error_when_not_logged_in_at_all(tmp_path, monkeypatch):
    profiles = _setup_profiles_dir(tmp_path, monkeypatch)
    _write_profile(
        profiles / "psdxautomation" / ".env",
        active=True,
        dataverse_url="https://progress.example.crm.dynamics.com",
        tenant_id="tenant-progress",
        expected_user="psdxautomation@progress.com",
    )

    fake_run = _make_fake_run(
        {
            ("account", "list"): FakeResult(stdout=json.dumps([])),
            ("account", "show"): FakeResult(returncode=1, stderr="ERROR: Please run 'az login'"),
        }
    )
    monkeypatch.setattr(copilot_client.subprocess, "run", fake_run)

    with pytest.raises(CredentialError, match="Failed to get access token"):
        copilot_client.get_access_token_from_azure_cli("https://example.com/.default")


def test_get_access_token_new_error_when_no_cached_match_and_no_user_expected(tmp_path, monkeypatch):
    profiles = _setup_profiles_dir(tmp_path, monkeypatch)
    _write_profile(
        profiles / "tenant-only" / ".env",
        active=True,
        dataverse_url="https://example.crm.dynamics.com",
        tenant_id="tenant-progress",
    )

    fake_run = _make_fake_run({("account", "list"): FakeResult(stdout=json.dumps([]))})
    monkeypatch.setattr(copilot_client.subprocess, "run", fake_run)

    with pytest.raises(CredentialError, match="No cached Azure CLI login found for tenant 'tenant-progress'"):
        copilot_client.get_access_token_from_azure_cli("https://example.com/.default")


def test_get_access_token_legacy_success_without_tenant_id(tmp_path, monkeypatch):
    profiles = _setup_profiles_dir(tmp_path, monkeypatch)
    _write_profile(
        profiles / "legacy" / ".env",
        active=True,
        dataverse_url="https://example.crm.dynamics.com",
        expected_user="someone@example.com",
    )

    calls = []
    fake_run = _make_fake_run(
        {
            ("account", "show"): FakeResult(stdout="someone@example.com\n"),
            ("account", "get-access-token"): FakeResult(stdout="legacy-token\n"),
        },
        calls=calls,
    )
    monkeypatch.setattr(copilot_client.subprocess, "run", fake_run)

    token = copilot_client.get_access_token_from_azure_cli("https://example.com/.default")

    assert token == "legacy-token"
    assert all(_az_subcommand(c) != ("account", "list") for c in calls)
    token_call = next(c for c in calls if _az_subcommand(c) == ("account", "get-access-token"))
    assert "--subscription" not in token_call


def test_get_access_token_legacy_mismatch_uses_original_message(tmp_path, monkeypatch):
    profiles = _setup_profiles_dir(tmp_path, monkeypatch)
    _write_profile(
        profiles / "legacy" / ".env",
        active=True,
        dataverse_url="https://example.crm.dynamics.com",
        expected_user="someone@example.com",
    )

    fake_run = _make_fake_run({("account", "show"): FakeResult(stdout="someone-else@example.com\n")})
    monkeypatch.setattr(copilot_client.subprocess, "run", fake_run)

    with pytest.raises(CredentialError) as exc_info:
        copilot_client.get_access_token_from_azure_cli("https://example.com/.default")
    message = str(exc_info.value)
    assert (
        "Azure CLI is logged in as 'someone-else@example.com' but profile "
        "'legacy' requires 'someone@example.com'." in message
    )
    assert "az login --tenant <tenant-id>" in message


def test_get_access_token_no_tenant_no_expected_user_skips_identity_check(tmp_path, monkeypatch):
    profiles = _setup_profiles_dir(tmp_path, monkeypatch)
    _write_profile(profiles / "bare" / ".env", active=True, dataverse_url="https://example.crm.dynamics.com")

    calls = []
    fake_run = _make_fake_run({("account", "get-access-token"): FakeResult(stdout="bare-token\n")}, calls=calls)
    monkeypatch.setattr(copilot_client.subprocess, "run", fake_run)

    token = copilot_client.get_access_token_from_azure_cli("https://example.com/.default")

    assert token == "bare-token"
    assert all(_az_subcommand(c) not in (("account", "show"), ("account", "list")) for c in calls)


# ---------------------------------------------------------------------------
# _resolve_login_identity
# ---------------------------------------------------------------------------


def test_resolve_login_identity_uses_cached_non_default_account_without_az_login(monkeypatch):
    calls = []
    accounts = [
        {"id": "sub-progress", "tenantId": "tenant-progress", "isDefault": False,
         "user": {"name": "psdxautomation@progress.com"}},
    ]
    fake_run = _make_fake_run(
        {
            ("account", "show"): FakeResult(
                stdout=json.dumps({"user": {"name": "adam@adamtheautomator.com"}, "tenantId": "tenant-personal"})
            ),
            ("account", "list"): FakeResult(stdout=json.dumps(accounts)),
        },
        calls=calls,
    )
    monkeypatch.setattr(copilot_client.subprocess, "run", fake_run)

    user, tenant = copilot_main._resolve_login_identity(
        "az", "psdxautomation@progress.com", "tenant-progress", force=False
    )

    assert user == "psdxautomation@progress.com"
    assert tenant == "tenant-progress"
    assert any(_az_subcommand(c) == ("account", "list") for c in calls)
    assert all(_az_subcommand(c) != ("login",) for c in calls)


def test_resolve_login_identity_force_skips_cached_shortcut_and_logs_in(monkeypatch):
    calls = []
    fake_run = _make_fake_run(
        {
            ("logout",): FakeResult(),
            ("account", "show"): [
                FakeResult(returncode=1, stderr="ERROR: Please run 'az login'"),
                FakeResult(stdout=json.dumps(
                    {"user": {"name": "psdxautomation@progress.com"}, "tenantId": "tenant-progress"}
                )),
            ],
            ("login",): FakeResult(),
        },
        calls=calls,
    )
    monkeypatch.setattr(copilot_client.subprocess, "run", fake_run)

    user, tenant = copilot_main._resolve_login_identity(
        "az", "psdxautomation@progress.com", "tenant-progress", force=True
    )

    assert user == "psdxautomation@progress.com"
    assert tenant == "tenant-progress"
    logout_call = next(c for c in calls if _az_subcommand(c) == ("logout",))
    assert "--username" in logout_call
    assert logout_call[logout_call.index("--username") + 1] == "psdxautomation@progress.com"
    assert any(_az_subcommand(c) == ("login",) for c in calls)
    # --force must skip the cached-account shortcut entirely.
    assert all(_az_subcommand(c) != ("account", "list") for c in calls)


def test_resolve_login_identity_falls_through_to_az_login_when_no_cached_match(monkeypatch):
    calls = []
    fake_run = _make_fake_run(
        {
            ("account", "show"): [
                FakeResult(stdout=json.dumps(
                    {"user": {"name": "adam@adamtheautomator.com"}, "tenantId": "tenant-personal"}
                )),
                FakeResult(stdout=json.dumps(
                    {"user": {"name": "psdxautomation@progress.com"}, "tenantId": "tenant-progress"}
                )),
            ],
            ("account", "list"): FakeResult(stdout=json.dumps([])),
            ("login",): FakeResult(),
        },
        calls=calls,
    )
    monkeypatch.setattr(copilot_client.subprocess, "run", fake_run)

    user, tenant = copilot_main._resolve_login_identity(
        "az", "psdxautomation@progress.com", "tenant-progress", force=False
    )

    assert user == "psdxautomation@progress.com"
    login_call = next(c for c in calls if _az_subcommand(c) == ("login",))
    assert "--tenant" in login_call
    assert login_call[login_call.index("--tenant") + 1] == "tenant-progress"


def test_resolve_login_identity_raises_systemexit_when_still_mismatched_after_login(monkeypatch):
    fake_run = _make_fake_run(
        {
            ("account", "show"): FakeResult(
                stdout=json.dumps({"user": {"name": "someone-else@example.com"}, "tenantId": "tenant-wrong"})
            ),
            ("account", "list"): FakeResult(stdout=json.dumps([])),
            ("login",): FakeResult(),
        }
    )
    monkeypatch.setattr(copilot_client.subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as exc_info:
        copilot_main._resolve_login_identity("az", "psdxautomation@progress.com", "tenant-progress", force=False)
    assert exc_info.value.code == 1


def test_resolve_login_identity_legacy_no_tenant_configured(monkeypatch):
    calls = []
    fake_run = _make_fake_run(
        {
            ("account", "show"): FakeResult(
                stdout=json.dumps({"user": {"name": "someone@example.com"}, "tenantId": "any-tenant"})
            ),
        },
        calls=calls,
    )
    monkeypatch.setattr(copilot_client.subprocess, "run", fake_run)

    user, tenant = copilot_main._resolve_login_identity("az", "someone@example.com", None, force=False)

    assert user == "someone@example.com"
    assert all(_az_subcommand(c) != ("account", "list") for c in calls)


# ---------------------------------------------------------------------------
# _copilot_login_handler (light integration — wiring only)
# ---------------------------------------------------------------------------


def test_copilot_login_handler_wires_resolved_identity_through(monkeypatch):
    fake_run = _make_fake_run({("--version",): FakeResult()})
    monkeypatch.setattr(copilot_client.subprocess, "run", fake_run)
    monkeypatch.setattr(
        copilot_main,
        "_resolve_login_identity",
        lambda az, expected_user, expected_tenant, force: ("psdxautomation@progress.com", "tenant-progress"),
    )
    monkeypatch.setattr(copilot_main, "_copilot_test_handler", lambda config: {"api_test": "passed"})

    class FakeConfig:
        expected_user = "psdxautomation@progress.com"
        tenant_id = "tenant-progress"

        def has_credentials(self):
            return True

        def get_active_profile_name(self):
            return "psdxautomation"

    copilot_main._copilot_login_handler(FakeConfig(), force=False)
