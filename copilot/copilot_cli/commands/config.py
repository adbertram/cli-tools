"""Config management commands: paths, profile inspection, legacy migration.

Subcommands:

    copilot config show      Print effective config dirs and profiles.
    copilot config path      Print a single resolved path (config|cache|profiles).
    copilot config migrate   Move legacy in-repo .env files to ~/.config/copilot/
                             and store secrets in the OS keychain.

The migrate flow is interactive and idempotent: a successful migration writes
``.env.migrated`` next to each consumed legacy file so re-running the command
is a clean no-op.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

import typer

from cli_tools_shared.output import (
    print_json,
    print_table,
    print_success,
    print_warning,
    print_error,
    print_info,
    handle_error,
)
from cli_tools_shared.secrets import (
    SecretError,
    get_secret as _get_secret,
    set_secret as _set_secret,
    keyring_available,
    keyring_backend_name,
)

from ..config import (
    KEYCHAIN_SERVICE,
    Config,
    find_legacy_env_files,
    get_cache_root,
    get_config_root,
    get_profiles_dir,
    list_profile_files,
    profile_env_path,
    profile_name_from_xdg_path,
    _read_is_default,
)


app = typer.Typer(help="Manage copilot configuration paths, profiles, and migration.", no_args_is_help=True)


# ============================================================================
# Constants — which fields go where during migration
# ============================================================================

#: Field names that must be stored in the OS keychain instead of plain text.
#: Keep in sync with :class:`copilot_cli.config.Config.KEYCHAIN_FIELDS`.
SECRET_FIELDS = (
    "AZURE_CLIENT_SECRET",
    "M365_SDK_CLIENT_SECRET",
    "DIRECTLINE_SECRET",
)


def _parse_env(path: Path) -> dict[str, str]:
    """Read a .env file into a dict (ignores blank lines, comments, ``export``).

    We avoid python-dotenv here so the migrate command does not pollute
    ``os.environ`` while inspecting legacy files.
    """
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip()
        if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
            v = v[1:-1]
        out[k] = v
    return out


def _legacy_profile_name(path: Path) -> str:
    """Profile name for a legacy .env or .env.<name> file."""
    if path.name == ".env":
        return "default"
    return path.name[len(".env."):]


def _migration_marker_path(src: Path) -> Path:
    """Sibling path for the ``.migrated`` marker for a legacy file."""
    if src.name == ".env":
        return src.with_name(".env.migrated")
    # ``.env.demo`` → ``.env.demo.migrated`` (kept simple; not using
    # ``with_suffix`` which mishandles dotted filenames).
    return src.with_name(f"{src.name}.migrated")


# ============================================================================
# Commands
# ============================================================================


@app.command("show")
def config_show(
    json_output: bool = typer.Option(
        False, "--json", help="Emit JSON instead of a table.",
    ),
):
    """Show effective config paths, active profile, and keychain status."""
    try:
        cfg = Config()
        active = cfg.get_active_profile_name()
        profiles = [profile_name_from_xdg_path(p) for p in list_profile_files()]
        legacy = [str(p) for p in find_legacy_env_files()]

        try:
            backend = keyring_backend_name()
            keyring_ok = keyring_available()
        except SecretError as exc:
            backend = f"unavailable ({exc})"
            keyring_ok = False

        data = {
            "config_dir": str(get_config_root()),
            "cache_dir": str(get_cache_root()),
            "profiles_dir": str(get_profiles_dir()),
            "active_profile": active,
            "available_profiles": profiles,
            "legacy_env_files": legacy,
            "keychain_service": KEYCHAIN_SERVICE,
            "keychain_backend": backend,
            "keychain_available": keyring_ok,
        }

        if json_output:
            print_json(data)
            return

        rows = [
            {"property": "Config dir", "value": data["config_dir"]},
            {"property": "Cache dir", "value": data["cache_dir"]},
            {"property": "Profiles dir", "value": data["profiles_dir"]},
            {"property": "Active profile", "value": data["active_profile"]},
            {"property": "Available profiles", "value": ", ".join(profiles) or "(none)"},
            {"property": "Legacy .env files", "value": ", ".join(legacy) or "(none)"},
            {"property": "Keychain service", "value": data["keychain_service"]},
            {"property": "Keychain backend", "value": data["keychain_backend"]},
            {"property": "Keychain available", "value": "yes" if keyring_ok else "no"},
        ]
        print_table(rows, columns=["property", "value"], headers=["Property", "Value"])
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("path")
def config_path(
    kind: str = typer.Argument(
        ...,
        help="Which path to print: config | cache | profiles | active",
    ),
):
    """Print a single resolved path (useful for shell scripting)."""
    try:
        kind_l = kind.lower()
        if kind_l == "config":
            typer.echo(str(get_config_root()))
        elif kind_l == "cache":
            typer.echo(str(get_cache_root()))
        elif kind_l == "profiles":
            typer.echo(str(get_profiles_dir()))
        elif kind_l == "active":
            cfg = Config()
            typer.echo(str(cfg.env_file_path))
        else:
            print_error(f"Unknown path kind '{kind}'. Choose: config | cache | profiles | active")
            raise typer.Exit(2)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("migrate")
def config_migrate(
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Auto-confirm — store every secret in the keychain without prompting.",
    ),
    skip_secrets: bool = typer.Option(
        False, "--skip-secrets", help="Migrate non-secret values only; leave secrets untouched.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would happen without writing anything.",
    ),
):
    """Migrate legacy in-repo .env files to ``~/.config/copilot/`` + keychain.

    Idempotent: a ``.env.migrated`` marker is written next to each consumed
    legacy file. Re-running on a fully-migrated system is a clean no-op.

    The legacy ``.env`` files are NOT deleted — the user is prompted to
    review the output and remove them manually.
    """
    try:
        legacy_files = find_legacy_env_files()
        if not legacy_files:
            print_success(
                f"Nothing to migrate — no legacy .env files found.\n"
                f"  Config dir: {get_config_root()}"
            )
            return

        get_profiles_dir().mkdir(parents=True, exist_ok=True)

        actions: list[dict] = []  # (action, profile, key, source, target)
        for src in legacy_files:
            profile = _legacy_profile_name(src)
            target = profile_env_path(profile)
            data = _parse_env(src)

            non_secret = {k: v for k, v in data.items() if k not in SECRET_FIELDS}
            secret = {k: v for k, v in data.items() if k in SECRET_FIELDS and v}

            actions.append({
                "action": "copy",
                "profile": profile,
                "source": str(src),
                "target": str(target),
                "non_secret_keys": sorted(non_secret.keys()),
                "secret_keys": sorted(secret.keys()),
            })
            for key in sorted(secret.keys()):
                actions.append({
                    "action": "secret" if not skip_secrets else "skip-secret",
                    "profile": profile,
                    "key": key,
                })

        if dry_run:
            print_info("Dry run — no changes will be made.")
            for a in actions:
                if a["action"] == "copy":
                    print_info(
                        f"  Would copy {a['source']} → {a['target']} "
                        f"(non-secrets: {len(a['non_secret_keys'])}, "
                        f"secrets to migrate: {len(a['secret_keys'])})"
                    )
                elif a["action"] == "secret":
                    print_info(f"  Would store secret {a['key']} in keychain (profile {a['profile']})")
                else:
                    print_info(f"  Would skip secret {a['key']} (profile {a['profile']})")
            return

        # Pre-flight check: keychain available?
        if not skip_secrets and any(a["action"] == "secret" for a in actions):
            if not keyring_available():
                print_error(
                    "No usable OS keychain backend was detected — secrets cannot "
                    "be migrated.\n"
                    "On Linux, install libsecret (e.g. `sudo apt install "
                    "libsecret-1-0 gir1.2-secret-1`) or `pip install keyrings.alt`.\n"
                    "Re-run with --skip-secrets to copy non-secret values only."
                )
                raise typer.Exit(1)

        for src in legacy_files:
            profile = _legacy_profile_name(src)
            target = profile_env_path(profile)
            data = _parse_env(src)
            non_secret = {k: v for k, v in data.items() if k not in SECRET_FIELDS}
            secret = {k: v for k, v in data.items() if k in SECRET_FIELDS and v}

            # Idempotent skip: a marker next to the source AND the target
            # already exists ⇒ this file was processed in a prior run and
            # nothing has changed. Re-running shouldn't rewrite it.
            marker_path = _migration_marker_path(src)
            if marker_path.exists() and target.exists():
                print_info(f"Skipped {src} — already migrated to {target}.")
                continue

            # Honor the legacy IS_DEFAULT_PROFILE marker if present.
            is_default = _read_is_default(src)
            if is_default is not None:
                non_secret["IS_DEFAULT_PROFILE"] = "1" if is_default else "0"

            # Write the new profile .env (non-secret values only).
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if not yes and not typer.confirm(f"Overwrite existing profile {target}?", default=False):
                    print_warning(f"Skipped {target} (already exists).")
                    continue
            _write_env_file(target, non_secret)
            print_success(f"Wrote profile {profile} → {target}")

            # Stash secrets in the keychain.
            if skip_secrets:
                if secret:
                    print_warning(
                        f"  --skip-secrets: leaving {len(secret)} secret(s) in {src} "
                        f"({', '.join(sorted(secret.keys()))})"
                    )
            else:
                for key, value in secret.items():
                    if not yes:
                        if not typer.confirm(
                            f"  Store {key} for profile '{profile}' in OS keychain?",
                            default=True,
                        ):
                            print_warning(f"  Skipped {key} (still in {src}).")
                            continue
                    try:
                        _set_secret(KEYCHAIN_SERVICE, profile, key, value)
                        print_success(f"  Stored {key} in keychain (service={KEYCHAIN_SERVICE}, profile={profile})")
                    except SecretError as exc:
                        print_error(f"  Failed to store {key}: {exc}")
                        raise typer.Exit(1)

            # Drop a migration marker next to the legacy file. The marker
            # makes the migration idempotent — and lets the user spot which
            # legacy files have been processed.
            marker = _migration_marker_path(src)
            try:
                marker.write_text(
                    f"This profile was migrated to {target} on initial run of "
                    f"`copilot config migrate`. Safe to delete the original "
                    f"{src.name} once you have verified the new location works.\n",
                    encoding="utf-8",
                )
            except OSError:
                pass

        print_info(
            "\nMigration complete.\n"
            "  Verify with: copilot auth status\n"
            f"  Once happy, you may delete the legacy files in:\n"
            f"    {legacy_files[0].parent}"
        )
    except typer.Exit:
        raise
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


@app.command("set-secret")
def config_set_secret(
    key: str = typer.Argument(..., help="Secret name (e.g. AZURE_CLIENT_SECRET)."),
    value: Optional[str] = typer.Option(None, "--value", help="Value to store. Prompted if omitted."),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile to scope the secret to (default: active)."),
):
    """Store a secret in the OS keychain for a profile."""
    try:
        cfg = Config(profile=profile) if profile else Config()
        active = cfg.get_active_profile_name()

        if key.upper() not in {"AZURE_CLIENT_SECRET", "M365_SDK_CLIENT_SECRET", "DIRECTLINE_SECRET"}:
            print_warning(f"'{key}' is not a recognized copilot secret field — storing anyway.")

        if value is None:
            value = typer.prompt(f"Enter value for {key}", hide_input=True)
            if not value:
                print_error("Value cannot be empty.")
                raise typer.Exit(1)

        _set_secret(KEYCHAIN_SERVICE, active, key.upper(), value)
        print_success(f"Stored {key.upper()} in keychain (service={KEYCHAIN_SERVICE}, profile={active}).")
    except typer.Exit:
        raise
    except SecretError as exc:
        print_error(str(exc))
        raise typer.Exit(1)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


def _write_env_file(path: Path, values: dict[str, str]) -> None:
    """Write a dict of key=value pairs as a .env file (sorted, quoted as needed)."""
    lines = []
    for k in sorted(values.keys()):
        v = values[k]
        # Quote anything containing whitespace or shell-special chars.
        if v == "" or all(c.isalnum() or c in "-_./:" for c in v):
            lines.append(f"{k}={v}")
        else:
            escaped = v.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{k}="{escaped}"')
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
