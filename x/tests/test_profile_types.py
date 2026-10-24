"""X profile authentication and registry integration regressions."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

from cli_tools_shared.auth_verifier import AuthVerifier
from cli_tools_shared.config import BaseConfig
from cli_tools_shared.credentials import CredentialType
from typer.testing import CliRunner

from x_cli import config as x_config


def test_browser_profile_does_not_claim_api_credentials(monkeypatch, tmp_path):
    monkeypatch.setattr(x_config, 'resolve_tool_dir', lambda _: tmp_path / 'x')
    monkeypatch.setattr(x_config, '_migrate_legacy_profiles', lambda _: None)
    monkeypatch.setattr(BaseConfig, '__init__', lambda *args, **kwargs: None)
    monkeypatch.setattr(x_config.Config, '_get', lambda self, field: 'browser_session' if field == 'AUTH_TYPE' else None)
    config = x_config.Config(profile='browser')
    assert config.CREDENTIAL_TYPES == [CredentialType.BROWSER_SESSION]
    assert x_config.Config.CREDENTIAL_TYPES == [CredentialType.CUSTOM, CredentialType.BROWSER_SESSION]
    verifier = AuthVerifier(config)
    monkeypatch.setattr(verifier, '_check_browser', lambda: {'has_session': True, 'authenticated': True, 'available': True})
    api_check = Mock()
    monkeypatch.setattr(verifier, '_check_api', api_check)
    result = verifier.verify()
    assert result['authenticated'] is True
    assert set(result['credential_types']) == {'browser_session'}
    api_check.assert_not_called()


def test_api_profile_does_not_probe_browser(monkeypatch, tmp_path):
    monkeypatch.setattr(x_config, 'resolve_tool_dir', lambda _: tmp_path / 'x')
    monkeypatch.setattr(x_config, '_migrate_legacy_profiles', lambda _: None)
    monkeypatch.setattr(BaseConfig, '__init__', lambda *args, **kwargs: None)
    monkeypatch.setattr(x_config.Config, '_get', lambda self, field: 'custom' if field == 'AUTH_TYPE' else 'saved')
    config = x_config.Config(profile='default')
    verifier = AuthVerifier(config)
    monkeypatch.setattr(verifier, '_check_api', lambda: {'api_test': 'passed'})
    browser_check = Mock()
    monkeypatch.setattr(verifier, '_check_browser', browser_check)
    result = verifier.verify()
    assert result['authenticated'] is True
    assert set(result['credential_types']) == {'custom'}
    browser_check.assert_not_called()


def test_cache_defaults_to_api_but_honors_explicit_profile(monkeypatch):
    resolve = Mock()
    monkeypatch.setattr(x_config, 'get_config', resolve)
    x_config.get_cache_config()
    resolve.assert_called_with(profile=None, profile_auth_type='custom')
    x_config.get_cache_config('browser')
    resolve.assert_called_with(profile='browser', profile_auth_type=None)


def test_root_analytics_bearer_request_through_registry_without_oauth(monkeypatch):
    from x_cli.main import app
    from x_cli.commands import analytics
    import cli_tools_shared.command_registry as registry
    from x_cli.client import XClient

    assert CredentialType.CUSTOM.required_fields == []
    resolve = Mock(return_value=('default', 'custom'))
    monkeypatch.setattr(registry, '_resolve_runtime_profile_context', resolve)
    settings = SimpleNamespace(has_api_credentials=lambda: False, get_missing_api_credentials=lambda: ['X_CONSUMER_KEY'], bearer_token='test-bearer', base_url='https://api.x.com')
    monkeypatch.setattr(analytics, 'get_config', lambda **kwargs: settings)
    request = Mock(return_value={'data': {'project_usage': 3}})
    monkeypatch.setattr(XClient, '_make_request', request)
    result = CliRunner().invoke(app, ['analytics', 'usage', '--days', '1'])
    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout)['data']['project_usage'] == 3
    resolve.assert_called_once()
    request.assert_called_once()


def test_bearer_only_profile_is_saved_and_live_verified(monkeypatch, tmp_path):
    monkeypatch.setattr(x_config, 'resolve_tool_dir', lambda _: tmp_path / 'x')
    monkeypatch.setattr(x_config, '_migrate_legacy_profiles', lambda _: None)
    monkeypatch.setattr(BaseConfig, '__init__', lambda *args, **kwargs: None)
    values = {'AUTH_TYPE': 'custom', 'X_BEARER_TOKEN': 'test-bearer'}
    monkeypatch.setattr(x_config.Config, '_get', lambda self, field: values.get(field))
    settings = x_config.Config(profile='api')
    assert settings.has_credentials() is True
    assert settings.get_missing_credentials() == []
    assert settings.CUSTOM_REQUIRED_FIELDS == ['AUTH_TYPE', 'X_BEARER_TOKEN']
    from x_cli.client import XClient
    request = Mock(return_value={'data': {'remaining_credits': 123}})
    monkeypatch.setattr(XClient, '_make_request', request)
    status = AuthVerifier(settings).verify()
    block = status['credential_types']['custom']
    assert block['credentials_saved'] is True
    assert block['authenticated'] is True
    assert block['api_test'] == 'passed'
    assert block['auth_method'] == 'bearer'
    request.assert_called_once_with('GET', '/2/usage/credits')


def test_bearer_only_verification_preserves_api_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(x_config, 'resolve_tool_dir', lambda _: tmp_path / 'x')
    monkeypatch.setattr(x_config, '_migrate_legacy_profiles', lambda _: None)
    monkeypatch.setattr(BaseConfig, '__init__', lambda *args, **kwargs: None)
    values = {'AUTH_TYPE': 'custom', 'X_BEARER_TOKEN': 'test-bearer'}
    monkeypatch.setattr(x_config.Config, '_get', lambda self, field: values.get(field))
    from x_cli.client import XClient
    monkeypatch.setattr(XClient, '_make_request', lambda *args, **kwargs: {'errors': [{'detail': 'access denied'}]})
    status = AuthVerifier(x_config.Config(profile='api')).verify()
    block = status['credential_types']['custom']
    assert block['authenticated'] is False
    assert block['api_test'].startswith('failed:')


def test_bearer_token_command_saves_via_managed_profile_without_echo(monkeypatch):
    from x_cli.commands import auth
    save = Mock()
    resolve = Mock(return_value=SimpleNamespace(save_credentials=save))
    monkeypatch.setattr(auth, 'get_config', resolve)
    result = CliRunner().invoke(auth.app, ['bearer-token', '--profile', 'api', '--stdin'], input='private-test-token\n')
    assert result.exit_code == 0, result.stderr
    resolve.assert_called_once_with(profile='api', profile_auth_type='custom')
    save.assert_called_once_with(X_BEARER_TOKEN='private-test-token')
    assert json.loads(result.stdout) == {'saved': True, 'credential': 'X_BEARER_TOKEN'}
    assert 'private-test-token' not in result.output


def test_bearer_token_command_rejects_empty_input(monkeypatch):
    from x_cli.commands import auth
    save = Mock()
    monkeypatch.setattr(auth, 'get_config', lambda **kwargs: SimpleNamespace(save_credentials=save))
    result = CliRunner().invoke(auth.app, ['bearer-token', '--stdin'], input='\n')
    assert result.exit_code == 1
    assert 'must not be empty' in result.stderr
    save.assert_not_called()


def test_bearer_token_requires_explicit_stdin(monkeypatch):
    from x_cli.commands import auth
    save = Mock()
    monkeypatch.setattr(auth, 'get_config', lambda **kwargs: SimpleNamespace(save_credentials=save))
    result = CliRunner().invoke(auth.app, ['bearer-token'], input='private-hidden-token\n')
    assert result.exit_code == 1
    assert '--stdin' in result.stderr
    assert 'private-hidden-token' not in result.output
    save.assert_not_called()
