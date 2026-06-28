"""Utility functions for CLI testing - separate from tests/ to avoid circular imports."""

import os
import subprocess
import sys
import json
import re
from pathlib import Path
from typing import Any, List, Dict, Optional, Tuple

_DISCOVER_NESTED_COMMANDS_CACHE: Dict[
    Tuple[str, str, int, int, Tuple[str, ...], int],
    Tuple[str, ...],
] = {}


def _clean_path() -> Dict[str, str]:
    """Return env with harness Python state removed.

    CLIs are invoked by full path, so the test venv's bin/ is never needed.
    Keeping it in PATH can shadow CLI dependencies — same-named binaries
    installed in the test venv can mask the CLI under test.

    Python interpreter env vars can also make a uv-tool launcher import from
    the harness interpreter instead of the CLI's own isolated uv tool venv.
    """
    env = os.environ.copy()
    virtual_env = os.environ.get("VIRTUAL_ENV")
    path_parts = env.get("PATH", "").split(os.pathsep)
    if virtual_env:
        venv_bin = os.path.join(virtual_env, "bin")
        path_parts = [p for p in path_parts if p != venv_bin]
    user_bin = str(Path.home() / ".local" / "bin")
    if user_bin not in path_parts:
        path_parts.insert(0, user_bin)
    env["PATH"] = os.pathsep.join(path_parts)
    for key in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME", "__PYVENV_LAUNCHER__"):
        env.pop(key, None)
    env["COLUMNS"] = "200"
    env["NO_COLOR"] = "1"
    return env


RUN_TIMEOUT_ATTEMPTS = 2


def run_cli_command(
    cli_name: str,
    args: List[str],
    timeout: int = 30,
    check: bool = False
) -> subprocess.CompletedProcess:
    """Execute CLI command with timeout and capture output.

    Retries once on timeout: CLI startup can stall for tens of seconds under
    bursty host contention (Dropbox sync, parallel agent sessions), and a
    single stall is not a CLI hang. A second consecutive timeout raises
    TimeoutExpired so genuine hangs still fail loudly.
    """
    cmd = [cli_name] + args
    for attempt in range(1, RUN_TIMEOUT_ATTEMPTS + 1):
        try:
            return subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=check,
                env=_clean_path()
            )
        except subprocess.TimeoutExpired:
            if attempt == RUN_TIMEOUT_ATTEMPTS:
                raise
            print(
                f"WARNING: {' '.join(cmd)} timed out after {timeout}s "
                f"(attempt {attempt}/{RUN_TIMEOUT_ATTEMPTS}); retrying",
                file=sys.stderr,
            )


def _top_level_cache_command_missing(result: subprocess.CompletedProcess) -> bool:
    """Return True when the CLI has no top-level ``cache`` command to clear."""
    output = f"{result.stderr or ''}\n{result.stdout or ''}".lower()
    return (
        "no such command 'cache'" in output
        or 'no such command "cache"' in output
        or "no such command: cache" in output
        or "unexpected extra argument (cache)" in output
    )


def clear_cli_cache(cli_executable: str, timeout: int = 30) -> None:
    """Clear cached CLI responses before a live command executes."""
    result = run_cli_command(cli_executable, ["cache", "clear"], timeout=timeout)
    if result.returncode == 0:
        return
    if _top_level_cache_command_missing(result):
        return
    detail = (result.stderr or result.stdout or "").strip()
    raise AssertionError(
        f"Could not clear CLI response cache before live test "
        f"(exit code {result.returncode}). Stderr/stdout: {detail[:300]}"
    )


def run_live_cli_command(
    cli_executable: str,
    args: List[str],
    timeout: int = 30,
    check: bool = False
) -> subprocess.CompletedProcess:
    """Execute a live CLI command after clearing the response cache."""
    clear_cli_cache(cli_executable, timeout=timeout)
    return run_cli_command(cli_executable, args, timeout=timeout, check=check)


def parse_help_commands(help_text: str) -> List[str]:
    """Extract command names from Rich CLI help output.

    Parses lines like: │ auth    Authentication commands
    Returns: ["auth", "items", ...]

    Only parses from the Commands section to avoid false positives
    from option descriptions (e.g., "copy" in --show-completion help text).

    Column-aware so wrapped help does not create phantom commands.
    Rich/Typer lays each Commands row out as two aligned columns:
    the command name in a fixed left column and its help text in a deeper
    column to the right. When a command's help is long enough to wrap, the
    overflow renders on continuation lines that are indented to the *help*
    column, e.g.:

        │ search    Search icons by a single keyword ... a single keyword │
        │           like 'branch' or 'lightbulb' matches; ...             │

    The bare ``^│\\s+([a-z]...)`` pattern matches the first lowercase token on
    every line, so the continuation line above yields a phantom ``like``
    command, and the generator then runs e.g. ``icons like --help`` (exit 2)
    and aborts. To prevent that, lock onto the command-name column from the
    first real row in a section and accept a token only when it begins at (or
    before) that column; tokens that begin at the deeper help column are
    wrapped continuation text and are rejected. The column is the offset of the
    command-name token from the ``│`` box char (the pattern anchors on ``^│``,
    but the ``│`` may be preceded by other chars in some terminals, so measure
    from the ``│`` rather than from column 0).
    """
    pattern = r'^│(\s+)([a-z][a-z0-9_-]*)\s+'
    commands = []
    in_commands_section = False
    # Command-name column for the current Commands section, learned from its
    # first matched row. None until the first real command row is seen, and
    # reset whenever a new Commands section begins so a help screen with more
    # than one Commands box is handled independently.
    command_column = None

    for line in help_text.split('\n'):
        # Detect Commands section header
        if 'Commands' in line and '─' in line:
            in_commands_section = True
            command_column = None
            continue
        # Detect end of Commands section (next section header)
        if in_commands_section and '─' in line and 'Commands' not in line:
            in_commands_section = False
            command_column = None
            continue

        if in_commands_section:
            match = re.match(pattern, line)
            if match:
                # Offset of the command-name token from the │ box char, i.e.
                # the width of the leading whitespace captured before the name.
                token_column = len(match.group(1))
                if command_column is None:
                    # First real command row defines the command-name column.
                    command_column = token_column
                if token_column <= command_column:
                    commands.append(match.group(2))
                # token_column > command_column => the token starts at the
                # deeper help column, so this is a wrapped continuation line,
                # not a command. Skip it.
    return commands


def extract_help_sections(help_text: str) -> Dict[str, str]:
    """Extract named sections from Rich/Typer help output."""
    sections = {}
    current_name = None
    current_lines = []

    for line in help_text.splitlines():
        header_match = re.match(r"^╭─\s*(.+?)\s*─+╮$", line.strip())
        if header_match:
            if current_name:
                sections[current_name] = "\n".join(current_lines)
            current_name = header_match.group(1).strip()
            current_lines = []
            continue

        if line.strip().startswith("╰") and line.strip().endswith("╯"):
            if current_name:
                sections[current_name] = "\n".join(current_lines)
                current_name = None
                current_lines = []
            continue

        if current_name:
            content = re.sub(r"^\s*│\s?", "", line)
            content = re.sub(r"\s*│\s*$", "", content)
            current_lines.append(content)

    return sections


def parse_help_arguments(section_text: str) -> List[Dict]:
    """Parse a Rich/Typer Arguments section into usage.json argument records."""
    arguments = []

    for line in section_text.splitlines():
        line = line.strip()
        if not line:
            continue

        required = line.startswith("*")
        if required:
            line = line[1:].strip()

        bracket_match = re.match(r"^(\w[\w-]*)\s+\[([A-Z_]+)\]\s+(.*)", line)
        if bracket_match:
            name = bracket_match.group(1)
            arg_type = bracket_match.group(2)
            rest = bracket_match.group(3).strip()
        else:
            bare_match = re.match(r"^(\w[\w-]*)\s{2,}([A-Z][A-Z_0-9]+)\s{2,}(.*)", line)
            if bare_match:
                name = bare_match.group(1)
                arg_type = bare_match.group(2)
                rest = bare_match.group(3).strip()
            else:
                parts = re.split(r"\s{2,}", line, maxsplit=1)
                name = parts[0]
                arg_type = "TEXT"
                rest = parts[1] if len(parts) > 1 else ""

        default = None
        default_match = re.search(r"\[default:\s*(.+?)\]", rest)
        if default_match:
            default = default_match.group(1)
            rest = rest[: default_match.start()].strip()

        if "[required]" in rest:
            required = True
            rest = rest.replace("[required]", "").strip()

        argument = {
            "name": name,
            "type": arg_type,
            "required": required,
            "help": rest.rstrip(". ").strip() if rest else "",
        }
        if default is not None:
            argument["default"] = default

        arguments.append(argument)

    return arguments


def parse_help_options(section_text: str) -> List[Dict]:
    """Parse a Rich/Typer Options section into usage.json option records."""
    options = []
    joined_lines = []

    for line in section_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("--") or stripped.startswith("*"):
            joined_lines.append(stripped)
        elif joined_lines:
            joined_lines[-1] += " " + stripped

    filtered_options = {"--help", "--install-completion", "--show-completion"}

    for line in joined_lines:
        required = line.startswith("*")
        if required:
            line = line[1:].strip()

        if any(line.startswith(option) for option in filtered_options):
            continue

        flag_match = re.match(r"^(--[\w-]+)(?:,--[\w-]+)*\s+(-\w)?\s*(.*)", line)
        if not flag_match:
            continue

        long_flag = flag_match.group(1)
        short_flag = flag_match.group(2)
        rest = flag_match.group(3).strip()

        # Typer renders a paired boolean flag as two long forms on one line,
        # e.g. "--content-done            --no-content-done   <help>". The
        # primary regex only consumes an optional short flag, so the negative
        # secondary form would otherwise be captured as part of the help text.
        # Strip a leading secondary long flag (with its own optional short
        # flag) before extracting the type/help so the help stays clean.
        secondary_match = re.match(r"^(--[\w-]+)(?:\s+(-\w))?\s+(.*)", rest)
        if secondary_match:
            if short_flag is None and secondary_match.group(2):
                short_flag = secondary_match.group(2)
            rest = secondary_match.group(3).strip()

        type_match = re.match(r"^([A-Z][A-Z_0-9]+)\s+(.*)", rest)
        if type_match:
            opt_type = type_match.group(1)
            help_text = type_match.group(2).strip()
        else:
            opt_type = "bool"
            help_text = rest

        default = None
        default_match = re.search(r"\[default:\s*(.+?)\]", help_text)
        if default_match:
            default = default_match.group(1)
            help_text = help_text[: default_match.start()].strip()

        if "[required]" in help_text:
            required = True
            help_text = help_text.replace("[required]", "").strip()

        env_var = None
        env_match = re.search(r"\[env var:\s*(.+?)\]", help_text)
        if env_match:
            env_var = env_match.group(1)
            help_text = help_text[: env_match.start()].strip()

        option = {
            "name": long_flag,
            "type": opt_type,
            "required": required,
            "help": help_text.rstrip(". ").strip() if help_text else "",
        }
        if short_flag:
            option["short"] = short_flag
        if default is not None:
            option["default"] = default
        if env_var:
            option["env_var"] = env_var

        options.append(option)

    return options


def parse_help_parameters(help_text: str) -> Dict[str, List[Dict]]:
    """Extract arguments and options from live command help."""
    sections = extract_help_sections(help_text)
    return {
        "arguments": parse_help_arguments(sections.get("Arguments", "")),
        "options": parse_help_options(sections.get("Options", "")),
    }


def describe_json_top_level(data: Any) -> str:
    """Return a concise description of a parsed JSON document's root shape."""
    if isinstance(data, list):
        return f"array[{len(data)}]"
    if isinstance(data, dict):
        keys = sorted(str(key) for key in data.keys())
        preview = ", ".join(keys[:5])
        suffix = ", ..." if len(keys) > 5 else ""
        return f"object keys=[{preview}{suffix}]"
    if data is None:
        return "null"
    return type(data).__name__


def validate_json_output(stdout: str) -> Tuple[bool, Optional[Any]]:
    """Validate that output is valid JSON and return parsed data."""
    try:
        data = json.loads(stdout)
        return True, data
    except json.JSONDecodeError:
        return False, None


def require_json_array_output(
    stdout: str,
    *,
    command: str = "command",
) -> Tuple[bool, Optional[List[Any]], str]:
    """Parse stdout and require a top-level JSON array before callers slice it."""
    valid, data = validate_json_output(stdout)
    if not valid:
        return False, None, f"{command} stdout is not a single valid JSON document"
    if not isinstance(data, list):
        shape = describe_json_top_level(data)
        return False, None, f"{command} expected top-level JSON array before slicing, got {shape}"
    return True, data, ""


def filter_commands_by_group(commands: List[str], group: str) -> List[str]:
    """Filter commands to only those under a specific command group.

    Args:
        commands: List of command paths (e.g., ["auth", "auth login", "records list"])
        group: Command group to filter by (e.g., "records")

    Returns:
        Commands that start with the group name
        e.g., ["records", "records list", "records get"]
    """
    return [cmd for cmd in commands if cmd == group or cmd.startswith(f"{group} ")]


def discover_nested_commands(
    cli_executable: str,
    path: str = "",
    depth: int = 0,
    max_depth: int = 3,
    skip_list: List[str] = None,
    timeout: int = 30
) -> List[str]:
    """Recursively discover nested command groups.

    Args:
        cli_executable: Full path to CLI executable (or cli name if in PATH)
    """
    skip_list = skip_list or []
    skip_tuple = tuple(skip_list)
    cache_key = (cli_executable, path, depth, max_depth, skip_tuple, timeout)

    cached = _DISCOVER_NESTED_COMMANDS_CACHE.get(cache_key)
    if cached is not None:
        return list(cached)

    if depth >= max_depth:
        _DISCOVER_NESTED_COMMANDS_CACHE[cache_key] = ()
        return []

    args = path.split() + ["--help"] if path else ["--help"]
    result = run_cli_command(cli_executable, args, timeout=timeout)
    commands = parse_help_commands(result.stdout)

    discovered = []
    for cmd in commands:
        new_path = f"{path} {cmd}".strip()
        discovered.append(new_path)
        # Only recurse into commands not in skip_list
        # (skip_list prevents recursion, not discovery)
        if cmd not in skip_list:
            nested = discover_nested_commands(cli_executable, new_path, depth + 1, max_depth, skip_list, timeout)
            discovered.extend(nested)

    _DISCOVER_NESTED_COMMANDS_CACHE[cache_key] = tuple(discovered)
    return discovered


def extract_usage_command_paths(usage: Dict) -> set[str]:
    """Extract every command path documented by generated usage.json."""
    if not isinstance(usage, dict):
        raise ValueError("usage.json root must be an object")
    commands = usage.get("commands")
    if not isinstance(commands, dict):
        raise ValueError("usage.json must contain a commands object")

    paths = set()

    def walk(command_tree: Dict, prefix: str) -> None:
        for name, node in command_tree.items():
            if not isinstance(name, str) or not name:
                raise ValueError("usage.json command names must be non-empty strings")
            if not isinstance(node, dict):
                raise ValueError(f"usage.json command '{name}' must be an object")

            command_path = f"{prefix} {name}".strip()
            paths.add(command_path)

            children = node.get("commands")
            if children is not None:
                if not isinstance(children, dict):
                    raise ValueError(f"usage.json command '{command_path}' commands must be an object")
                walk(children, command_path)

    walk(commands, "")
    return paths


def extract_usage_command_parameters(usage: Dict) -> Dict[str, Dict[str, List[Dict]]]:
    """Extract every command path and its documented arguments/options."""
    if not isinstance(usage, dict):
        raise ValueError("usage.json root must be an object")
    commands = usage.get("commands")
    if not isinstance(commands, dict):
        raise ValueError("usage.json must contain a commands object")

    parameters = {}

    def walk(command_tree: Dict, prefix: str) -> None:
        for name, node in command_tree.items():
            if not isinstance(name, str) or not name:
                raise ValueError("usage.json command names must be non-empty strings")
            if not isinstance(node, dict):
                raise ValueError(f"usage.json command '{name}' must be an object")

            command_path = f"{prefix} {name}".strip()
            parameters[command_path] = {
                "arguments": list(node.get("arguments") or []),
                "options": list(node.get("options") or []),
            }

            children = node.get("commands")
            if children is not None:
                if not isinstance(children, dict):
                    raise ValueError(f"usage.json command '{command_path}' commands must be an object")
                walk(children, command_path)

    walk(commands, "")
    return parameters


def leaf_command_paths(command_paths: set[str]) -> set[str]:
    """Return command paths that have no documented child commands."""
    return {
        path for path in command_paths
        if not any(other.startswith(f"{path} ") for other in command_paths)
    }


def check_file_contains_patterns(file_path: Path, patterns: List[str]) -> Dict[str, bool]:
    """Check if file contains all specified patterns."""
    content = file_path.read_text()
    return {pattern: pattern in content for pattern in patterns}


def get_python_version_from_venv(venv_path: Path) -> str:
    """Get Python version from venv."""
    python_exe = venv_path / "bin" / "python3"
    if not python_exe.exists():
        python_exe = venv_path / "bin" / "python"

    if python_exe.is_symlink():
        # Follow symlink to actual executable
        python_exe = python_exe.resolve()

    result = subprocess.run([str(python_exe), "--version"], capture_output=True, text=True)
    return result.stdout.strip()


def get_list_commands(
    cli_name: str,
    test_config: Dict,
    discovered_commands: List[str]
) -> List[str]:
    """Get list commands for a CLI, using CLI-specific config or standard pattern.

    This function checks:
    1. CLI-specific list_commands in test_config (highest priority)
    2. Standard pattern: commands ending with " list" or equal to "list"

    Args:
        cli_name: Name of the CLI tool
        test_config: Test configuration dictionary
        discovered_commands: List of discovered command paths

    Returns:
        List of command paths that are list-style commands
    """
    # Check for CLI-specific list commands first
    cli_specific = test_config.get("cli_specific", {}).get(cli_name, {})
    if "list_commands" in cli_specific:
        return cli_specific["list_commands"]

    # Fall back to standard pattern
    return [cmd for cmd in discovered_commands if cmd.endswith(" list") or cmd == "list"]


def get_fixture_args(
    cli_name: str,
    cmd_path: str,
    cli_fixtures: Dict,
    test_config: Dict
) -> List[str]:
    """
    Get additional args needed for a command based on fixtures.

    Looks up the command path in the test_config's param_fixtures section
    and returns the corresponding fixture values as command-line arguments.

    Args:
        cli_name: Name of the CLI tool
        cmd_path: Command path (e.g., "database page list")
        cli_fixtures: Loaded fixtures from <cli_name>.json
        test_config: Test configuration dictionary

    Returns:
        List of args like ["--database-id", "abc123"] or ["12345"] for positional args

    Special keys:
        - Keys starting with "_pos" are treated as positional arguments (value only, no flag)
        - Example: "_pos1" = "app_id" results in just the value being added
    """
    param_fixtures = test_config.get("cli_specific", {}).get(cli_name, {}).get("param_fixtures", {})

    cmd_params = param_fixtures.get(cmd_path, {})
    if not cmd_params:
        return []

    positional_args = []
    flag_args = []

    for param_flag, fixture_key in cmd_params.items():
        # Support nested keys like "comment_params.page_id"
        value = cli_fixtures
        for key in fixture_key.split("."):
            value = value.get(key, {}) if isinstance(value, dict) else None
            if value is None:
                break

        if value and not isinstance(value, dict):
            if param_flag.startswith("_pos"):
                # Positional argument - just add the value
                positional_args.append((param_flag, str(value)))
            else:
                # Flag argument - add flag and value
                flag_args.extend([param_flag, str(value)])

    # Sort positional args by their key (_pos1, _pos2, etc.) and extract values
    positional_args.sort(key=lambda x: x[0])
    positional_values = [v for _, v in positional_args]

    # Positional args come first, then flags
    return positional_values + flag_args


def get_cli_timeout(cli_name: str, test_config: Dict) -> int:
    """Get command timeout for a CLI, checking per-CLI override first."""
    timeout = test_config["general"]["command_timeout"]
    if cli_name in test_config.get("cli_specific", {}):
        timeout = test_config["cli_specific"][cli_name].get("command_timeout", timeout)
    return timeout


def discover_list_commands(
    cli_executable: str,
    cli_name: str,
    test_config: Dict,
    command_filter: Optional[str] = None,
) -> Tuple[List[str], int]:
    """Discover and filter list commands for a CLI.

    Returns:
        Tuple of (list_commands, timeout).
    """
    skip_list = test_config["command_discovery"]["skip_list"]
    timeout = get_cli_timeout(cli_name, test_config)
    max_depth = test_config["general"]["max_nested_depth"]

    if cli_name in test_config.get("cli_specific", {}):
        max_depth = test_config["cli_specific"][cli_name].get("max_nested_depth", max_depth)

    commands = discover_nested_commands(cli_executable, "", 0, max_depth, skip_list, timeout)
    list_commands = get_list_commands(cli_name, test_config, commands)

    if command_filter:
        list_commands = filter_commands_by_group(list_commands, command_filter)

    return list_commands, timeout


def get_uv_tool_venv_dir(cli_dir: Path, cli_name: str) -> Optional[Path]:
    """Get the uv tool venv path by reading package name from pyproject.toml.

    uv tool install stores venvs at ~/.local/share/uv/tools/<package-name>.
    The package name comes from pyproject.toml [project].name field.
    Falls back to {cli_name}-cli if pyproject.toml can't be read.
    """
    import tomllib

    pkg_name = f"{cli_name}-cli"
    pyproject = cli_dir / "pyproject.toml"
    if pyproject.exists():
        try:
            with open(pyproject, "rb") as f:
                data = tomllib.load(f)
            pkg_name = data.get("project", {}).get("name", pkg_name)
        except Exception:
            pass

    normalized_pkg_name = re.sub(r"[-_.]+", "-", pkg_name).lower()
    uv_tool_dir = Path.home() / ".local" / "share" / "uv" / "tools" / normalized_pkg_name
    if uv_tool_dir.exists():
        return uv_tool_dir
    return None


def get_pkg_dir(cli_dir: Path, cli_name: str) -> Path:
    """Get the CLI package directory from the CLI repo path and CLI name."""
    pkg_name = cli_name.replace("-", "_") + "_cli"
    return cli_dir / pkg_name


def cli_has_browser_type(
    cli_dir: Path,
    cli_name: str,
    browser_clis=None,
) -> bool:
    """Return True when a CLI declares browser-session/browser automation support."""
    browser_clis = browser_clis or ()
    pkg_dir = get_pkg_dir(cli_dir, cli_name)
    if cli_name in browser_clis:
        return True
    if not pkg_dir.exists():
        return False
    if (pkg_dir / "browser.py").exists():
        return True
    if _file_assigns_browser_session(pkg_dir / "config.py", "CREDENTIAL_TYPES"):
        return True
    commands_dir = pkg_dir / "commands"
    if not commands_dir.exists():
        return False
    return any(
        _file_assigns_browser_session(path, "COMMAND_CREDENTIALS")
        for path in commands_dir.rglob("*.py")
    )


def cli_uses_shared_browser_http(cli_dir: Path, cli_name: str) -> bool:
    """Return True when CLI source imports cli_tools_shared.browser_http helpers."""
    pkg_dir = get_pkg_dir(cli_dir, cli_name)
    if not pkg_dir.exists():
        return False
    for py_file in pkg_dir.rglob("*.py"):
        if "__pycache__" in py_file.parts:
            continue
        if _file_imports_shared_browser_http(py_file):
            return True
    return False


def _file_assigns_browser_session(path: Path, assignment_name: str) -> bool:
    """Check whether a Python assignment contains the browser_session credential."""
    if not path.exists():
        return False
    try:
        import ast

        tree = ast.parse(path.read_text())
    except (OSError, SyntaxError, UnicodeDecodeError):
        return False

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == assignment_name for target in node.targets):
            continue
        for child in ast.walk(node.value):
            if isinstance(child, ast.Attribute) and child.attr == "BROWSER_SESSION":
                return True
            if isinstance(child, ast.Constant) and child.value == "browser_session":
                return True
    return False


def _file_imports_shared_browser_http(path: Path) -> bool:
    """Check whether a Python source file imports the shared browser HTTP API."""
    try:
        import ast

        tree = ast.parse(path.read_text())
    except (OSError, SyntaxError, UnicodeDecodeError):
        return False

    common_exports = {
        "BrowserAuthState",
        "BrowserAuthStateError",
        "BrowserAuthenticatedHttpClient",
        "BrowserCookie",
        "BrowserHttpResult",
        "RelayFormRequest",
        "RelayGraphQLClient",
        "DEFAULT_BROWSER_HEADERS",
        "decode_json_at_marker",
        "extract_embedded_define",
        "iter_json_objects",
        "iter_json_values_at_marker",
        "required_path",
    }

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "cli_tools_shared.browser_http":
                    return True
        if isinstance(node, ast.ImportFrom):
            if node.module == "cli_tools_shared.browser_http":
                return True
            if node.module == "cli_tools_shared":
                imported = {alias.name for alias in node.names}
                if imported & common_exports:
                    return True
    return False
