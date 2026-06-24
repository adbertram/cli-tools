"""Shared pytest configuration and fixtures for CLI tool testing."""

import json
import pytest
import sys
import tomllib
import subprocess
import ast
from pathlib import Path
from typing import Dict

# Add tests directory to path so cli_test_utils can be imported
sys.path.insert(0, str(Path(__file__).parent))

from cli_test_utils import discover_list_commands, run_cli_command

SKIP_GROUPS = {"auth", "cache", "profiles"}
COMMAND_ONLY_CREDENTIAL_TYPES = {"no_auth"}
CLI_SELECTION_FIXTURE = "cli_name"
CLI_NAME_REQUIRED_MESSAGE = (
    "WARNING: No --cli-name specified for CLI-dependent tests.\n"
    "Use --cli-name <name> to execute CLI-dependent tests. "
    "--force only confirms batch/collect-only harness work where those tests may skip."
)


def _credential_types_from_config(cli_dir: Path, cli_name: str) -> list[str] | None:
    """Return declared CREDENTIAL_TYPES, or None if the config cannot be parsed."""
    config_file = cli_dir / f"{cli_name.replace('-', '_')}_cli" / "config.py"
    if not config_file.exists():
        return None
    tree = ast.parse(config_file.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "CREDENTIAL_TYPES":
                if isinstance(node.value, ast.List):
                    credential_types = []
                    for element in node.value.elts:
                        if isinstance(element, ast.Attribute):
                            credential_types.append(element.attr.lower())
                        elif isinstance(element, ast.Constant) and isinstance(element.value, str):
                            credential_types.append(element.value.lower())
                        else:
                            return None
                    return credential_types
                return None
    return None


def _command_credentials_from_module(module_file: Path) -> dict[str, list[str]]:
    """Return COMMAND_CREDENTIALS from a command module."""
    tree = ast.parse(module_file.read_text())
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name) or target.id != "COMMAND_CREDENTIALS":
                continue
            if not isinstance(node.value, ast.Dict):
                return {}
            credential_map: dict[str, list[str]] = {}
            for key_node, value_node in zip(node.value.keys, node.value.values):
                if not isinstance(key_node, ast.Constant) or not isinstance(key_node.value, str):
                    continue
                if not isinstance(value_node, ast.List):
                    continue
                credential_types = []
                for element in value_node.elts:
                    if isinstance(element, ast.Attribute):
                        credential_types.append(element.attr.lower())
                    elif isinstance(element, ast.Constant) and isinstance(element.value, str):
                        credential_types.append(element.value.lower())
                    else:
                        credential_types = []
                        break
                if credential_types:
                    credential_map[key_node.value] = credential_types
            return credential_map
    return {}


def _command_module_files(commands_dir: Path) -> list[Path]:
    """Return real command modules, ignoring package boilerplate and private files."""
    if not commands_dir.is_dir():
        return []
    return [
        module_file
        for module_file in sorted(commands_dir.glob("*.py"))
        if module_file.name != "__init__.py" and not module_file.name.startswith("_")
    ]


def _required_credential_types_for_list_commands(
    cli_dir: Path,
    cli_name: str,
    list_commands: list[str],
) -> list[str]:
    """Return credential types required by the discovered list commands."""
    pkg_dir = cli_dir / f"{cli_name.replace('-', '_')}_cli"
    commands_dir = pkg_dir / "commands"
    package_modules = {
        module_file.stem: module_file
        for module_file in _command_module_files(commands_dir)
    }
    flat_module = pkg_dir / "commands.py"
    if not package_modules and not flat_module.is_file():
        main_module = pkg_dir / "main.py"
        if main_module.is_file() and _command_credentials_from_module(main_module):
            flat_module = main_module
    flat_credentials = None
    if package_modules and flat_module.is_file():
        pytest.fail(
            f"{cli_name} has both commands.py and command modules in commands/. "
            "Use exactly one command layout."
        )
    if not package_modules and flat_module.is_file():
        command_groups = {
            parts[0]
            for command in list_commands
            if len(parts := command.split()) >= 2
            and parts[0] not in SKIP_GROUPS
        }
        if len(command_groups) > 1 and flat_module.name != "main.py":
            pytest.fail(
                f"{cli_name} uses flat commands.py but exposes multiple list-command groups: "
                f"{', '.join(sorted(command_groups))}. Use commands/<group>.py modules instead."
            )
        flat_credentials = _command_credentials_from_module(flat_module)

    required_types: set[str] = set()

    for cmd_path in list_commands:
        parts = cmd_path.split()
        if len(parts) < 2:
            continue
        if parts[0] in SKIP_GROUPS:
            continue
        module_file = package_modules.get(parts[0]) or package_modules.get(parts[0].replace("-", "_"))
        if module_file is None:
            if flat_credentials is None:
                continue
            command_credentials = flat_credentials
        else:
            command_credentials = _command_credentials_from_module(module_file)
        credential_types = (
            command_credentials.get(cmd_path)
            or command_credentials.get(" ".join(parts[1:]))
            or command_credentials.get(parts[-1], [])
        )
        required_types.update(
            credential_type
            for credential_type in credential_types
            if credential_type not in COMMAND_ONLY_CREDENTIAL_TYPES
        )

    return sorted(required_types)


def _auth_required_message(cli_name: str, auth_command: str) -> str:
    return (
        f"Authentication required for complete live list-command testing. "
        f"Run '{auth_command}' to authenticate, then re-run tests."
    )


def _profile_has_required_credentials(profile: dict, required_credential_types: list[str]) -> bool:
    credential_statuses = profile.get("credential_types", {})
    if not isinstance(credential_statuses, dict):
        return False
    return all(
        credential_statuses.get(credential_type, {}).get("authenticated") is True
        for credential_type in required_credential_types
    )


def _missing_credential_types(profile: dict, required_credential_types: list[str]) -> list[str]:
    credential_statuses = profile.get("credential_types", {})
    if not isinstance(credential_statuses, dict):
        return list(required_credential_types)
    return [
        credential_type
        for credential_type in required_credential_types
        if credential_statuses.get(credential_type, {}).get("authenticated") is not True
    ]


def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--cli-name",
        action="store",
        default=None,
        help="CLI tool name to test (e.g., 'notion', 'podio')"
    )
    parser.addoption(
        "--force",
        action="store_true",
        default=False,
        help="Required when running all CLIs (no --cli-name specified)"
    )
    parser.addoption(
        "--command",
        action="store",
        default=None,
        help="Filter tests to specific command group (e.g., 'auth', 'records')"
    )


def _selected_tests_need_cli_name(items) -> bool:
    """Return whether any selected test needs the CLI-specific fixture graph."""
    return any(
        CLI_SELECTION_FIXTURE in getattr(item, "fixturenames", ())
        for item in items
    )


def pytest_collection_finish(session):
    """Validate CLI name or batch mode after pytest has selected tests."""
    cli_name = session.config.getoption("--cli-name")
    force = session.config.getoption("--force")

    if cli_name is None and not force and _selected_tests_need_cli_name(session.items):
        pytest.exit(CLI_NAME_REQUIRED_MESSAGE)


def _resolve_cli_dir_from_launcher(cli_name: str) -> Path:
    """Resolve a CLI's source directory via its installed launcher interpreter."""
    exe_path = Path.home() / ".local" / "bin" / cli_name
    if not exe_path.exists():
        exe_path_win = exe_path.with_suffix(".exe")
        if exe_path_win.exists():
            exe_path = exe_path_win
        else:
            raise FileNotFoundError(f"CLI executable not found at {exe_path}")

    first_line = exe_path.read_text().splitlines()[0].strip()
    if not first_line.startswith("#!"):
        raise RuntimeError(f"Launcher at {exe_path} has no shebang")

    launcher_python = first_line[2:]
    dist_name = f"{cli_name}-cli"
    result = subprocess.run(
        [
            launcher_python,
            "-c",
            (
                "from cli_tools_shared.config import resolve_tool_dir; "
                f"print(resolve_tool_dir({dist_name!r}))"
            ),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip())

    resolved = Path(result.stdout.strip())
    if not resolved.is_dir():
        raise RuntimeError(f"Resolved path is not a directory: {resolved}")
    return resolved


@pytest.fixture(scope="session")
def test_config() -> Dict:
    """Load test configuration from TOML file."""
    config_path = Path(__file__).parent / "cli_test_config.toml"
    with open(config_path, "rb") as f:
        return tomllib.load(f)


@pytest.fixture(scope="session")
def cli_tools_root() -> Path:
    """Root directory containing all CLI tools."""
    return Path(__file__).resolve().parents[4]


@pytest.fixture(scope="session")
def cli_name(request) -> str:
    """Get CLI name from command line argument."""
    name = request.config.getoption("--cli-name")
    if name is None:
        pytest.skip("No --cli-name specified")
    return name


@pytest.fixture(scope="session")
def cli_dir(cli_name, cli_tools_root) -> Path:
    """Get CLI directory path."""
    path = cli_tools_root / cli_name
    if path.exists():
        return path

    try:
        return _resolve_cli_dir_from_launcher(cli_name)
    except Exception as exc:
        pytest.fail(
            f"CLI directory not found at {path}, and launcher-based resolution failed: {exc}"
        )


@pytest.fixture(scope="session")
def cli_executable(cli_name, cli_dir) -> str:
    """Get the full path to the CLI executable.

    This ensures tests use the CLI from its proper installation location,
    not from whatever happens to be in the test runner's PATH.
    Looks for the executable in ~/.local/bin (where uv tool install places it).
    """
    exe_path = Path.home() / ".local" / "bin" / cli_name
    # On Windows, uv installs executables with .exe extension
    if not exe_path.exists():
        exe_path_win = exe_path.with_suffix(".exe")
        if exe_path_win.exists():
            exe_path = exe_path_win
        else:
            pytest.fail(
                f"CLI executable not found at {exe_path}. "
                f"Fix: uv tool install -e {cli_dir} --force --refresh"
            )
    return str(exe_path)


@pytest.fixture(scope="session")
def help_cache(cli_executable) -> Dict[str, str]:
    """Session-scoped cache for CLI help output to avoid repeated subprocess calls."""
    cache = {}

    def _get_help(command_path: str = "") -> str:
        key = f"{cli_executable}:{command_path}"
        if key not in cache:
            args = command_path.split() + ["--help"] if command_path else ["--help"]
            result = run_cli_command(cli_executable, args)
            cache[key] = result.stdout
        return cache[key]

    return _get_help


@pytest.fixture(scope="session")
def authenticated(cli_executable, cli_name, cli_dir, test_config, help_cache, command_filter):
    """Check if CLI is authenticated. Fail if not authenticated and auth is required."""
    return _check_authenticated(cli_executable, cli_name, cli_dir, test_config, help_cache, command_filter)


@pytest.fixture(scope="session")
def require_authenticated(cli_executable, cli_name, cli_dir, test_config, help_cache, command_filter):
    """Return a callable so tests can discover commands before auth gating."""
    auth_verified = False
    cached_result = None

    def _require_authenticated():
        nonlocal auth_verified, cached_result
        if auth_verified:
            return cached_result

        cached_result = _check_authenticated(
            cli_executable,
            cli_name,
            cli_dir,
            test_config,
            help_cache,
            command_filter,
        )
        auth_verified = True
        return cached_result

    return _require_authenticated


def _check_authenticated(cli_executable, cli_name, cli_dir, test_config, help_cache, command_filter):
    """Check if CLI is fully authenticated for complete live list-command testing.

    Auto-detects whether the CLI has auth commands. If no auth subcommand exists,
    skip instead of fail (auth is optional for some CLI types).

    Auth-capable CLIs fail when unauthenticated so execution tests do not
    silently skip live command coverage.
    """
    no_auth_clis = test_config["exclusions"]["no_auth_clis"]

    if cli_name in no_auth_clis:
        pytest.skip(f"{cli_name} does not require authentication")

    # Auto-detect: if CLI has no auth subcommand, skip
    help_text = help_cache("")
    if " auth " not in help_text and "│ auth" not in help_text:
        pytest.skip(f"{cli_name} has no auth subcommand (auth is optional for this CLI type)")

    credential_types = _credential_types_from_config(cli_dir, cli_name)
    if credential_types == []:
        return True

    list_commands, _ = discover_list_commands(cli_executable, cli_name, test_config, command_filter)
    required_credential_types = _required_credential_types_for_list_commands(cli_dir, cli_name, list_commands)
    if not required_credential_types:
        return True

    auth_command = f"{cli_name} auth login"
    auth_login_help = help_cache("auth login")
    if (
        len(required_credential_types) == 1
        and len(credential_types or []) > 1
        and ("--credential-type" in auth_login_help or "-c" in auth_login_help)
    ):
        auth_command = f"{auth_command} --credential-type {required_credential_types[0]}"

    result = run_cli_command(cli_executable, ["auth", "status"])

    if result.returncode not in (0, 2):
        pytest.fail(
            f"{cli_name} auth status returned exit code {result.returncode}.\n"
            f"{_auth_required_message(cli_name, auth_command)}"
        )

    try:
        status = json.loads(result.stdout)
    except (json.JSONDecodeError, AttributeError):
        pytest.fail(
            f"{cli_name} auth status did not return valid JSON.\n"
            f"{_auth_required_message(cli_name, auth_command)}"
    )

    profiles = status.get("profiles", [])
    active_profiles = [
        profile
        for profile in profiles
        if isinstance(profile, dict) and profile.get("active") is True
    ]
    if not active_profiles:
        pytest.fail(
            f"{cli_name} auth status did not report an active profile.\n"
            f"{_auth_required_message(cli_name, auth_command)}"
        )

    matching_profile = next(
        (
            profile
            for profile in active_profiles
            if _profile_has_required_credentials(profile, required_credential_types)
        ),
        None,
    )
    if matching_profile is None:
        profile_missing = {
            profile.get("name", "<unnamed>"): _missing_credential_types(profile, required_credential_types)
            for profile in active_profiles
        }
        missing_credential_types = sorted(
            {
                credential_type
                for missing in profile_missing.values()
                for credential_type in missing
            }
        )
        if (
            len(missing_credential_types) == 1
            and len(credential_types or []) > 1
            and ("--credential-type" in auth_login_help or "-c" in auth_login_help)
        ):
            auth_command = f"{cli_name} auth login --credential-type {missing_credential_types[0]}"
        pytest.fail(
            f"{cli_name} is not fully authenticated for complete live list-command testing.\n"
            f"Discovered list commands require authenticated credential types: "
            f"{', '.join(required_credential_types)}.\n"
            f"No active profile satisfies the required credential types. "
            f"Missing by profile: {profile_missing}.\n"
            f"{_auth_required_message(cli_name, auth_command)}"
        )

    return {
        "profile": matching_profile.get("name"),
        "auth_type": matching_profile.get("auth_type"),
    }


@pytest.fixture(scope="session")
def cli_fixtures(cli_name) -> Dict:
    """Load test fixtures for the specific CLI."""
    fixtures_dir = Path(__file__).parent / "fixtures"
    fixtures_file = fixtures_dir / f"{cli_name}.json"

    if fixtures_file.exists():
        with open(fixtures_file) as f:
            return json.load(f)
    return {}


@pytest.fixture(scope="session")
def command_filter(request) -> str | None:
    """Get command group filter from command line argument."""
    return request.config.getoption("--command")


def _detect_browser_capability(cli_dir: Path, cli_name: str) -> bool:
    """Auto-detect if a CLI has browser automation capability by reading its code.

    Checks (in order):
    1. config.py for CredentialType.BROWSER_SESSION
    2. Existence of browser.py in the package directory
    """
    pkg_name = cli_name.replace("-", "_") + "_cli"
    pkg_dir = cli_dir / pkg_name

    if not pkg_dir.exists():
        return False

    # Check config.py for BROWSER_SESSION credential type
    config_file = pkg_dir / "config.py"
    if config_file.exists():
        content = config_file.read_text()
        if "BROWSER_SESSION" in content:
            return True

    # Check for browser.py (indicates browser commands exist)
    browser_file = pkg_dir / "browser.py"
    if browser_file.exists():
        return True

    return False


@pytest.fixture(scope="session")
def is_browser_cli(cli_name, cli_dir, test_config) -> bool:
    """Determine if CLI has browser automation capability.

    Auto-detects from:
    1. Hardcoded browser_clis list in config (explicit override)
    2. CredentialType.BROWSER_SESSION in config.py
    3. Presence of browser.py in package directory
    """
    browser_clis = test_config["exclusions"].get("browser_clis", [])
    if cli_name in browser_clis:
        return True

    return _detect_browser_capability(cli_dir, cli_name)
