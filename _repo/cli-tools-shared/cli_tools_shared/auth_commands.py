"""Standard auth Typer app: login, logout, status, refresh with --profile support."""

import logging
import sys
import typer
from typing import Callable, Optional

from ._debug_logging import get_debug_logger
from .auth_verifier import AuthVerifier
from .credentials import (
    CredentialType,
    combined_ephemeral_fields,
    combined_login_prompts,
    mask_value,
)
from .exceptions import ConfigError
from .config import (
    BaseConfig,
    get_profile_auth_settings,
    resolve_tool_dir,
    root_config_field_names_for,
)
from .output import (
    print_json,
    print_table,
    print_output,
    print_success,
    print_error,
    print_info,
    print_warning,
    handle_error,
    command,
)

logger = get_debug_logger("cli_tools.auth_commands")


def _portable_failure_code(error):
    """Classify only fixed owning-engine messages, never echo exception text."""
    from .auth import BrowserAutomationError
    import errno
    if isinstance(error, OSError) and error.errno == errno.EEXIST:
        return "destination_exists"
    if isinstance(error, BrowserAutomationError):
        return {
            "Portable session browser close failed": "browser_close_failed",
            "Portable cookie readback failed": "cookie_readback_failed",
            "Portable storage readback failed": "storage_readback_failed",
            "Portable session identity verification failed or requires device verification": "identity_verification_failed",
            "Published portable identity did not verify": "published_identity_or_close_failed",
            "Portable staging browser did not close": "staging_browser_not_closed",
            "Portable session restore failed or requires device verification; private staging was retained": "restore_or_device_verification_failed",
        }.get(str(error), "transfer_failed")
    return "transfer_failed"


def _exclusive_session_rename(source, destination):
    """Publish an absent macOS destination atomically, with no fallback."""
    import ctypes
    import os
    from pathlib import Path

    if sys.platform != "darwin":
        raise ConfigError("Portable profile publication requires macOS exclusive rename")
    library = ctypes.CDLL(None, use_errno=True)
    rename = library.renamex_np
    rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(os.fsencode(source), os.fsencode(destination), 0x00000004 | 0x00000010) != 0:
        raise OSError(ctypes.get_errno(), "Portable exclusive profile rename failed")
    # A successful syscall is not a durable directory entry until every
    # affected parent is flushed. Failure leaves the pre-rename journal in
    # place, so recovery inspects the ownership marker rather than assuming.
    for parent in {Path(source).parent, Path(destination).parent}:
        descriptor = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _session_journal_write(path, journal):
    import json
    import os
    import tempfile
    from pathlib import Path

    descriptor, temporary = tempfile.mkstemp(prefix=".journal-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(journal, stream, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _private_session_path(path, *, directory=False):
    """Reject aliases and permissions that expose transfer state."""
    import os
    import stat

    metadata = path.lstat()
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if path.absolute() != path.resolve() or not kind(metadata.st_mode) or metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
        raise ConfigError("Portable transfer state must be private and unaliased")


def _portable_profile_import(get_config_fn, config_cls, tool_name, profile, bundle,
                             expected_account_id, expected_username=None):
    """Restore a new inactive profile with durable ownership and rollback."""
    import ctypes
    import fcntl
    import json
    import os
    import stat
    import uuid
    from pathlib import Path
    from .auth import BrowserAutomationError, read_session_bundle, validate_session_profile, write_session_bundle
    from .config import get_profiles_base_dir, get_tool_data_dir
    from .browser.processes import profile_process_pids

    validate_session_profile(profile)
    bundle = read_session_bundle(json.dumps(bundle, allow_nan=False))
    if bundle["tool"] != tool_name or bundle["profile"] != profile or bundle["identity"]["account_id"] != expected_account_id or (
        expected_username is not None and bundle["identity"]["username"].casefold() != expected_username.casefold()
    ):
        raise BrowserAutomationError("Portable session target or expected identity mismatch")
    if config_cls is None or CredentialType.BROWSER_SESSION not in config_cls.CREDENTIAL_TYPES:
        raise BrowserAutomationError("Portable browser session configuration is unavailable")
    if sys.platform != "darwin" or not hasattr(ctypes.CDLL(None), "renamex_np"):
        raise BrowserAutomationError("Portable profile publication requires macOS exclusive rename")
    root = get_profiles_base_dir(tool_name).absolute()
    target = root / profile
    if root.resolve() != root or target.exists() or target.is_symlink():
        raise BrowserAutomationError("Portable session destination already exists or is not isolated")
    transfers = get_tool_data_dir(tool_name) / "session-transfers"
    transfers.mkdir(mode=0o700, parents=True, exist_ok=True)
    _private_session_path(transfers, directory=True)
    lock_path = transfers / f"{profile}.lock"
    lock = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    browser = None
    journal_path = transfers / f"{profile}.journal.json"
    journal = None
    try:
        _private_session_path(lock_path)
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if journal_path.exists() or journal_path.is_symlink():
            raise BrowserAutomationError("Unfinished portable session transfer requires journal recovery")
        if target.exists() or target.is_symlink():
            raise BrowserAutomationError("Portable session destination already exists")
        token = uuid.uuid4().hex
        stage_name = "transfer-" + token
        stage = root / stage_name
        backup = transfers / f"{token}.bundle.json"
        journal = {"token": token, "tool": tool_name, "profile": profile,
                   "stage": str(stage), "target": str(target), "backup": str(backup), "phase": "initializing"}
        # Journal every subsequent mutation, including interrupted preparation.
        _session_journal_write(journal_path, journal)
        stage.mkdir(mode=0o700, parents=True)
        marker = stage / ".session-transfer.json"
        _session_journal_write(marker, {"token": token, "tool": tool_name, "profile": profile})
        env = "ACTIVE=false\n"
        field = getattr(config_cls, "PROFILE_AUTH_TYPE_FIELD", None)
        if field:
            env += f"{field}=browser_session\n"
        descriptor = os.open(stage / ".env", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            stream.write(env)
            stream.flush()
            os.fsync(stream.fileno())
        # The marker proves ownership during recovery; it contains no secrets.
        write_session_bundle(backup, bundle)
        journal["phase"] = "prepared"
        _session_journal_write(journal_path, journal)
        # Staging .env already exists, so BaseConfig cannot bootstrap active default.
        config = get_config_fn(profile=stage_name)
        browser = config.get_browser()
        journal["phase"] = "restoring"
        _session_journal_write(journal_path, journal)
        result = browser.import_session(bundle, expected_account_id=expected_account_id,
                                        expected_username=expected_username, target_profile=profile)
        browser._portable_close()
        if profile_process_pids(config.get_persistent_profile_dir()):
            raise BrowserAutomationError("Portable staging browser did not close")
        journal["phase"] = "publishing"
        _session_journal_write(journal_path, journal)
        _exclusive_session_rename(stage, target)
        journal["phase"] = "published"
        _session_journal_write(journal_path, journal)
        final_config = get_config_fn(profile=profile)
        browser = final_config.get_browser()
        final_identity = browser._portable_identity(expected_account_id, expected_username)
        browser._portable_close()
        if final_identity != result["identity"] or profile_process_pids(final_config.get_persistent_profile_dir()):
            raise BrowserAutomationError("Published portable identity did not verify")
        journal["phase"] = "complete"
        _session_journal_write(journal_path, journal)
        # Complete is the durable commit point. Cleanup failure must not undo
        # an already verified publication; recovery completes private cleanup.
        try:
            backup.unlink()
            journal_path.unlink()
        except OSError:
            pass
        return {**result, "profile": profile, "imported": True, "active": False}
    except Exception as error:
        failure_phase = journal["phase"] if journal is not None else "preparation"
        failure_code = _portable_failure_code(error)
        if browser is not None:
            try:
                browser._portable_close()
            except Exception:
                pass
        if journal is not None:
            try:
                stage = Path(journal["stage"])
                target = Path(journal["target"])
                marker = target / ".session-transfer.json"
                owned = marker.is_file() and json.loads(marker.read_text()).get("token") == journal["token"]
                if owned and not stage.exists() and not profile_process_pids(target / "browser-data" / "chromium-profile"):
                    _exclusive_session_rename(target, stage)
                if journal["phase"] != "initializing":
                    journal["phase"] = "failed"
                journal["failure_phase"] = failure_phase
                journal["failure_code"] = failure_code
                _session_journal_write(journal_path, journal)
            except Exception:
                # Retain the last durable journal and all private backup state.
                pass
        if journal is None and isinstance(error, BrowserAutomationError):
            raise error
        import errno
        if isinstance(error, OSError) and error.errno == errno.EEXIST:
            raise BrowserAutomationError("Portable session destination already exists; private backup retained") from None
        raise BrowserAutomationError(f"Portable session import failed (phase={failure_phase}; code={failure_code}); private backup retained and journal recovery is required") from None
    finally:
        os.close(lock)


def _finalize_portable_profile(get_config_fn, tool_name, profile, journal, journal_path,
                               stage, target, backup, owned, expected_account_id,
                               expected_username):
    """Finalize one already restored, importer-owned inactive profile under lock."""
    from .auth import BrowserAutomationError, PORTABLE_SESSION_MAX_BYTES, read_session_bundle
    from .browser.processes import profile_process_pids
    browser = None
    failure_phase = "preparation"
    may_rollback = False
    try:
        if not callable(get_config_fn) or not isinstance(expected_account_id, str) or not expected_account_id:
            raise ValueError
        if stage.exists() == target.exists():
            raise ValueError
        current = stage if stage.exists() else target
        if not owned(current):
            raise ValueError
        env = current / ".env"
        _private_session_path(env)
        if env.stat().st_size > 65536:
            raise ValueError
        from .config import _read_env_values
        if _read_env_values(env).get("ACTIVE") != "false":
            raise ValueError
        if profile_process_pids(current / "browser-data" / "chromium-profile"):
            raise ValueError
        _private_session_path(backup)
        with backup.open("rb") as stream:
            raw = stream.read(PORTABLE_SESSION_MAX_BYTES + 1)
        bundle = read_session_bundle(raw.decode("utf-8"))
        if bundle["tool"] != tool_name or bundle["profile"] != profile or bundle["identity"]["account_id"] != expected_account_id or (
            expected_username is not None and bundle["identity"]["username"].casefold() != expected_username.casefold()
        ):
            raise ValueError
        failure_phase = "restoring"
        journal["phase"] = failure_phase
        _session_journal_write(journal_path, journal)
        may_rollback = True
        config = get_config_fn(profile=current.name)
        browser = config.get_browser()
        identity = browser._portable_identity(expected_account_id, expected_username)
        browser._portable_close()
        if profile_process_pids(config.get_persistent_profile_dir()):
            raise BrowserAutomationError("Portable staging browser did not close")
        if current == stage:
            failure_phase = "publishing"
            journal["phase"] = failure_phase
            _session_journal_write(journal_path, journal)
            _exclusive_session_rename(stage, target)
        failure_phase = "published"
        journal["phase"] = failure_phase
        _session_journal_write(journal_path, journal)
        config = get_config_fn(profile=profile)
        browser = config.get_browser()
        final_identity = browser._portable_identity(expected_account_id, expected_username)
        browser._portable_close()
        if final_identity != identity or profile_process_pids(config.get_persistent_profile_dir()):
            raise BrowserAutomationError("Published portable identity did not verify")
        journal["phase"] = "complete"
        journal.pop("failure_phase", None)
        journal.pop("failure_code", None)
        _session_journal_write(journal_path, journal)
        try:
            backup.unlink()
            _exclusive_session_rename(journal_path, journal_path.parent / (journal["token"] + ".completed.json"))
        except OSError:
            pass
        return {"tool": tool_name, "profile": profile, "identity": final_identity,
                "recovered": True, "published": True, "verified": True, "active": False,
                "backup_retained": backup.exists()}
    except Exception as error:
        code = _portable_failure_code(error)
        if browser is not None:
            try:
                browser._portable_close()
            except Exception:
                pass
        try:
            if may_rollback and owned(target) and not stage.exists() and not profile_process_pids(target / "browser-data" / "chromium-profile"):
                _exclusive_session_rename(target, stage)
            journal.update(phase="failed", failure_phase=failure_phase, failure_code=code)
            _session_journal_write(journal_path, journal)
        except Exception:
            pass
        raise BrowserAutomationError(f"Portable session finalization failed (phase={failure_phase}; code={code}); private backup retained") from None


def _recover_portable_profile(tool_name, profile, *, finalize=False, get_config_fn=None,
                              expected_account_id=None, expected_username=None):
    """Quarantine only importer-owned state, preserving every failed backup."""
    import fcntl
    import json
    import os
    import re
    from pathlib import Path
    from .auth import BrowserAutomationError, validate_session_profile
    from .config import get_profiles_base_dir, get_tool_data_dir
    from .browser.processes import profile_process_pids

    validate_session_profile(profile)
    transfers = get_tool_data_dir(tool_name) / "session-transfers"
    journal_path = transfers / f"{profile}.journal.json"
    try:
        _private_session_path(transfers, directory=True)
        _private_session_path(journal_path)
        lock_path = transfers / f"{profile}.lock"
        _private_session_path(lock_path)
        lock = os.open(lock_path, os.O_RDWR | os.O_NOFOLLOW)
    except Exception:
        raise BrowserAutomationError("Portable session recovery journal is missing or unsafe") from None
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if journal_path.stat().st_size > 4096:
            raise ValueError
        journal = json.loads(journal_path.read_text())
        token = journal["token"]
        if not isinstance(token, str) or not re.fullmatch(r"[a-f0-9]{32}", token):
            raise ValueError
        root = get_profiles_base_dir(tool_name).absolute()
        stage, target = root / ("transfer-" + token), root / profile
        backup = transfers / f"{token}.bundle.json"
        if journal["tool"] != tool_name or journal["profile"] != profile or journal["stage"] != str(stage) or journal["target"] != str(target) or journal["backup"] != str(backup) or root.resolve() != root or journal["phase"] not in {"initializing", "prepared", "restoring", "publishing", "published", "failed", "complete", "recovered"}:
            raise ValueError
        if any(path.is_symlink() for path in (stage, target, backup)):
            raise ValueError
        def owned(path):
            marker = path / ".session-transfer.json"
            if not marker.exists():
                return False
            _private_session_path(path, directory=True)
            _private_session_path(marker)
            return marker.stat().st_size <= 4096 and json.loads(marker.read_text()) == {"token": token, "tool": tool_name, "profile": profile}
        if finalize and journal["phase"] == "complete":
            raise BrowserAutomationError("Portable session is already complete; use recovery without --finalize for cleanup")
        if finalize:
            return _finalize_portable_profile(get_config_fn, tool_name, profile, journal,
                journal_path, stage, target, backup, owned, expected_account_id, expected_username)
        if journal["phase"] == "complete":
            if not owned(target) or stage.exists() or profile_process_pids(target / "browser-data" / "chromium-profile"):
                raise ValueError
            if backup.exists():
                _private_session_path(backup)
                backup.unlink()
            _exclusive_session_rename(journal_path, transfers / f"{token}.completed.json")
            return {"tool": tool_name, "profile": profile, "recovered": True, "backup_retained": False, "published": True}
        if owned(target):
            if stage.exists() or profile_process_pids(target / "browser-data" / "chromium-profile"):
                raise ValueError
            _exclusive_session_rename(target, stage)
        initializing = journal["phase"] == "initializing"
        if stage.exists():
            _private_session_path(stage, directory=True)
        if (not initializing and not owned(stage)) or profile_process_pids(stage / "browser-data" / "chromium-profile") or (not initializing and not backup.is_file()):
            raise ValueError
        if initializing and (target.exists() or (stage.exists() and (stage / ".session-transfer.json").exists() and not owned(stage))):
            raise ValueError
        if backup.exists():
            _private_session_path(backup)
        retained = backup.is_file()
        journal["phase"] = "recovered"
        _session_journal_write(journal_path, journal)
        _exclusive_session_rename(journal_path, transfers / f"{token}.recovered.json")
        return {"tool": tool_name, "profile": profile, "recovered": True, "backup_retained": retained}
    except Exception as error:
        if isinstance(error, BrowserAutomationError) and (str(error).startswith("Portable session finalization failed (phase=") or str(error) == "Portable session is already complete; use recovery without --finalize for cleanup"):
            raise
        raise BrowserAutomationError("Portable session recovery refused unsafe or live profile state; backup retained") from None
    finally:
        os.close(lock)


def _register_portable_session_commands(app, get_config_fn, config_cls, tool_name):
    """Mount explicit named-session commands without constructing Config."""
    from pathlib import Path
    from .auth import BrowserAutomationError, PORTABLE_SESSION_MAX_BYTES, read_session_bundle, validate_session_profile
    from .config import get_profiles_base_dir

    @app.command("session-export")
    @command
    def session_export(
        profile: str = typer.Option(..., "--profile", help="Explicit named browser-session profile"),
        expected_account_id: str = typer.Option(..., "--expected-account-id", help="Exact expected service account ID"),
        expected_username: Optional[str] = typer.Option(None, "--expected-username", help="Expected service username"),
        output: Path = typer.Option(..., "--output", help="New private CLI runtime bundle file"),
    ):
        """Export scoped cookies/localStorage after live exact-account checks."""
        validate_session_profile(profile)
        source = get_profiles_base_dir(tool_name).absolute() / profile
        if source.resolve() != source or not (source / ".env").is_file() or (source / ".env").is_symlink():
            raise BrowserAutomationError("Portable session source profile is missing or unsafe")
        config = get_config_fn(profile=profile)
        print_json(config.get_browser().export_session(output, expected_account_id=expected_account_id,
                                                       expected_username=expected_username))

    @app.command("session-import")
    @command
    def session_import(
        profile: str = typer.Option(..., "--profile", help="New inactive named browser-session profile"),
        expected_account_id: str = typer.Option(..., "--expected-account-id", help="Exact expected service account ID"),
        expected_username: Optional[str] = typer.Option(None, "--expected-username", help="Expected service username"),
        stdin: bool = typer.Option(False, "--stdin", help="Read a private bounded session bundle from stdin"),
    ):
        """Restore, verify, close, and exclusively publish an absent profile."""
        validate_session_profile(profile)
        if not stdin or sys.stdin.isatty():
            raise BrowserAutomationError("Portable import requires --stdin with piped or redirected JSON")
        try:
            raw = sys.stdin.buffer.read(PORTABLE_SESSION_MAX_BYTES + 1)
            bundle = read_session_bundle(raw.decode("utf-8"))
        except Exception:
            raise BrowserAutomationError("Invalid or oversized portable session stdin") from None
        print_json(_portable_profile_import(get_config_fn, config_cls, tool_name, profile, bundle,
                                             expected_account_id, expected_username))

    @app.command("session-import-recover")
    @command
    def session_import_recover(
        profile: str = typer.Option(..., "--profile", help="Explicit named profile with an unfinished transfer journal"),
        finalize: bool = typer.Option(False, "--finalize", help="Verify and publish already restored inactive owned state"),
        expected_account_id: Optional[str] = typer.Option(None, "--expected-account-id", help="Required exact actor for finalization"),
        expected_username: Optional[str] = typer.Option(None, "--expected-username", help="Expected service username for finalization"),
    ):
        """Recover owned closed transfer state or finalize it after exact actor proof."""
        if finalize and not expected_account_id:
            raise BrowserAutomationError("Portable session finalization requires --expected-account-id")
        if not finalize and (expected_account_id is not None or expected_username is not None):
            raise BrowserAutomationError("Portable session expected identity requires --finalize")
        print_json(_recover_portable_profile(tool_name, profile, finalize=finalize,
            get_config_fn=get_config_fn, expected_account_id=expected_account_id,
            expected_username=expected_username))


_CREDENTIAL_TYPE_ALIASES = {
    "browser": CredentialType.BROWSER_SESSION.value,
}


def _login_setup_instructions(config) -> Optional[str]:
    """Return the preferred auth setup message for a config."""
    for attr_name in ("AUTH_SETUP_INSTRUCTIONS", "LOGIN_INSTRUCTIONS"):
        value = getattr(config, attr_name, None)
        if value:
            return str(value).strip()
    return None


def _has_prompt_placeholder_value(config, field_name: str, current_value: Optional[str]) -> bool:
    """Return True when a stored prompt value still matches the config default."""
    if not current_value:
        return False
    default_value = getattr(config, f"DEFAULT_{field_name}", None)
    return bool(default_value) and current_value == default_value


def _prompt_and_save(config, prompts, skip_if_set: bool = True) -> bool:
    """Prompt for credential fields and save values to config.

    Args:
        config: BaseConfig instance.
        prompts: Iterable of (field_name, prompt_text, hide_input) tuples.
        skip_if_set: If True, skip fields that already have a value.

    Returns:
        True if any field was prompted.
    """
    instructions_shown = False
    setup_instructions = _login_setup_instructions(config)
    prompted = False
    for field_name, prompt_text, hide in prompts:
        current = config._get(field_name)
        if current and skip_if_set and not _has_prompt_placeholder_value(config, field_name, current):
            continue
        if not instructions_shown:
            if setup_instructions:
                print_info(setup_instructions)
            instructions_shown = True
        prompted = True
        value = typer.prompt(f"Enter {prompt_text}", hide_input=hide)
        if not value or not value.strip():
            print_error(f"{prompt_text} cannot be empty")
            raise typer.Exit(1)
        config._set(field_name, value.strip())
    return prompted


def _clear_login_state(config, credential_types: list[CredentialType]) -> None:
    """Clear transient login state without removing reusable credentials."""
    fields = combined_ephemeral_fields(credential_types, config=config)
    if (
        CredentialType.OAUTH in credential_types
        and not getattr(config, "OAUTH_TOKEN_EXPIRES", True)
    ):
        static_fields = set(getattr(config, "OAUTH_STATIC_REQUIRED_FIELDS", ()))
        fields = [field for field in fields if field not in static_fields]
    for field_name in dict.fromkeys(fields):
        config._clear(field_name)

    if CredentialType.BROWSER_SESSION in credential_types:
        browser = config.get_browser() if hasattr(config, "get_browser") else None
        if browser is not None:
            browser.clear_session()
        else:
            config.clear_session()


def _missing_credential_types(config) -> list[CredentialType]:
    """Return credential types that have no configured login state."""
    missing = []
    for credential_type in config.CREDENTIAL_TYPES:
        if credential_type == CredentialType.BROWSER_SESSION:
            configured = config.has_saved_session()
        else:
            if hasattr(config, "_required_fields_for"):
                required_fields = config._required_fields_for([credential_type])
            else:
                from .credentials import combined_required_fields
                required_fields = combined_required_fields([credential_type], config=config)
            configured = all(config._get(field) for field in required_fields)
        if not configured:
            missing.append(credential_type)
    return missing


def _load_config_for_login(get_config_fn, effective_profile, tool_name: str):
    """Create the login config, converting missing-secret errors into guidance.

    When a profile field is sourced from a ``secret://`` placeholder and the
    referenced CLI-tools secret is missing, ``BaseConfig`` raises a generic
    ``Missing secret '<name>' referenced by <path>`` error during init. Interactive
    ``auth login`` cannot re-prompt a secret-managed field, so a bare re-prompt is
    the wrong remediation. Re-raise with the exact secret-manager command so the
    user knows how to set or rotate the secret.
    """
    from .config import secret_manager_set_command

    try:
        return get_config_fn(profile=effective_profile)
    except ConfigError as exc:
        message = str(exc)
        marker = "Missing secret '"
        if not message.startswith(marker):
            raise
        secret_name = message[len(marker):].split("'", 1)[0]
        raise ConfigError(
            f"{message}\n"
            f"This value is sourced from CLI-tools secret '{secret_name}'. "
            "It cannot be entered interactively.\n"
            f"Set or rotate it with: {secret_manager_set_command(secret_name)}"
        ) from exc


def _secret_managed_field_names(config, active_types) -> dict:
    """Return ``{field_name: secret_name}`` for required fields backed by secrets.

    Only required credential fields for the active credential types that are
    stored as ``secret://`` placeholders in the active profile ``.env`` are
    returned. These fields live in the CLI-tools secret manager and cannot be
    re-prompted interactively during ``auth login``.
    """
    from .config import profile_secret_field_map

    env_path = getattr(config, "env_file_path", None)
    if env_path is None:
        return {}
    placeholders = profile_secret_field_map(env_path)
    if not placeholders:
        return {}
    required = set(config._required_fields_for(active_types))
    return {
        field: secret_name
        for field, secret_name in placeholders.items()
        if field in required
    }


def _notify_secret_managed_fields(config, active_types, tool_name: str) -> None:
    """Print actionable guidance for required fields sourced from secrets."""
    from .config import secret_manager_set_command

    secret_fields = _secret_managed_field_names(config, active_types)
    for field, secret_name in secret_fields.items():
        print_info(
            f"{field} is sourced from CLI-tools secret '{secret_name}' and cannot "
            f"be entered interactively.\n"
            f"To change or rotate it, run: {secret_manager_set_command(secret_name)}"
        )


def _browser_declarative_login_ready(browser) -> bool:
    """True when ``browser`` can refresh its own session headlessly.

    Only real ``BrowserAutomation`` instances with a fully declared
    non-interactive credential login (username/password/submit selectors AND
    both secret names — ``declarative_login_configured``) qualify. Any other
    browser object (adapters, mocks) keeps the interactive headed login flow.
    """
    from .auth import BrowserAutomation

    return isinstance(browser, BrowserAutomation) and browser.declarative_login_configured


def _interactive_stdio_available() -> bool:
    """True when this process can interact with a human.

    Checks TTY stdin first, then falls back to opening the controlling
    terminal ``/dev/tty`` (mirroring ``_prompt_enter_eof_safe``).
    """
    try:
        if sys.stdin is not None and sys.stdin.isatty():
            return True
    except Exception:
        pass
    try:
        with open("/dev/tty", "r"):
            return True
    except OSError:
        return False
    except Exception:
        return False


def _handle_browser_login(config, tool_name: str, force: bool):
    """Handle browser session login if config.get_browser() is configured.

    Never claims "already authenticated" based on session files alone —
    cookies on disk can be expired or revoked server-side. The
    short-circuit must be backed by a live round-trip via
    ``browser.is_authenticated()``. If the live check fails we proceed
    to the login flow even though session files exist on disk, because
    that is exactly the case the user wants caught.

    When the browser fully declares the non-interactive credential login
    (see ``BrowserAutomation.declarative_login_configured``) the login is
    attempted HEADLESS first via ``BrowserAutomation.ensure_fresh_session()``
    — no visible browser, no stdin — so the same ``auth login`` works from
    non-interactive automation hosts (the 2026-09-04 microworkers incident:
    a stale saved session could not be healed without a TTY). The headed
    interactive flow is preserved as the fallback when a human-verification
    challenge blocks the headless path, and for CLIs that do not configure
    the declarative login at all.
    """
    logger.debug("_handle_browser_login: tool=%s force=%s", tool_name, force)
    browser = config.get_browser()
    if browser is None:
        logger.debug("_handle_browser_login: no browser configured, skipping")
        return
    # When the live check fails, the saved session is stale — we must
    # force the inner authenticate() to clear it, otherwise its
    # ``has_saved_session()`` short-circuit returns immediately without
    # ever opening the browser. The user would see "Browser session
    # authenticated" while nothing actually happened.
    effective_force = force
    try:
        if not force:
            has_session = config.has_saved_session()
            logger.debug("_handle_browser_login: has_saved_session=%s", has_session)
            if has_session:
                # Live-verify before declaring "already authenticated".
                live = browser.is_authenticated()
                live_ok = bool(live)
                logger.debug("_handle_browser_login: live check=%s", live_ok)
                if live_ok:
                    print_success(f"Already authenticated ({tool_name} browser session)")
                    return
                print_info(
                    "Saved session is no longer valid — re-running browser login."
                )
                effective_force = True

        # Headless-first automatic refresh for CLIs with a complete
        # declarative non-interactive login. A successful headless refresh
        # returns before any browser window is opened. ``--force`` must skip
        # this shortcut because a fresh session would otherwise return early
        # instead of entering the forced browser-login flow. Fall back to the
        # headed flow only when a human gate blocks the headless attempt
        # (needs_human) or — for a non-challenge failure on a TTY — so a
        # human can still complete the login by hand.
        if not force and _browser_declarative_login_ready(browser):
            outcome = browser.ensure_fresh_session()
            if outcome.authenticated:
                print_success("Browser session authenticated")
                return
            if outcome.needs_human:
                print_warning(
                    "Automatic browser login needs a human to complete a challenge "
                    f"({outcome.reason or 'unknown challenge'}); opening the "
                    "interactive login browser so you can finish it."
                )
            elif _interactive_stdio_available():
                print_info(
                    "Automatic browser login did not succeed "
                    f"({outcome.reason or 'unknown reason'}); opening the "
                    "interactive login browser."
                )
            else:
                # Non-interactive host with a fully declared login whose
                # headless refresh failed without a human gate (rejected
                # credentials, missing secret, timeout). Do not open a headed
                # browser that cannot be completed here.
                print_error(
                    "Browser auth failed: "
                    f"{outcome.reason or 'automatic browser login failed'}"
                )
                raise typer.Exit(1)

        print_info("Opening browser for login...")
        logger.debug("_handle_browser_login: calling browser.login(force=%s)", effective_force)
        result = browser.login(force=effective_force)
        logger.debug("_handle_browser_login: login result=%s", result)
        if result.get("success"):
            print_success("Browser session authenticated")
        else:
            print_error(f"Browser auth failed: {result.get('message', 'Unknown error')}")
            raise typer.Exit(1)
    finally:
        browser.close()


def _mask_saved_fields(config, cred_type) -> dict:
    """Return masked sensitive field values for a single credential type.

    Only fields with non-empty stored values are included. Both the
    required fields and the type's sensitive fields are masked so that
    callers can show a safe preview of what's configured.
    """
    fields = []
    if cred_type == CredentialType.CUSTOM:
        fields.extend(getattr(config, "CUSTOM_REQUIRED_FIELDS", []) or [])
    else:
        fields.extend(cred_type.required_fields)
    for f in cred_type.sensitive_fields:
        if f not in fields:
            fields.append(f)

    masked = {}
    for field in fields:
        value = config._get(field)
        if value:
            masked[field.lower()] = mask_value(value)
    return masked


def _resolve_profile_names(get_config_fn, requested_profile: Optional[str], tool_name: str) -> list:
    """Return the list of profile names to check.

    If a specific profile is requested, returns just that one. Otherwise
    enumerates every .env* file in the tool directory via list_profiles().
    Falls back to [None] when no profiles have been created yet.
    """
    if requested_profile:
        return [requested_profile]

    from .profiles import list_profiles

    config_cls = _get_config_class(get_config_fn)
    configured_credential_types = list(
        getattr(config_cls, "CREDENTIAL_TYPES", None)
        or []
    )
    profile_store = _get_profile_store_for_auth(get_config_fn, config_cls, tool_name)
    profile_entries = [entry for entry in list_profiles(profile_store) if entry.get("active") is True]
    if not profile_entries:
        return [None]
    return [entry["name"] for entry in profile_entries]


def _get_config_class(get_config_fn):
    get_config_fn = getattr(get_config_fn, "__wrapped__", get_config_fn)
    annotations = getattr(get_config_fn, "__annotations__", {}) or {}
    config_cls = annotations.get("return")
    if config_cls is not None:
        return config_cls
    config_cls = getattr(get_config_fn, "__globals__", {}).get("Config")
    if config_cls is not None:
        return config_cls
    for cell in getattr(get_config_fn, "__closure__", ()) or ():
        value = cell.cell_contents
        if isinstance(value, type) and hasattr(value, "CREDENTIAL_TYPES"):
            return value
    return None


def _tool_dir_from_closure(get_config_fn):
    for cell in getattr(get_config_fn, "__closure__", ()) or ():
        value = cell.cell_contents
        if isinstance(value, type(None)):
            continue
        if hasattr(value, "is_dir") and hasattr(value, "exists"):
            try:
                if value.exists():
                    return value
            except OSError:
                continue
    return None


def _get_profile_store_for_auth(get_config_fn, config_cls, tool_name: str):
    from .profiles import ProfileStore
    probe_config = None

    profile_auth_settings = None
    tool_dir = _tool_dir_from_closure(get_config_fn)
    if config_cls is not None:
        profile_auth_settings = get_profile_auth_settings(config_cls)
        if tool_dir is None and getattr(config_cls, "DIST_NAME", None):
            tool_dir = resolve_tool_dir(config_cls.DIST_NAME)

    if config_cls is None or tool_dir is None:
        try:
            probe_config = get_config_fn()
        except Exception:
            probe_config = None

    if config_cls is None and probe_config is not None:
        config_cls = type(probe_config)
        profile_auth_settings = get_profile_auth_settings(config_cls)

    if tool_dir is None:
        tool_dir = getattr(probe_config, "tool_dir", None)
    if tool_dir is None:
        tool_dir = _tool_dir_from_closure(get_config_fn)
    if config_cls is not None:
        if tool_dir is None and getattr(config_cls, "DIST_NAME", None):
            tool_dir = resolve_tool_dir(config_cls.DIST_NAME)
    return ProfileStore(
        tool_name,
        tool_dir=tool_dir,
        profile_auth_settings=profile_auth_settings,
        root_config_fields=root_config_field_names_for(config_cls),
    )


def _collect_profile_statuses(
    get_config_fn,
    tool_name: str,
    profile: Optional[str],
    api_test_handler=None,
    verbose: bool = False,
) -> dict:
    """Run AuthVerifier for each target profile and build the response dict.

    Always returns {"profiles": [...]}. Each profile entry contains
    `name`, `auth_type`, `active`, `authenticated`, and `credential_types`. When
    `verbose` is True, `base_url` is added to every profile entry.
    """
    from .profiles import list_profiles

    profile_names = _resolve_profile_names(get_config_fn, profile, tool_name)

    config_cls = _get_config_class(get_config_fn)
    profile_store = _get_profile_store_for_auth(get_config_fn, config_cls, tool_name)
    profile_map = {
        entry["name"]: entry
        for entry in list_profiles(profile_store)
    }
    configured_credential_types = list(
        getattr(config_cls, "CREDENTIAL_TYPES", []) if config_cls is not None else []
    )

    profile_entries = []
    for prof_name in profile_names:
        try:
            config = get_config_fn(profile=prof_name)
        except ConfigError as exc:
            message = str(exc)
            if (
                config_cls is None
                or not message.startswith("Missing secret '")
                or " referenced by " not in message
            ):
                raise
            active_name = prof_name or "default"
            profile_meta = profile_map.get(active_name, {})
            credential_types = {
                ct.value: {
                    "credentials_saved": False,
                    "authenticated": False,
                    "api_test": f"failed: {message}",
                    "message": message,
                }
                for ct in configured_credential_types
            }
            profile_entries.append(
                {
                    "name": active_name,
                    "auth_type": profile_meta.get("auth_type") or "default",
                    "active": bool(profile_meta.get("active", False)),
                    "authenticated": False,
                    "credential_types": credential_types,
                    "missing": [message],
                }
            )
            continue
        verifier = AuthVerifier(config, api_test_handler=api_test_handler)
        result = verifier.verify()

        active_name = config.get_active_profile_name()
        profile_meta = profile_map.get(active_name)
        if profile_meta is None:
            profile_map = {
                entry["name"]: entry
                for entry in list_profiles(profile_store)
            }
            profile_meta = profile_map.get(active_name, {})
        entry = {
            "name": active_name,
            "auth_type": profile_meta.get("auth_type"),
            "active": bool(profile_meta.get("active", False)),
            "authenticated": result["authenticated"],
            "credential_types": result["credential_types"],
        }

        # Attach per-type static credential previews and missing-credentials
        # hints so the output is self-explanatory.
        for ct in config.CREDENTIAL_TYPES:
            type_key = ct.value
            block = entry["credential_types"].get(type_key)
            if block is None:
                continue
            if block.get("credentials_saved"):
                for masked_key, masked_val in _mask_saved_fields(config, ct).items():
                    block.setdefault(masked_key, masked_val)
            else:
                block.setdefault(
                    "message",
                    f"Not authenticated. Run '{tool_name} auth login' to configure.",
                )

        if not any(block.get("credentials_saved") for block in entry["credential_types"].values()):
            entry["missing"] = config.get_missing_credentials()

        if verbose:
            entry["base_url"] = config.base_url

        logger.debug("auth_status: profile=%s entry=%s", active_name, entry)
        profile_entries.append(entry)

    return {"profiles": profile_entries}


def _exit_if_no_authenticated_profile(data: dict) -> None:
    if not any(profile["authenticated"] for profile in data["profiles"]):
        raise typer.Exit(2)


def _bootstrap_profile_if_missing(get_config_fn, requested_profile: Optional[str], tool_name: str) -> Optional[str]:
    """Ensure a profile exists for ``auth login`` to write credentials into.

    On a fresh install no ``.env`` files exist yet, so ``auth login`` would
    silently write credentials without a registered profile and downstream
    commands like ``auth profiles list`` and ``auth status`` would fail to
    discover them. This helper auto-creates the profile that ``auth login``
    is about to populate.

    Behavior:
      * If ``requested_profile`` is ``None`` AND no profile env files exist
        for the tool, create a ``default`` profile.
      * If ``requested_profile`` is set and its env file does not exist,
        create that profile.
      * If the relevant profile already exists, do nothing.

    Returns the effective profile name to use for subsequent
    ``get_config_fn(profile=...)`` calls (either ``requested_profile`` or
    ``"default"`` after bootstrapping). Raises on creation failure — no
    silent suppression.
    """
    from .profiles import create_profile, list_profiles

    config_cls = _get_config_class(get_config_fn)
    profile_store = _get_profile_store_for_auth(get_config_fn, config_cls, tool_name)
    existing = list_profiles(profile_store)
    existing_names = {entry["name"] for entry in existing}

    if requested_profile is None:
        if existing:
            return None
        target_name = "default"
    else:
        if requested_profile in existing_names:
            return requested_profile
        target_name = requested_profile

    create_profile(profile_store, target_name)
    print_info(f"Created profile '{target_name}'")

    return target_name if requested_profile else None


def _require_profile_for_multi_auth_login(
    get_config_fn,
    requested_profile: Optional[str],
    tool_name: str,
) -> None:
    if requested_profile:
        return
    config_cls = _get_config_class(get_config_fn)
    profile_auth_settings = get_profile_auth_settings(config_cls) if config_cls is not None else None
    if profile_auth_settings is None:
        return
    _auth_type_field, auth_types = profile_auth_settings
    if len(auth_types) < 2:
        return
    valid_types = ", ".join(sorted(auth_types))
    print_error(
        f"{tool_name} auth login requires --profile because this CLI has "
        f"multiple profile auth types: {valid_types}. Create or select the "
        "target profile first, then run auth login --profile <name>."
    )
    raise typer.Exit(1)


def _resolve_credential_type(config, credential_type_str: str):
    """Resolve a credential type string to a CredentialType enum, validating it's configured."""
    cred_types = config.CREDENTIAL_TYPES
    if len(cred_types) < 2:
        print_error("--credential-type is only valid for CLIs with multiple credential types")
        raise typer.Exit(1)
    normalized = _CREDENTIAL_TYPE_ALIASES.get(credential_type_str, credential_type_str)
    for ct in cred_types:
        if ct.value == normalized:
            return ct
    valid = ", ".join(ct.value for ct in cred_types)
    print_error(f"Unknown credential type '{credential_type_str}'. Valid types: {valid}")
    raise typer.Exit(1)


def create_auth_app(
    get_config_fn,
    tool_name: str = "tool",
    login_handler: Optional[Callable] = None,
    test_handler: Optional[Callable] = None,
    profiles_app: Optional[typer.Typer] = None,
    include_profiles: bool = True,
):
    """Create a standard auth Typer app for a CLI tool.

    Args:
        get_config_fn: Callable that accepts (profile=None) and returns a BaseConfig.
        tool_name: CLI tool name for help text (e.g., 'cloudflare').
        login_handler: Optional callable(config, force) for custom login flows.
            Used by CLIs that need a custom OAuth flow (e.g., OAuth 1.0a,
            dual-auth). When provided, replaces the default interactive
            prompt login AND the built-in OAuth auto-detection. The handler
            is responsible for the entire login flow including obtaining
            and saving tokens.

            Handler priority (3-way resolution):
            1. Explicit login_handler param -> always wins
            2. Config has OAUTH_AUTH_URL + OAUTH_TOKEN_URL -> built-in oauth_login
            3. Neither -> default prompt-based login

        test_handler: Optional callable(config) -> dict for auth testing.
            Returns dict with at minimum {"api_test": "passed"|"failed: reason"}.
            Only provides the API test — credential checks and browser session
            checks are handled automatically by the shared package.
        profiles_app: Optional pre-built profiles Typer app. Use this when a CLI
            has a local profiles app that must be mounted exactly as-is.
        include_profiles: Mount the standard profiles app under auth.

    Returns:
        typer.Typer app with login, logout, status commands (+ refresh for OAuth,
        + profiles, + test if test_handler provided).
    """
    app = typer.Typer(help=f"Manage {tool_name} authentication", no_args_is_help=True)
    config_cls = _get_config_class(get_config_fn)
    probe_config = None
    if config_cls is None:
        try:
            probe_config = get_config_fn()
        except Exception:
            probe_config = None
    if config_cls is None and probe_config is not None:
        config_cls = type(probe_config)
    configured_credential_types = list(
        getattr(config_cls, "CREDENTIAL_TYPES", None)
        or getattr(probe_config, "CREDENTIAL_TYPES", [])
        or []
    )
    has_browser_auth = CredentialType.BROWSER_SESSION in configured_credential_types
    allow_credential_type_selection = len(configured_credential_types) > 1
    credential_type_examples = ", ".join(f"'{ct.value}'" for ct in configured_credential_types)
    if credential_type_examples:
        credential_type_help = f"Authenticate only this credential type (e.g., {credential_type_examples})"
    else:
        credential_type_help = "Authenticate only this credential type"
    logout_help = "Clear stored credentials and browser sessions." if has_browser_auth else "Clear stored credentials."
    if has_browser_auth:
        status_help = (
            "Check authentication status across profiles.\n\n"
            "Performs a live round-trip for every configured credential type so\n"
            "the report reflects ground truth — not on-disk belief. Saved\n"
            "credentials whose live verification fails are reported as\n"
            "``authenticated: false`` with the failure reason in\n"
            "``api_test`` (API/OAuth) or via the live browser check\n"
            "(browser_session)."
        )
    else:
        status_help = (
            "Check authentication status across profiles.\n\n"
            "Performs a live round-trip for every configured credential type so\n"
            "the report reflects ground truth — not on-disk belief. Saved\n"
            "credentials whose live verification fails are reported as\n"
            "``authenticated: false`` with the failure reason in\n"
            "``api_test``."
        )

    # Resolve the effective test handler ONCE so both ``auth status`` and
    # ``auth test`` use the same live-verification path. ``auth status``
    # MUST do live checks — filesystem state is not proof of being
    # authenticated.
    effective_test_handler = test_handler
    if effective_test_handler is None:
        try:
            if config_cls is not None and config_cls.test_connection is not BaseConfig.test_connection:
                def _auto_test_handler(config):
                    result = config.test_connection()
                    if result is not None:
                        return result
                    return {"api_test": "skipped: no test_connection implemented"}
                effective_test_handler = _auto_test_handler
        except Exception:
            pass

    login_doc = (
        "Configure authentication credentials.\n\n"
        "Prompts for required credentials based on the tool's authentication type.\n"
        "For OAuth authorization code flows, opens a browser for user consent."
    )

    def _run_auth_login(
        profile: Optional[str],
        force: bool,
        credential_type: Optional[str] = None,
    ):
        _require_profile_for_multi_auth_login(get_config_fn, profile, tool_name)
        # Auto-create a profile when none exists yet (or the requested one
        # is missing) so credentials saved during this login flow land in a
        # registered profile that ``auth profiles list`` / ``auth status``
        # can discover.
        effective_profile = _bootstrap_profile_if_missing(get_config_fn, profile, tool_name)
        config = _load_config_for_login(get_config_fn, effective_profile, tool_name)

        # Resolve scoped credential type if specified
        resolved_type = None
        if credential_type:
            resolved_type = _resolve_credential_type(config, credential_type)

        # Determine which credential types to process
        if resolved_type:
            active_types = [resolved_type]
        else:
            missing_types = _missing_credential_types(config)
            active_types = missing_types or config.CREDENTIAL_TYPES

        # Required credential fields sourced from ``secret://`` placeholders live
        # in the CLI-tools secret manager and cannot be entered interactively.
        # Tell the user how to set/rotate them so ``auth login`` is actionable
        # instead of a silent no-op.
        _notify_secret_managed_fields(config, active_types, tool_name)

        # Resolve effective handler (3-way)
        effective_handler = login_handler
        if effective_handler is None and config.OAUTH_AUTH_URL and config.OAUTH_TOKEN_URL:
            from .oauth import oauth_login
            effective_handler = oauth_login

        # Force clears only transient auth state. Static credentials such as
        # client IDs, client secrets, API keys, and redirect URIs remain usable.
        if force:
            _clear_login_state(config, active_types)
            print_info("Existing ephemeral auth state cleared")

        _prompt_and_save(
            config,
            getattr(config, "AUTH_CONFIG_PROMPTS", []),
            skip_if_set=True,
        )

        # Browser session only — skip all prompts, go directly to browser login
        if resolved_type == CredentialType.BROWSER_SESSION:
            _handle_browser_login(config, tool_name, force)
            return

        if effective_handler is not None:
            # Custom or built-in OAuth login flow
            # Ensure setup fields (CLIENT_ID, etc.) are configured first
            _prompt_and_save(
                config,
                combined_login_prompts(active_types, config=config),
                skip_if_set=True,
            )
            _prompt_and_save(config, config.AUTH_EXTRA_PROMPTS, skip_if_set=True)

            # Delegate to handler for token acquisition
            effective_handler(config, force)
        else:
            # Default prompt-based login — skip fields that already have values
            # (force only clears ephemeral fields, so static creds remain)
            prompted = _prompt_and_save(config, combined_login_prompts(active_types, config=config))
            _prompt_and_save(config, config.AUTH_EXTRA_PROMPTS, skip_if_set=True)

            if prompted:
                print_success("Credentials saved successfully")

        # Browser session login (if configured and no custom handler)
        # Custom handlers manage their own browser flow
        # Skip if --credential-type is set and it's not BROWSER_SESSION
        if effective_handler is None or effective_handler is not login_handler:
            if not resolved_type or resolved_type == CredentialType.BROWSER_SESSION:
                _handle_browser_login(config, tool_name, force)

    if allow_credential_type_selection:
        @app.command("login")
        @command
        def auth_login(
            profile: Optional[str] = typer.Option(
                None, "--profile", "-p", help="Profile name to save credentials to"
            ),
            force: bool = typer.Option(
                False, "--force", "-F", help="Clear existing ephemeral auth state and re-authenticate"
            ),
            credential_type: Optional[str] = typer.Option(
                None, "--credential-type", "--credential", "-c", help=credential_type_help
            ),
        ):
            _run_auth_login(profile, force, credential_type)

        auth_login.__doc__ = login_doc
    else:
        @app.command("login")
        @command
        def auth_login(
            profile: Optional[str] = typer.Option(
                None, "--profile", "-p", help="Profile name to save credentials to"
            ),
            force: bool = typer.Option(
                False, "--force", "-F", help="Clear existing ephemeral auth state and re-authenticate"
            ),
        ):
            _run_auth_login(profile, force)

        auth_login.__doc__ = login_doc

    @app.command("logout", help=logout_help)
    @command
    def auth_logout(
        profile: Optional[str] = typer.Option(
            None, "--profile", "-p", help="Profile name to clear credentials from"
        ),
    ):
        target_profiles = _resolve_profile_names(get_config_fn, profile, tool_name)
        for profile_name in target_profiles:
            config = get_config_fn(profile=profile_name)
            config.clear_credentials()
            browser = config.get_browser()
            if browser is not None:
                browser.close()
            config.clear_session()
        print_success("Credentials cleared")

    @app.command("status", help=status_help)
    @command
    def auth_status(
        profile: Optional[str] = typer.Option(
            None, "--profile", "-p", help="Profile name to check (defaults to all profiles)"
        ),
        table: bool = typer.Option(
            False, "--table", "-t", help="Display as table"
        ),
    ):
        data = _collect_profile_statuses(
            get_config_fn=get_config_fn,
            tool_name=tool_name,
            profile=profile,
            api_test_handler=effective_test_handler,
        )
        print_output(data, table)
        _exit_if_no_authenticated_profile(data)

    if has_browser_auth and getattr(config_cls, "PORTABLE_BROWSER_SESSION", False) is True:
        _register_portable_session_commands(app, get_config_fn, config_cls, tool_name)

    if has_browser_auth:
        @app.command("seed-shared-chromium-profile")
        @command
        def seed_shared_chromium_profile(
            profile: Optional[str] = typer.Option(
                None, "--profile", "-p", help="Default profile with the known-good legacy browser session"
            ),
        ):
            """Seed an empty shared Chromium profile from this CLI's default profile."""
            config = get_config_fn(profile=profile)
            seeded = config.seed_shared_chromium_profile()
            print_success(f"Seeded shared Chromium profile at {seeded}")

    # Add refresh command only if config has OAuth token URL
    # We check lazily via a probe config to avoid requiring profile at import time
    if config_cls is not None and getattr(config_cls, "OAUTH_TOKEN_URL", ""):
        @app.command("refresh")
        @command
        def auth_refresh(
            profile: Optional[str] = typer.Option(
                None, "--profile", "-p", help="Profile name"
            ),
            table: bool = typer.Option(
                False, "--table", "-t", help="Display as table"
            ),
        ):
            """Refresh OAuth access token using stored refresh token."""
            config = get_config_fn(profile=profile)
            from .token_manager import TokenManager
            tm = TokenManager(config)
            tm.force_refresh()
            print_success("Access token refreshed")

    # Add test command if test_handler is provided or auto-detected.
    # ``effective_test_handler`` is resolved once at the top of this
    # function and reused for both ``auth status`` and ``auth test``.
    if effective_test_handler is not None:
        @app.command("test")
        @command
        def auth_test(
            table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
            verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed checks"),
            profile: Optional[str] = typer.Option(None, "--profile", "-p", help="Profile name (defaults to all profiles)"),
        ):
            """Test authentication by verifying credentials work across profiles."""
            data = _collect_profile_statuses(
                get_config_fn=get_config_fn,
                tool_name=tool_name,
                profile=profile,
                api_test_handler=effective_test_handler,
                verbose=verbose,
            )
            print_output(data, table)
            _exit_if_no_authenticated_profile(data)

    if include_profiles:
        if profiles_app is None:
            from .profiles_commands import create_profiles_app
            profiles_app = create_profiles_app(get_config_fn, tool_name)
        app.add_typer(profiles_app, name="profiles", help="Manage authentication profiles")

    return app
