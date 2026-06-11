"""Test credential type declarations at both config and command level.

Validates:
1. Config class declares CREDENTIAL_TYPES with approved values
2. Every command declares its credential type(s) in COMMAND_CREDENTIALS
3. Command credential types are declared in config-level CREDENTIAL_TYPES or
   config-level PROFILE_AUTH_TYPES

This ensures the n8n node generator can determine which credential type each
command requires, enabling separate nodes per credential type (e.g.,
"BrickOwl (API)" vs "BrickOwl (Browser)").
"""

import json
import subprocess
from pathlib import Path

import pytest

from cli_test_utils import discover_nested_commands


# Command groups that are infrastructure, not user-facing commands
SKIP_GROUPS = {"auth", "cache", "profiles"}

VALID_CREDENTIAL_TYPES = {
    "api_key",
    "personal_access_token",
    "oauth",
    "oauth_authorization_code",
    "username_password",
    "browser_session",
    "custom",
    "no_auth",
}

# no_auth is a command-level marker (command needs no credentials), not a config-level
# auth flow. It should never appear in Config.CREDENTIAL_TYPES but is valid in
# COMMAND_CREDENTIALS.
COMMAND_ONLY_TYPES = {"no_auth"}


def _command_module_files(commands_dir: Path) -> list[Path]:
    """Return real command modules, ignoring package boilerplate and private files."""
    if not commands_dir.is_dir():
        return []
    return [
        module_file
        for module_file in sorted(commands_dir.glob("*.py"))
        if module_file.name != "__init__.py" and not module_file.name.startswith("_")
    ]


def _command_module_entries(cli_dir: Path, cli_pkg: str) -> list[tuple[str, Path, str]]:
    """Return importable command modules from package or flat layout."""
    pkg_dir = cli_dir / cli_pkg
    package_modules = _command_module_files(pkg_dir / "commands")
    flat_module = pkg_dir / "commands.py"
    if package_modules and flat_module.is_file():
        raise AssertionError(
            f"{cli_pkg} has both commands.py and command modules in commands/. "
            "Use exactly one command layout."
        )
    if package_modules:
        return [
            (module_file.stem, module_file, f"{cli_pkg}.commands.{module_file.stem}")
            for module_file in package_modules
        ]
    if flat_module.is_file():
        return [("commands", flat_module, f"{cli_pkg}.commands")]
    return []


def test_command_module_files_ignores_empty_directory(tmp_path):
    """An empty leftover commands/ directory does not imply commands/<group>.py layout."""
    commands_dir = tmp_path / "commands"
    commands_dir.mkdir()

    assert _command_module_files(commands_dir) == []


def test_command_module_files_ignores_init_only_directory(tmp_path):
    """A commands/ package with only __init__.py still has no real command modules."""
    commands_dir = tmp_path / "commands"
    commands_dir.mkdir()
    (commands_dir / "__init__.py").write_text('"""package"""')

    assert _command_module_files(commands_dir) == []


def test_command_module_entries_use_flat_commands_with_empty_directory(tmp_path):
    """Flat commands.py remains the command module when commands/ is empty."""
    cli_dir = tmp_path / "keywords"
    pkg_dir = cli_dir / "keywords_cli"
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "commands").mkdir()
    flat_module = pkg_dir / "commands.py"
    flat_module.write_text("COMMAND_CREDENTIALS = {'query': ['custom']}")

    assert _command_module_entries(cli_dir, "keywords_cli") == [
        ("commands", flat_module, "keywords_cli.commands")
    ]


def test_config_declares_credential_types(
    cli_name, cli_dir, test_config, help_cache, command_filter
):
    """Config class must declare CREDENTIAL_TYPES with approved values.

    Every CLI that has auth commands must declare CREDENTIAL_TYPES on its
    config class. This tells cli_tools_shared which auth flows to support
    and is used by the n8n node generator to create credential schemas.
    """
    if command_filter:
        pytest.skip("Skipping general setup tests (command filter active)")

    no_auth_clis = test_config["exclusions"].get("no_auth_clis", [])
    if cli_name in no_auth_clis:
        pytest.skip(f"{cli_name} does not require authentication")

    help_text = help_cache("")
    if " auth " not in help_text and "│ auth" not in help_text:
        pytest.skip(f"{cli_name} has no auth subcommand (auth infrastructure not required)")

    cli_pkg = cli_name.replace("-", "_") + "_cli"
    from cli_test_utils import get_uv_tool_venv_dir
    uv_venv = get_uv_tool_venv_dir(cli_dir, cli_name)
    if uv_venv is None:
        pytest.skip(f"{cli_name} uv tool venv not found")
    venv_python = str(uv_venv / "bin" / "python")

    # Import CREDENTIAL_TYPES from the config module
    result = subprocess.run(
        [
            venv_python,
            "-c",
            f"import json; "
            f"from {cli_pkg}.config import Config; "
            f"types = getattr(Config, 'CREDENTIAL_TYPES', None); "
            f"print('MISSING' if types is None else json.dumps([t.value if hasattr(t, 'value') else str(t) for t in types]))",
        ],
        capture_output=True,
        text=True,
        cwd=str(cli_dir),
    )

    assert result.returncode == 0, (
        f"{cli_pkg}.config.Config could not be imported.\n"
        f"stderr: {result.stderr[:300]}\n"
        f"Fix: Ensure config.py defines a Config class extending BaseConfig."
    )

    output = result.stdout.strip()
    assert output != "MISSING", (
        f"{cli_pkg}.config.Config is missing CREDENTIAL_TYPES.\n"
        f"Fix: Add CREDENTIAL_TYPES = [CredentialType.XXX] to the Config class in config.py."
    )

    cred_types = json.loads(output)
    assert isinstance(cred_types, list) and len(cred_types) > 0, (
        f"{cli_pkg}.config.Config.CREDENTIAL_TYPES must be a non-empty list, "
        f"got: {cred_types!r}"
    )

    invalid = [ct for ct in cred_types if ct not in VALID_CREDENTIAL_TYPES]
    assert not invalid, (
        f"{cli_pkg}.config.Config.CREDENTIAL_TYPES contains invalid values: {invalid}\n"
        f"Valid types: {', '.join(sorted(VALID_CREDENTIAL_TYPES))}"
    )


def test_command_credentials_subset_of_config(
    cli_name, cli_dir, test_config, help_cache, command_filter
):
    """COMMAND_CREDENTIALS values must be a subset of Config.CREDENTIAL_TYPES.

    If the config declares CREDENTIAL_TYPES = [CredentialType.OAUTH], then
    no command module should claim a credential type outside that set (e.g.,
    "api_key"). This catches mismatches where a command claims a credential
    flow the tool doesn't actually support.
    """
    no_auth_clis = test_config["exclusions"].get("no_auth_clis", [])
    if cli_name in no_auth_clis:
        pytest.skip(f"{cli_name} does not require authentication")

    help_text = help_cache("")
    if " auth " not in help_text and "│ auth" not in help_text:
        pytest.skip(f"{cli_name} has no auth subcommand (auth infrastructure not required)")

    cli_pkg = cli_name.replace("-", "_") + "_cli"
    module_entries = _command_module_entries(cli_dir, cli_pkg)
    if not module_entries:
        pytest.skip(f"{cli_name} has no command modules")

    from cli_test_utils import get_uv_tool_venv_dir
    uv_venv = get_uv_tool_venv_dir(cli_dir, cli_name)
    if uv_venv is None:
        pytest.skip(f"{cli_name} uv tool venv not found")
    venv_python = str(uv_venv / "bin" / "python")

    # Get Config.CREDENTIAL_TYPES and Config.PROFILE_AUTH_TYPES
    result = subprocess.run(
        [
            venv_python,
            "-c",
            f"import json; "
            f"from {cli_pkg}.config import Config; "
            f"types = getattr(Config, 'CREDENTIAL_TYPES', None); "
            f"profile_types = getattr(Config, 'PROFILE_AUTH_TYPES', {{}}); "
            f"payload = {{"
            f"'credential_types': None if types is None else [t.value if hasattr(t, 'value') else str(t) for t in types], "
            f"'profile_auth_types': list(profile_types.keys())"
            f"}}; "
            f"print(json.dumps(payload))",
        ],
        capture_output=True,
        text=True,
        cwd=str(cli_dir),
    )

    if result.returncode != 0:
        pytest.skip("Config.CREDENTIAL_TYPES not available (test_config_declares_credential_types will catch this)")

    config_payload = json.loads(result.stdout.strip())
    if config_payload["credential_types"] is None:
        pytest.skip("Config.CREDENTIAL_TYPES not available (test_config_declares_credential_types will catch this)")

    config_types = set(config_payload["credential_types"])
    profile_auth_types = set(config_payload["profile_auth_types"])

    # Scan all command modules for COMMAND_CREDENTIALS
    mismatches = []
    for module_name, _module_file, import_path in module_entries:
        if module_name in SKIP_GROUPS:
            continue
        if command_filter and module_name != command_filter and module_name != "commands":
            continue

        result = subprocess.run(
            [
                venv_python,
                "-c",
                f"import json; "
                f"from {import_path} import COMMAND_CREDENTIALS; "
                f"print(json.dumps(COMMAND_CREDENTIALS))",
            ],
            capture_output=True,
            text=True,
            cwd=str(cli_dir),
        )

        if result.returncode != 0:
            continue  # Missing COMMAND_CREDENTIALS caught by other test

        cred_map = json.loads(result.stdout.strip())
        for cmd, types in cred_map.items():
            if not isinstance(types, list):
                continue
            for ct in types:
                if ct in COMMAND_ONLY_TYPES:
                    continue  # no_auth is valid in commands but not in config
                if ct in profile_auth_types:
                    continue
                if ct not in config_types:
                    mismatches.append(
                        f"  {module_name} {cmd}: uses '{ct}' but Config.CREDENTIAL_TYPES = {sorted(config_types)} "
                        f"and Config.PROFILE_AUTH_TYPES = {sorted(profile_auth_types)}"
                    )

    assert not mismatches, (
        "COMMAND_CREDENTIALS references credential types not declared in "
        "Config.CREDENTIAL_TYPES or Config.PROFILE_AUTH_TYPES:\n"
        + "\n".join(mismatches)
        + "\n\nFix: Either add the credential type to Config.CREDENTIAL_TYPES, "
        "add the profile auth type to Config.PROFILE_AUTH_TYPES, "
        "or change the command's credential type to one the tool supports."
    )


def test_all_commands_have_credential_mapping(
    cli_name, cli_dir, test_config, cli_executable, help_cache, command_filter
):
    """Every command must declare its credential type(s) in COMMAND_CREDENTIALS."""
    no_auth_clis = test_config["exclusions"].get("no_auth_clis", [])
    if cli_name in no_auth_clis:
        pytest.skip(f"{cli_name} does not require authentication")

    help_text = help_cache("")
    if " auth " not in help_text and "│ auth" not in help_text:
        pytest.skip(f"{cli_name} has no auth subcommand (auth infrastructure not required)")

    cli_pkg = cli_name.replace("-", "_") + "_cli"
    module_entries = _command_module_entries(cli_dir, cli_pkg)
    if not module_entries:
        pytest.skip(f"{cli_name} has no command modules")

    # Discover all leaf commands (depth 2 = "group command")
    all_commands = discover_nested_commands(
        cli_executable, max_depth=2, skip_list=list(SKIP_GROUPS)
    )

    # Filter to only leaf commands (two-part: "group command") that aren't in skip groups
    leaf_commands = []
    for cmd_path in all_commands:
        parts = cmd_path.split()
        if len(parts) != 2:
            continue
        group, cmd = parts
        if group in SKIP_GROUPS:
            continue
        if command_filter and group != command_filter:
            continue
        leaf_commands.append((group, cmd))

    if not leaf_commands:
        pytest.skip("No leaf commands found to validate")

    # Group commands by module file
    # Convention: commands/<group>.py contains the commands for that group
    from cli_test_utils import get_uv_tool_venv_dir
    uv_venv = get_uv_tool_venv_dir(cli_dir, cli_name)
    if uv_venv is None:
        pytest.skip(f"{cli_name} uv tool venv not found")
    venv_python = str(uv_venv / "bin" / "python")

    missing_commands = []
    invalid_values = []

    # Group leaf commands by their module
    modules = {}
    for group, cmd in leaf_commands:
        modules.setdefault(group, []).append(cmd)

    module_entries_by_stem = {entry[0]: entry for entry in module_entries}
    flat_entry = (
        module_entries[0]
        if len(module_entries) == 1 and module_entries[0][0] == "commands"
        else None
    )

    if flat_entry is not None and len(modules) != 1:
        pytest.fail(
            f"{cli_name} uses flat commands.py but exposes multiple command groups: "
            f"{', '.join(sorted(modules))}. Use commands/<group>.py modules instead."
        )

    for module_name, commands in modules.items():
        module_entry = flat_entry or module_entries_by_stem.get(module_name)
        if module_entry is None:
            module_entry = module_entries_by_stem.get(module_name.replace("-", "_"))
            if module_entry is None:
                for cmd in commands:
                    missing_commands.append(
                        f"  {module_name} {cmd} (module file not found)"
                    )
                continue

        # Import COMMAND_CREDENTIALS from the module using the CLI's venv Python
        _entry_name, _module_file, import_path = module_entry
        result = subprocess.run(
            [
                venv_python,
                "-c",
                f"import json; "
                f"from {import_path} import COMMAND_CREDENTIALS; "
                f"print(json.dumps(COMMAND_CREDENTIALS))",
            ],
            capture_output=True,
            text=True,
            cwd=str(cli_dir),
        )

        if result.returncode != 0:
            for cmd in commands:
                missing_commands.append(
                    f"  {module_name} {cmd} (COMMAND_CREDENTIALS not found in {import_path})"
                )
            continue

        cred_map = json.loads(result.stdout.strip())

        for cmd in commands:
            if cmd not in cred_map:
                missing_commands.append(
                    f"  {module_name} {cmd} (not in COMMAND_CREDENTIALS dict)"
                )
            else:
                # Validate credential type values
                cred_types = cred_map[cmd]
                if not isinstance(cred_types, list) or not cred_types:
                    invalid_values.append(
                        f"  {module_name} {cmd}: value must be a non-empty list, got {cred_types!r}"
                    )
                else:
                    for ct in cred_types:
                        if ct not in VALID_CREDENTIAL_TYPES:
                            invalid_values.append(
                                f"  {module_name} {cmd}: invalid credential type '{ct}' "
                                f"(valid: {', '.join(sorted(VALID_CREDENTIAL_TYPES))})"
                            )

    errors = []
    if missing_commands:
        errors.append(
            f"Commands missing from COMMAND_CREDENTIALS:\n"
            + "\n".join(missing_commands)
            + "\n\nFix: Add a COMMAND_CREDENTIALS dict at module level in the "
            "corresponding commands/*.py file mapping each command name to its "
            "credential type list."
        )
    if invalid_values:
        errors.append(
            f"Invalid COMMAND_CREDENTIALS values:\n" + "\n".join(invalid_values)
        )

    assert not errors, "\n\n".join(errors)


def test_credentialed_commands_expose_profile_option(
    cli_name, cli_dir, test_config, cli_executable, help_cache, command_filter
):
    """Credential-gated commands must expose shared --profile on their command path."""
    no_auth_clis = test_config["exclusions"].get("no_auth_clis", [])
    if cli_name in no_auth_clis:
        pytest.skip(f"{cli_name} does not require authentication")

    help_text = help_cache("")
    if " auth " not in help_text and "│ auth" not in help_text:
        pytest.skip(f"{cli_name} has no auth subcommand (auth infrastructure not required)")

    cli_pkg = cli_name.replace("-", "_") + "_cli"
    module_entries = _command_module_entries(cli_dir, cli_pkg)
    if not module_entries:
        pytest.skip(f"{cli_name} has no command modules")

    max_depth = test_config["general"]["max_nested_depth"]
    if cli_name in test_config.get("cli_specific", {}):
        max_depth = test_config["cli_specific"][cli_name].get("max_nested_depth", max_depth)

    all_commands = discover_nested_commands(
        cli_executable,
        max_depth=max_depth,
        skip_list=list(SKIP_GROUPS),
    )

    from cli_test_utils import get_uv_tool_venv_dir
    uv_venv = get_uv_tool_venv_dir(cli_dir, cli_name)
    if uv_venv is None:
        pytest.skip(f"{cli_name} uv tool venv not found")
    venv_python = str(uv_venv / "bin" / "python")

    module_entries_by_stem = {entry[0]: entry for entry in module_entries}
    flat_entry = (
        module_entries[0]
        if len(module_entries) == 1 and module_entries[0][0] == "commands"
        else None
    )

    credential_maps = {}
    for _module_name, _module_file, import_path in module_entries:
        result = subprocess.run(
            [
                venv_python,
                "-c",
                f"import json; "
                f"from {import_path} import COMMAND_CREDENTIALS; "
                f"print(json.dumps(COMMAND_CREDENTIALS))",
            ],
            capture_output=True,
            text=True,
            cwd=str(cli_dir),
        )
        if result.returncode != 0:
            continue

        credential_maps[import_path] = json.loads(result.stdout.strip())

    def module_entry_for_group(group):
        module_entry = flat_entry or module_entries_by_stem.get(group)
        if module_entry is None:
            module_entry = module_entries_by_stem.get(group.replace("-", "_"))
        return module_entry

    def command_path_requires_credentials(cmd_path):
        parts = cmd_path.split()
        if not parts or parts[0] in SKIP_GROUPS:
            return False
        if command_filter and parts[0] != command_filter:
            return False

        for index in range(1, len(parts)):
            module_entry = module_entry_for_group(parts[index - 1])
            if module_entry is None:
                continue
            _entry_name, _module_file, import_path = module_entry
            cred_map = credential_maps.get(import_path, {})
            cred_types = cred_map.get(parts[index])
            if cred_types and cred_types != ["no_auth"]:
                return True
        return False

    def command_path_profile_help(cmd_path):
        parts = cmd_path.split()
        return [
            " ".join(parts[:index])
            for index in range(1, len(parts) + 1)
        ]

    credentialed_commands = [
        cmd_path for cmd_path in all_commands
        if command_path_requires_credentials(cmd_path)
    ]

    if not credentialed_commands:
        pytest.skip("No credential-gated commands found to validate")

    missing_profile = []
    for cmd_path in credentialed_commands:
        profile_help_paths = command_path_profile_help(cmd_path)
        if any("--profile" in help_cache(help_path) for help_path in profile_help_paths):
            continue

        missing_profile.append(
            f"  {cmd_path} (checked: {', '.join(profile_help_paths)})"
        )

    assert not missing_profile, (
        "Credential-gated commands must accept shared --profile on the command "
        "path so users can override the active selected auth profile.\n"
        "Missing --profile:\n"
        + "\n".join(missing_profile)
    )


def test_command_aliases_have_credential_mapping(
    cli_name, cli_dir, test_config, cli_executable, help_cache, command_filter
):
    """Hidden command aliases must also be mapped in COMMAND_CREDENTIALS.

    Typer allows registering aliases via multiple @app.command() decorators
    (e.g., @app.command("create") + @app.command("add", hidden=True)).
    The n8n node generator discovers ALL registered names (including hidden
    aliases) and looks each up in COMMAND_CREDENTIALS. If an alias is missing,
    the generated node will have an empty credential_types for that command.
    """
    no_auth_clis = test_config["exclusions"].get("no_auth_clis", [])
    if cli_name in no_auth_clis:
        pytest.skip(f"{cli_name} does not require authentication")

    help_text = help_cache("")
    if " auth " not in help_text and "│ auth" not in help_text:
        pytest.skip(f"{cli_name} has no auth subcommand (auth infrastructure not required)")

    cli_pkg = cli_name.replace("-", "_") + "_cli"
    module_entries = _command_module_entries(cli_dir, cli_pkg)
    if not module_entries:
        pytest.skip(f"{cli_name} has no command modules")

    import re

    from cli_test_utils import get_uv_tool_venv_dir
    uv_venv = get_uv_tool_venv_dir(cli_dir, cli_name)
    if uv_venv is None:
        pytest.skip(f"{cli_name} uv tool venv not found")
    venv_python = str(uv_venv / "bin" / "python")
    missing_aliases = []

    for module_name, module_file, import_path in module_entries:
        if module_name in SKIP_GROUPS:
            continue
        if command_filter and module_name != command_filter and module_name != "commands":
            continue

        # Read file to find all @app.command("name") decorators
        content = module_file.read_text()
        # Match @app.command("name") and @app.command('name')
        registered_names = re.findall(
            r'@app\.command\(\s*["\']([^"\']+)["\']', content
        )
        if not registered_names:
            continue

        # Import COMMAND_CREDENTIALS from the module
        result = subprocess.run(
            [
                venv_python,
                "-c",
                f"import json; "
                f"from {import_path} import COMMAND_CREDENTIALS; "
                f"print(json.dumps(COMMAND_CREDENTIALS))",
            ],
            capture_output=True,
            text=True,
            cwd=str(cli_dir),
        )

        if result.returncode != 0:
            continue  # COMMAND_CREDENTIALS import failure is caught by the other test

        cred_map = json.loads(result.stdout.strip())

        for name in registered_names:
            if name not in cred_map:
                missing_aliases.append(
                    f"  {module_name} {name} (@app.command(\"{name}\") "
                    f"not in COMMAND_CREDENTIALS)"
                )

    if missing_aliases:
        assert False, (
            "Command aliases registered via @app.command() are missing from "
            "COMMAND_CREDENTIALS.\n"
            "The n8n node generator discovers ALL registered names (including "
            "hidden aliases) and will produce empty credential_types for "
            "unmapped names.\n\n"
            "Missing:\n" + "\n".join(missing_aliases) + "\n\n"
            "Fix: Add each alias as a key in COMMAND_CREDENTIALS pointing to "
            "the same credential type list as the canonical command."
        )


def test_register_commands_adoption(
    cli_name, cli_dir, test_config, help_cache, command_filter
):
    """CLIs with COMMAND_CREDENTIALS should use register_commands() instead of bare add_typer().

    register_commands() enforces credential checks at runtime before commands
    execute. CLIs that still use bare app.add_typer() for command groups with
    COMMAND_CREDENTIALS will let users hit cryptic errors instead of a clear
    'run auth login' message.

    This test reads main.py and checks that command groups which have
    COMMAND_CREDENTIALS in their module use register_commands() (or are
    infrastructure groups like auth/cache/profiles which are exempt).
    """
    if command_filter:
        pytest.skip("Skipping general setup tests (command filter active)")

    no_auth_clis = test_config["exclusions"].get("no_auth_clis", [])
    if cli_name in no_auth_clis:
        pytest.skip(f"{cli_name} does not require authentication")

    help_text = help_cache("")
    if " auth " not in help_text and "│ auth" not in help_text:
        pytest.skip(f"{cli_name} has no auth subcommand")

    cli_pkg = cli_name.replace("-", "_") + "_cli"
    main_file = cli_dir / cli_pkg / "main.py"

    module_entries = _command_module_entries(cli_dir, cli_pkg)
    if not main_file.exists() or not module_entries:
        pytest.skip(f"{cli_name} has no main.py or command modules")

    main_content = main_file.read_text()
    from cli_test_utils import get_uv_tool_venv_dir
    uv_venv = get_uv_tool_venv_dir(cli_dir, cli_name)
    if uv_venv is None:
        pytest.skip(f"{cli_name} uv tool venv not found")
    venv_python = str(uv_venv / "bin" / "python")

    # Find command modules that have COMMAND_CREDENTIALS
    modules_with_creds = []
    for module_name, _module_file, import_path in module_entries:
        if module_name in SKIP_GROUPS:
            continue

        result = subprocess.run(
            [
                venv_python,
                "-c",
                f"from {import_path} import COMMAND_CREDENTIALS; print('yes')",
            ],
            capture_output=True,
            text=True,
            cwd=str(cli_dir),
        )
        if result.returncode == 0 and result.stdout.strip() == "yes":
            modules_with_creds.append(module_name)

    if not modules_with_creds:
        pytest.skip(f"{cli_name} has no command modules with COMMAND_CREDENTIALS")

    # Check that main.py uses register_commands for these modules
    # Look for bare add_typer() calls for modules that have COMMAND_CREDENTIALS
    import re

    bare_add_typer = []
    for module_name in modules_with_creds:
        # Match patterns like: app.add_typer(accounts.app, ...)
        # or: app.add_typer(module.app, name="accounts", ...)
        pattern = rf'app\.add_typer\(\s*{re.escape(module_name)}\.app\b'
        if re.search(pattern, main_content):
            bare_add_typer.append(module_name)

    if not bare_add_typer:
        return  # All good — either using register_commands or a different pattern

    assert not bare_add_typer, (
        f"Command groups using bare app.add_typer() instead of register_commands():\n"
        + "\n".join(f"  - {m}" for m in bare_add_typer)
        + "\n\nregister_commands() enforces credential checks at runtime.\n"
        "Fix: In main.py, replace:\n"
        "  app.add_typer(module.app, name='...', help='...')\n"
        "with:\n"
        "  from cli_tools_shared.command_registry import register_commands\n"
        "  register_commands(app, get_config, module, name='...', help='...')"
    )
