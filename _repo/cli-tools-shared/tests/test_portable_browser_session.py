"""Portable sessions preserve named-profile isolation, privacy, and rollback."""
import errno
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from cli_tools_shared.auth import AuthResult, BrowserAutomation, BrowserAutomationError, read_session_bundle, write_session_bundle, _session_cookie
from cli_tools_shared.config import BaseConfig, get_profiles_base_dir, get_tool_data_dir, get_cli_tools_data_root
from cli_tools_shared.credentials import CredentialType
import cli_tools_shared.auth_commands as commands
from cli_tools_shared.browser.driver import BrowserHarnessService
from cli_tools_shared.browser import BrowserHarnessError


SENTINEL = "fake-sensitive-transfer-sentinel"


def bundle():
    return {"version": 1, "tool": "sample", "profile": "account", "auth_type": "browser_session",
            "identity": {"account_id": "actor-1", "username": "owner"},
            "origins": [{"origin": "https://example.com", "localStorage": [{"key": "token", "value": SENTINEL}]}],
            "cookies": [{"name": "session", "value": SENTINEL, "domain": ".example.com", "path": "/", "secure": True, "httpOnly": True}]}


class Service:
    def __init__(self, config):
        self.config = config
        self._opened = False
        self.cookies = []
        self.storage = []

    def browser_open(self, url, **kwargs):
        self._opened = True
        directory = kwargs["persistent_profile_dir"]
        (directory / "Default").mkdir(parents=True, exist_ok=True)
        (directory / "Default" / "Cookies").write_bytes(b"fake-browser-created-state")

    def browser_close(self):
        self._opened = False

    def page_goto(self, url):
        pass

    def cookie_set(self, rows):
        self.cookies = rows

    def cookie_list(self):
        return self.cookies

    def localstorage_get(self, origin):
        return self.storage

    def localstorage_set(self, origin, rows):
        if self.config.fail_restore:
            raise RuntimeError(SENTINEL)
        self.storage = rows


class Browser(BrowserAutomation):
    AUTH_CHECK_URL = "https://example.com"

    def _get_service(self):
        if self._service is None:
            self._service = self.config.service
        return self._service

    def is_authenticated(self):
        return AuthResult(authenticated=True, live_check=True)


class Config(BaseConfig):
    CREDENTIAL_TYPES = [CredentialType.BROWSER_SESSION]
    fail_restore = False
    fail_final = False

    def __init__(self, tool_dir, profile):
        super().__init__(tool_dir=tool_dir, profile=profile)
        self.service = Service(self)

    def browser_session_origins(self):
        return ("https://example.com",)

    def browser_session_cookie_domains(self):
        return ("example.com",)

    def browser_session_identity(self, browser):
        if self.fail_final and self.get_active_profile_name() == "account":
            raise RuntimeError(SENTINEL)
        return {"account_id": "actor-1", "username": "owner"}

    def get_browser(self):
        return Browser(self)


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "runtime"))
    tool = tmp_path / "sample"
    tool.mkdir()
    monkeypatch.setattr(commands.sys, "platform", "darwin")
    monkeypatch.setattr("ctypes.CDLL", lambda *args, **kwargs: SimpleNamespace(renamex_np=True))
    monkeypatch.setattr("cli_tools_shared.browser.processes.profile_process_pids", lambda path: [])

    def exclusive(source, target):
        if Path(target).exists():
            raise FileExistsError(errno.EEXIST, "target exists")
        os.rename(source, target)

    monkeypatch.setattr(commands, "_exclusive_session_rename", exclusive)
    return tool, lambda profile=None: Config(tool, profile)


def restore(environment, payload=None):
    _, get_config = environment
    return commands._portable_profile_import(get_config, Config, "sample", "account", payload or bundle(), "actor-1", "owner")


def test_import_never_bootstraps_or_activates_default(environment):
    result = restore(environment)
    profiles = get_profiles_base_dir("sample")
    assert result["imported"] is True and result["active"] is False
    assert not (profiles / "default").exists()
    assert (profiles / "account" / ".env").read_text() == "ACTIVE=false\n"
    assert not list((get_tool_data_dir("sample") / "session-transfers").glob("*.bundle.json"))


def test_existing_profile_and_unrelated_state_unchanged(environment):
    profiles = get_profiles_base_dir("sample")
    for name in ("default", "other", "account"):
        (profiles / name).mkdir(parents=True)
        (profiles / name / ".env").write_text("ACTIVE=true\n")
    before = {path: path.read_bytes() for path in profiles.glob("*/.env")}
    with pytest.raises(BrowserAutomationError, match="already exists"):
        restore(environment)
    assert {path: path.read_bytes() for path in profiles.glob("*/.env")} == before


def test_import_keeps_other_auth_type_active_and_secret_references(environment, monkeypatch):
    monkeypatch.setattr(Config, "CREDENTIAL_TYPES", [CredentialType.CUSTOM, CredentialType.BROWSER_SESSION])
    monkeypatch.setattr(Config, "PROFILE_AUTH_TYPE_FIELD", "AUTH_TYPE", raising=False)
    monkeypatch.setattr(Config, "PROFILE_AUTH_TYPES", {"custom": [], "browser_session": []}, raising=False)
    profiles = get_profiles_base_dir("sample")
    other = profiles / "custom-account"
    other.mkdir(parents=True)
    content = "ACTIVE=true\nAUTH_TYPE=custom\nACCESS_TOKEN=secret://sample-custom-account-access-token\n"
    (other / ".env").write_text(content)
    assert restore(environment)["active"] is False
    assert (other / ".env").read_text() == content
    assert (profiles / "account" / ".env").read_text() == "ACTIVE=false\nAUTH_TYPE=browser_session\n"
    assert not (profiles / "default").exists()


@pytest.mark.parametrize("changes", [{"profile": "default"}, {"profile": "../escape"}, {"tool": "other"}, {"identity": {"account_id": "other", "username": "owner"}}])
def test_invalid_target_rejected_before_profile_creation(environment, changes):
    payload = bundle()
    payload.update(changes)
    with pytest.raises(BrowserAutomationError):
        restore(environment, payload)
    assert not get_profiles_base_dir("sample").exists()


def test_duplicate_and_oversized_json_rejected():
    with pytest.raises(BrowserAutomationError, match="Invalid"):
        read_session_bundle('{"cookies":[],"cookies":[]}')
    with pytest.raises(BrowserAutomationError, match="oversized"):
        read_session_bundle(" " * (16 * 1024 * 1024 + 1))


def test_command_help_and_invalid_input_never_construct_config(environment):
    import typer
    from typer.testing import CliRunner
    app = typer.Typer()
    calls = []
    def forbidden(profile=None):
        calls.append(profile)
        raise AssertionError("Config should not be constructed")
    commands._register_portable_session_commands(app, forbidden, Config, "sample")
    runner = CliRunner()
    for arguments in (["session-import", "--help"], ["session-export", "--help"], ["session-import-recover", "--help"]):
        assert runner.invoke(app, arguments).exit_code == 0
    for arguments, data in ((["session-import", "--profile", "default", "--expected-account-id", "actor-1", "--stdin"], "{}"),
                            (["session-import", "--profile", "account", "--expected-account-id", "actor-1", "--stdin"], SENTINEL),
                            (["session-import", "--profile", "account", "--expected-account-id", "actor-1"], "{}"),
                            (["session-export", "--profile", "account", "--expected-account-id", "actor-1", "--output", "/outside.json"], "")):
        result = runner.invoke(app, arguments, input=data)
        assert result.exit_code != 0 and SENTINEL not in result.output
    assert not calls and not get_profiles_base_dir("sample").exists()


def test_stdin_import_command_preserves_first_profile_isolation(environment):
    import typer
    from typer.testing import CliRunner
    _, factory = environment
    app = typer.Typer()
    commands._register_portable_session_commands(app, factory, Config, "sample")
    result = CliRunner().invoke(app, ["session-import", "--profile", "account", "--expected-account-id", "actor-1", "--expected-username", "owner", "--stdin"], input=json.dumps(bundle()))
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["active"] is False
    assert SENTINEL not in result.output
    assert not (get_profiles_base_dir("sample") / "default").exists()


def test_bundle_output_traversal_rejected_before_directory_creation(environment):
    root = get_cli_tools_data_root()
    escaped = root / ".." / "outside" / "private" / "bundle.json"
    with pytest.raises(BrowserAutomationError, match="runtime path"):
        write_session_bundle(escaped, bundle())
    assert not (root.parent / "outside").exists()


def test_bundle_publication_flushes_private_parent(environment, monkeypatch):
    output = get_tool_data_dir("sample") / "session-transfers" / "bundle.json"
    original = os.fsync
    import stat
    flushed = []
    def flush(descriptor):
        flushed.append(stat.S_ISDIR(os.fstat(descriptor).st_mode))
        return original(descriptor)
    monkeypatch.setattr(os, "fsync", flush)
    write_session_bundle(output, bundle())
    assert flushed == [False, True]
    assert output.stat().st_mode & 0o777 == 0o600


def test_failed_restore_retains_private_bundle_and_stage(environment, monkeypatch, capsys, caplog):
    monkeypatch.setattr(Config, "fail_restore", True)
    caplog.set_level("DEBUG")
    with pytest.raises(BrowserAutomationError, match="backup retained") as error:
        restore(environment)
    transfers = get_tool_data_dir("sample") / "session-transfers"
    journal = json.loads((transfers / "account.journal.json").read_text())
    assert journal["phase"] == "failed"
    assert Path(journal["stage"]).is_dir()
    assert not Path(journal["target"]).exists()
    assert Path(journal["backup"]).stat().st_mode & 0o777 == 0o600
    assert SENTINEL not in str(error.value) + caplog.text + str(capsys.readouterr())


@pytest.mark.parametrize("failure", ["challenge", "wrong_actor", "close"])
def test_live_identity_and_persistence_failures_never_publish(environment, monkeypatch, failure):
    if failure == "challenge":
        monkeypatch.setattr(Browser, "is_authenticated", lambda self: AuthResult(authenticated=False, live_check=True, needs_human=True))
    elif failure == "wrong_actor":
        monkeypatch.setattr(Config, "browser_session_identity", lambda self, browser: {"account_id": "foreign", "username": "owner"})
    else:
        def close(self):
            raise RuntimeError(SENTINEL)
        monkeypatch.setattr(Service, "browser_close", close)
    with pytest.raises(BrowserAutomationError, match="backup retained"):
        restore(environment)
    assert not (get_profiles_base_dir("sample") / "account").exists()
    transfers = get_tool_data_dir("sample") / "session-transfers"
    assert len(list(transfers.glob("*.bundle.json"))) == 1


def test_destination_race_never_overwrites(environment, monkeypatch):
    original = commands._exclusive_session_rename
    def race(source, target):
        Path(target).mkdir()
        (Path(target) / "foreign").write_text("unchanged")
        original(source, target)
    monkeypatch.setattr(commands, "_exclusive_session_rename", race)
    with pytest.raises(BrowserAutomationError, match="destination already exists"):
        restore(environment)
    assert (get_profiles_base_dir("sample") / "account" / "foreign").read_text() == "unchanged"


def test_post_rename_failure_rolls_back_and_recovers(environment, monkeypatch):
    monkeypatch.setattr(Config, "fail_final", True)
    with pytest.raises(BrowserAutomationError, match="backup retained"):
        restore(environment)
    assert not (get_profiles_base_dir("sample") / "account").exists()
    result = commands._recover_portable_profile("sample", "account")
    assert result["recovered"] and result["backup_retained"]
    transfers = get_tool_data_dir("sample") / "session-transfers"
    assert not (transfers / "account.journal.json").exists()
    assert len(list(transfers.glob("*.recovered.json"))) == 1
    assert len(list(transfers.glob("*.bundle.json"))) == 1


def test_parent_fsync_failure_after_publication_rolls_back(environment, monkeypatch):
    original = commands._exclusive_session_rename
    first = True
    def fail_after_rename(source, target):
        nonlocal first
        original(source, target)
        if first:
            first = False
            raise OSError("directory fsync failed after rename")
    monkeypatch.setattr(commands, "_exclusive_session_rename", fail_after_rename)
    with pytest.raises(BrowserAutomationError, match="backup retained"):
        restore(environment)
    assert not (get_profiles_base_dir("sample") / "account").exists()
    transfers = get_tool_data_dir("sample") / "session-transfers"
    journal = json.loads((transfers / "account.journal.json").read_text())
    assert journal["phase"] == "failed" and Path(journal["stage"]).is_dir()
    assert commands._recover_portable_profile("sample", "account")["backup_retained"]


def test_exclusive_rename_flushes_both_parents_and_exposes_flush_failure(tmp_path, monkeypatch):
    source_parent, target_parent = tmp_path / "source", tmp_path / "target"
    source_parent.mkdir()
    target_parent.mkdir()
    source, target = source_parent / "profile", target_parent / "profile"
    source.mkdir()
    def rename(source_bytes, target_bytes, flags):
        assert flags == 0x00000004 | 0x00000010
        os.rename(source_bytes, target_bytes)
        return 0
    monkeypatch.setattr(commands.sys, "platform", "darwin")
    monkeypatch.setattr("ctypes.CDLL", lambda *args, **kwargs: SimpleNamespace(renamex_np=rename))
    flushed = []
    original_open = os.open
    descriptors = {}
    def opened(path, flags, *args, **kwargs):
        descriptor = original_open(path, flags, *args, **kwargs)
        descriptors[descriptor] = Path(path)
        return descriptor
    monkeypatch.setattr(os, "open", opened)
    monkeypatch.setattr(os, "fsync", lambda descriptor: flushed.append(descriptors[descriptor]))
    commands._exclusive_session_rename(source, target)
    assert set(flushed) == {source_parent, target_parent}
    def fail(descriptor):
        raise OSError("injected directory fsync failure")
    monkeypatch.setattr(os, "fsync", fail)
    with pytest.raises(OSError, match="fsync"):
        commands._exclusive_session_rename(target, source)
    # The rename completed, but callers must not advance the journal on flush
    # failure; ownership inspection remains necessary at this crash boundary.
    assert source.is_dir() and not target.exists()


def test_recovery_refuses_live_staging(environment, monkeypatch):
    monkeypatch.setattr(Config, "fail_restore", True)
    with pytest.raises(BrowserAutomationError):
        restore(environment)
    monkeypatch.setattr("cli_tools_shared.browser.processes.profile_process_pids", lambda path: [123])
    with pytest.raises(BrowserAutomationError, match="live"):
        commands._recover_portable_profile("sample", "account")
    assert (get_tool_data_dir("sample") / "session-transfers" / "account.journal.json").exists()


def test_interrupted_preparation_is_journaled_and_recoverable(environment, monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError(SENTINEL)
    monkeypatch.setattr("cli_tools_shared.auth.write_session_bundle", fail)
    with pytest.raises(BrowserAutomationError):
        restore(environment)
    transfers = get_tool_data_dir("sample") / "session-transfers"
    journal = json.loads((transfers / "account.journal.json").read_text())
    assert journal["phase"] == "initializing"
    assert not Path(journal["backup"]).exists()
    assert commands._recover_portable_profile("sample", "account")["backup_retained"] is False
    assert Path(journal["stage"]).is_dir()
    assert not Path(journal["target"]).exists()


def test_complete_cleanup_failure_never_rolls_back_verified_profile(environment, monkeypatch):
    original = Path.unlink
    def fail_journal(path, *args, **kwargs):
        if path.name == "account.journal.json":
            raise OSError("simulated interrupted cleanup")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", fail_journal)
    assert restore(environment)["imported"]
    transfers = get_tool_data_dir("sample") / "session-transfers"
    assert json.loads((transfers / "account.journal.json").read_text())["phase"] == "complete"
    recovered = commands._recover_portable_profile("sample", "account")
    assert recovered["published"] and not recovered["backup_retained"]
    assert (get_profiles_base_dir("sample") / "account" / ".env").read_text() == "ACTIVE=false\n"


def test_recovery_rejects_exposed_or_aliased_state(environment, monkeypatch):
    monkeypatch.setattr(Config, "fail_restore", True)
    with pytest.raises(BrowserAutomationError):
        restore(environment)
    journal = get_tool_data_dir("sample") / "session-transfers" / "account.journal.json"
    journal.chmod(0o644)
    with pytest.raises(BrowserAutomationError, match="unsafe"):
        commands._recover_portable_profile("sample", "account")


def test_export_scopes_cookies_and_preserves_session_partition_attributes(environment):
    _, factory = environment
    profile = get_profiles_base_dir("sample") / "account"
    profile.mkdir(parents=True)
    (profile / ".env").write_text("ACTIVE=false\n")
    config = factory("account")
    config.service.browser_open("about:blank", persistent_profile_dir=config.get_persistent_profile_dir())
    scoped = {**bundle()["cookies"][0], "session": True, "expires": -1,
              "priority": "High", "sameSite": "None", "partitionKey": {"topLevelSite": "https://example.com", "hasCrossSiteAncestor": False}}
    config.service.cookies = [scoped, {**scoped, "domain": ".identity-provider.com"}]
    config.service.storage = bundle()["origins"][0]["localStorage"]
    output = get_tool_data_dir("sample") / "session-transfers" / "export.json"
    metadata = config.get_browser().export_session(output, expected_account_id="actor-1", expected_username="owner")
    exported = json.loads(output.read_text())
    assert metadata["cookies"] == 1 and SENTINEL not in json.dumps(metadata)
    assert "expires" not in exported["cookies"][0]
    assert exported["cookies"][0]["partitionKey"] == scoped["partitionKey"]
    assert output.stat().st_mode & 0o777 == 0o600
    assert (profile / ".env").read_text() == "ACTIVE=false\n"
    assert not config.service._opened


def test_persistent_and_opaque_partition_cookie_validation():
    import time
    raw = {**bundle()["cookies"][0], "expires": time.time() + 3600}
    assert _session_cookie(raw, ("example.com",))["expires"] == raw["expires"]
    with pytest.raises(BrowserAutomationError, match="Opaque"):
        _session_cookie({**raw, "partitionKeyOpaque": True}, ("example.com",), from_browser=True)
    with pytest.raises(BrowserAutomationError, match="expired"):
        _session_cookie({**raw, "expires": 1}, ("example.com",))


def test_scope_validation_and_backend_failure_are_closed(environment):
    tool, get_config = environment
    profile = get_profiles_base_dir("sample") / "account"
    profile.mkdir(parents=True)
    (profile / ".env").write_text("ACTIVE=false\n")
    browser = get_config("account").get_browser()
    for changes in ({"domain": ".unrelated.com"}, {"partitionKey": {"topLevelSite": "https://foreign.com", "hasCrossSiteAncestor": False}}):
        payload = bundle()
        payload["cookies"][0].update(changes)
        with pytest.raises(BrowserAutomationError):
            browser.import_session(payload, expected_account_id="actor-1")
        assert not (profile / "browser-data" / "chromium-profile" / "Default").exists()
    browser.config.service = SimpleNamespace()
    with pytest.raises(BrowserAutomationError, match="unsupported"):
        browser._portable_scope()


def test_non_browser_auth_type_and_symlink_source_refused_before_browser(environment, monkeypatch):
    _, factory = environment
    profile = get_profiles_base_dir("sample") / "account"
    profile.mkdir(parents=True)
    (profile / ".env").write_text("ACTIVE=false\n")
    config = factory("account")
    monkeypatch.setattr(config, "PROFILE_AUTH_TYPE_FIELD", "AUTH_TYPE", raising=False)
    monkeypatch.setattr(config, "_profile_auth_type_for_env", lambda path: "custom")
    with pytest.raises(BrowserAutomationError, match="browser_session"):
        config.get_browser()._portable_scope()
    assert not config.service._opened
    monkeypatch.setattr(config, "_profile_auth_type_for_env", lambda path: "browser_session")
    other = profile.parent / "other"
    other.mkdir()
    data = config.get_browser_data_dir()
    data.rmdir()
    data.symlink_to(other, target_is_directory=True)
    with pytest.raises(BrowserAutomationError, match="isolated"):
        config.get_browser()._portable_scope()
    assert not config.service._opened


def test_driver_setters_use_exact_cdp_contract_and_redact_errors(monkeypatch, capsys, caplog):
    service = BrowserHarnessService("portable-test")
    service._opened = True
    calls = []
    def cdp(method, **parameters):
        calls.append((method, parameters))
        return {"entries": [["key", SENTINEL]]}
    service._bh = SimpleNamespace(h=SimpleNamespace(cdp=cdp))
    monkeypatch.setattr(service, "_page_info", lambda: {"url": "https://example.com/login"})
    service.cookie_set(bundle()["cookies"])
    service.localstorage_set("https://example.com", [{"key": "key", "value": SENTINEL}])
    assert service.localstorage_get("https://example.com") == [{"key": "key", "value": SENTINEL}]
    assert [call[0] for call in calls] == ["Network.setCookies", "DOMStorage.setDOMStorageItem", "DOMStorage.getDOMStorageItems"]
    assert calls[1][1]["storageId"] == {"securityOrigin": "https://example.com", "isLocalStorage": True}
    with pytest.raises(BrowserHarnessError, match="origin mismatch"):
        service.localstorage_set("https://other.com", [])
    def fail(*args, **kwargs):
        raise RuntimeError(SENTINEL)
    service._bh.h.cdp = fail
    caplog.set_level("DEBUG")
    with pytest.raises(BrowserHarnessError) as error:
        service.cookie_set(bundle()["cookies"])
    assert SENTINEL not in str(error.value) + caplog.text + str(capsys.readouterr())


@pytest.mark.parametrize("enabled", [False, True])
def test_auth_registration_requires_explicit_portable_policy(environment, enabled):
    from typer.testing import CliRunner
    class DeclaredConfig(Config):
        PORTABLE_BROWSER_SESSION = enabled
    def forbidden(profile=None):
        raise AssertionError("Config should not be constructed for help")
    forbidden.__annotations__["return"] = DeclaredConfig
    app = commands.create_auth_app(forbidden, tool_name="sample")
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    assert ("session-export" in result.stdout) is enabled
    assert ("session-import" in result.stdout) is enabled
    assert not get_profiles_base_dir("sample").exists()


def test_frame_documents_reports_tree_and_oopif_without_private_url_fields():
    from unittest.mock import Mock
    from cli_tools_shared.browser.driver import BrowserHarnessService
    service=BrowserHarnessService('frame-diagnostic')
    service._require_open=Mock()
    service._bh=Mock()
    service._bh.h.cdp.side_effect=[{'frameTree':{'frame':{'id':'root','url':'https://whop.com/shell?token=SECRET#SECRET'},'childFrames':[{'frame':{'id':'child','parentId':'root','url':'https://app.apps.whop.com/c/exp_TEST/settings?token=SECRET'}}]}},
                                 {'targetInfos':[{'type':'iframe','targetId':'oop','url':'https://app.apps.whop.com/c/exp_TEST/settings#SECRET'},{'type':'page','targetId':'other','url':'https://private.test/'}]}]
    rows=service.frame_documents()
    assert [r['id'] for r in rows]==['root','child','oop']
    assert rows[1]['parent_id']=='root' and rows[1]['origin']=='https://app.apps.whop.com'
    assert 'SECRET' not in str(rows) and 'private.test' not in str(rows)
    assert service._bh.h.cdp.call_args_list[0].args==('Page.getFrameTree',)


def test_frame_documents_bounds_tree_size():
    from unittest.mock import Mock
    from cli_tools_shared.browser.driver import BrowserHarnessService
    from cli_tools_shared.browser import BrowserHarnessError
    service=BrowserHarnessService('frame-diagnostic');service._require_open=Mock();service._bh=Mock()
    service._bh.h.cdp.return_value={'frameTree':{'frame':{'id':'root'},'childFrames':[{'frame':{'id':str(i)}} for i in range(128)]}}
    with pytest.raises(BrowserHarnessError,match='frame_document_limit_exceeded'):
        service.frame_documents()


def test_frame_navigation_requires_exact_current_origin():
    from unittest.mock import Mock
    from cli_tools_shared.browser.driver import BrowserHarnessService
    from cli_tools_shared.browser import BrowserHarnessError
    service=BrowserHarnessService('frame-navigation');service._bh=Mock()
    service.frame_documents=Mock(return_value=[{'id':'frame','kind':'frame','origin':'https://app.apps.whop.com','path':'/c/exp_TEST/discover'}])
    service._bh.h.cdp.return_value={}
    service.goto_frame('frame','https://app.apps.whop.com/c/exp_TEST/settings')
    service._bh.h.cdp.assert_called_once_with('Page.navigate',session_id=None,frameId='frame',url='https://app.apps.whop.com/c/exp_TEST/settings')
    service._bh.h.cdp.reset_mock()
    with pytest.raises(BrowserHarnessError,match='origin_mismatch'):
        service.goto_frame('frame','https://wrong.apps.whop.com/c/exp_TEST/settings')
    service._bh.h.cdp.assert_not_called()


def test_oopif_navigation_attaches_and_detaches_only_requested_target():
    from unittest.mock import Mock,call
    from cli_tools_shared.browser.driver import BrowserHarnessService
    service=BrowserHarnessService('frame-navigation');service._bh=Mock()
    service.frame_documents=Mock(return_value=[{'id':'oop','kind':'iframe_target','origin':'https://app.apps.whop.com','path':'/c/exp_TEST/discover'}])
    service._bh.h.cdp.side_effect=[{'sessionId':'sid'},{},{}]
    service.goto_frame('oop','https://app.apps.whop.com/c/exp_TEST/settings')
    assert service._bh.h.cdp.call_args_list==[call('Target.attachToTarget',targetId='oop',flatten=True),call('Page.navigate',session_id='sid',frameId='oop',url='https://app.apps.whop.com/c/exp_TEST/settings'),call('Target.detachFromTarget',sessionId='sid')]


@pytest.mark.parametrize('url',['https://private.test:SECRET/path','https://[SECRET/path'])
def test_frame_diagnostic_malformed_url_never_echoed(url):
    from unittest.mock import Mock
    from cli_tools_shared.browser.driver import BrowserHarnessService
    from cli_tools_shared.browser import BrowserHarnessError
    service=BrowserHarnessService('frame-diagnostic');service._require_open=Mock();service._bh=Mock()
    service._bh.h.cdp.return_value={'frameTree':{'frame':{'id':'root','url':url}}}
    with pytest.raises(BrowserHarnessError,match='frame_document_url_invalid') as error:
        service.frame_documents()
    assert 'SECRET' not in str(error.value)


def test_frame_navigation_budget_reaches_every_cdp_call():
    from unittest.mock import Mock
    from cli_tools_shared.browser.driver import BrowserHarnessService
    service=BrowserHarnessService('frame-deadline');service._require_open=Mock();service._bh=Mock()
    service._bh.h.cdp.side_effect=[{'frameTree':{'frame':{'id':'root','url':'https://app.apps.whop.com/c/exp_TEST/discover'}}},{'targetInfos':[]},{}]
    service.goto_frame('root','https://app.apps.whop.com/c/exp_TEST/settings',request_timeout=.5)
    calls=service._bh.h.cdp.call_args_list
    assert [c.args[0] for c in calls]==['Page.getFrameTree','Target.getTargets','Page.navigate']
    budgets=[c.kwargs['request_timeout'] for c in calls]
    assert .5>=budgets[0]>=budgets[1]>=budgets[2]>0
    assert calls[-1].kwargs['frameId']=='root'


@pytest.mark.parametrize('oop',[False,True])
def test_bounded_frame_evaluation_keeps_exact_context_and_budget(oop):
    from unittest.mock import Mock
    from cli_tools_shared.browser.driver import BrowserHarnessService
    service=BrowserHarnessService('frame-evaluation');service._require_open=Mock();service._bh=Mock()
    service.frame_documents=Mock(return_value=[{'id':'selected','origin':'https://app.apps.whop.com','path':'/c/exp_TEST/settings','kind':'iframe_target' if oop else 'frame'}])
    service._bh.h.cdp.side_effect=[{'sessionId':'exact-sid'} if oop else {'executionContextId':42},{'result':{'value':True}}]+([{}] if oop else [])
    assert service.evaluate_in_iframe('https://app.apps.whop.com/c/exp_TEST/settings','() => true',request_timeout=.5) is True
    calls=service._bh.h.cdp.call_args_list
    evaluate=next(c for c in calls if c.args[0]=='Runtime.evaluate')
    assert evaluate.kwargs['session_id']==('exact-sid' if oop else None)
    assert evaluate.kwargs.get('contextId')==(None if oop else 42)
    assert all(0<c.kwargs['request_timeout']<=.5 for c in calls)
    if oop:assert calls[-1].kwargs['sessionId']=='exact-sid'


@pytest.mark.parametrize('operation',['navigate','evaluate'])
def test_expired_frame_operation_detaches_only_owned_session_preserving_error(monkeypatch,operation):
    from unittest.mock import Mock
    from cli_tools_shared.browser.driver import BrowserHarnessService
    from cli_tools_shared.browser import BrowserHarnessError
    from cli_tools_shared.browser import driver
    clock=[0.0];monkeypatch.setattr(driver.time,'monotonic',lambda:clock[0])
    service=BrowserHarnessService('frame-cleanup');service._require_open=Mock();service._bh=Mock()
    service.frame_documents=Mock(return_value=[{'id':'owned-target','origin':'https://app.apps.whop.com','path':'/c/exp_TEST/settings','kind':'iframe_target'}])
    calls=[]
    def cdp(method,**params):
        calls.append((method,params))
        if method=='Target.attachToTarget':return {'sessionId':'owned-session'}
        if method in ('Page.navigate','Runtime.evaluate'):
            clock[0]=1.0
            raise TimeoutError('SECRET primary timeout')
        if method=='Target.detachFromTarget':return {}
        raise AssertionError(method)
    service._bh.h.cdp.side_effect=cdp
    with pytest.raises(BrowserHarnessError,match='frame_cdp_request_failed') as error:
        if operation=='navigate':service.goto_frame('owned-target','https://app.apps.whop.com/c/exp_TEST/settings',request_timeout=.1)
        else:service.evaluate_in_iframe('https://app.apps.whop.com/c/exp_TEST/settings','() => true',request_timeout=.1)
    assert 'SECRET' not in str(error.value)
    assert calls[-1][0]=='Target.detachFromTarget'
    assert calls[-1][1]['sessionId']=='owned-session'
    assert 0<calls[-1][1]['request_timeout']<=.25
