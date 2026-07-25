import importlib
import pkgutil
import subprocess

import pytest

import cli_tools_shared.config as config_module


def _iter_command_apps():
    """Yield every command-group Typer app defined under wordpress_cli.commands.

    Building the root ``wordpress`` app (``import wordpress_cli.main``) calls
    ``register_commands``, which permanently wraps each command group's
    callbacks in place with the credential gate. Those command groups are
    module-level singletons, so the wrapping leaks into any later test that
    invokes a group's ``app`` directly (e.g. ``menus.app``). Enumerate the
    groups here so an autouse fixture can restore their pristine callbacks.
    """
    commands_pkg = importlib.import_module("wordpress_cli.commands")
    for module_info in pkgutil.iter_modules(commands_pkg.__path__):
        module = importlib.import_module(f"wordpress_cli.commands.{module_info.name}")
        app = getattr(module, "app", None)
        if app is not None and hasattr(app, "registered_commands"):
            yield app


@pytest.fixture(autouse=True)
def pristine_command_callbacks():
    """Undo credential-gate wrapping leaked onto module-level command apps.

    ``register_commands`` wraps each command callback with ``functools.wraps``,
    so the pristine callback is recoverable via ``__wrapped__``. Restore it
    before and after each test so command groups behave identically whether or
    not another test has imported ``wordpress_cli.main`` first.
    """

    def unwrap():
        for app in _iter_command_apps():
            for command_info in app.registered_commands:
                callback = command_info.callback
                if getattr(callback, "_cli_tools_profile_wrapped", False) and hasattr(
                    callback, "__wrapped__"
                ):
                    command_info.callback = callback.__wrapped__

    unwrap()
    yield
    unwrap()


@pytest.fixture(autouse=True)
def isolated_user_data_and_secret_manager(tmp_path, monkeypatch):
    home = tmp_path / "home"
    data_home = tmp_path / "data-home"
    config_home = tmp_path / "config-home"
    cache_home = tmp_path / "cache-home"
    state_home = tmp_path / "state-home"
    for path in (home, data_home, config_home, cache_home, state_home):
        path.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_DATA_HOME", str(data_home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_home))
    monkeypatch.setenv("XDG_STATE_HOME", str(state_home))

    secrets = {}

    def fake_run(command: str, secret_name: str, *, secret_value=None):
        if command == "get":
            if secret_name not in secrets:
                return subprocess.CompletedProcess([], 1, stdout="", stderr="missing")
            return subprocess.CompletedProcess([], 0, stdout=secrets[secret_name], stderr="")
        if command == "set":
            secrets[secret_name] = secret_value or ""
            return subprocess.CompletedProcess([], 0, stdout="", stderr="")
        if command == "has":
            return subprocess.CompletedProcess(
                [],
                0 if secret_name in secrets else 1,
                stdout="",
                stderr="",
            )
        if command == "delete":
            if secret_name in secrets:
                del secrets[secret_name]
                return subprocess.CompletedProcess([], 0, stdout="", stderr="")
            return subprocess.CompletedProcess([], 1, stdout="", stderr="missing")
        raise AssertionError(f"Unsupported secret-manager command in test: {command}")

    monkeypatch.setattr(config_module, "_run_secret_manager", fake_run)
    return secrets
