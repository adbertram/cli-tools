"""AST-based parser for standardized CLI tools.

Parses Python CLI tool source code to extract metadata:
- main.py: CLI name, help text, command groups (from app.add_typer())
- commands/*.py: Commands and parameters (from @app.command() and function signatures)
- config.py: Credential env var names (from os.getenv() calls)
- .env.example: Credential documentation and comments
- pyproject.toml: CLI entry point name, version, description
"""
import ast
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    CLIToolMetadata,
    CommandGroup,
    Command,
    CommandParameter,
    CredentialField,
)

# Parameters to exclude from n8n node generation (CLI output-specific)
EXCLUDED_PARAMS = {
    "table", "properties", "output", "filter", "ctx", "version",
}
EXCLUDED_FLAGS = {
    "--table", "-t", "--properties", "-p", "--output", "-o",
    "--filter", "-f", "--version", "-v",
}


class ParserError(Exception):
    """Error during CLI tool parsing."""
    pass


def _title_case(name: str) -> str:
    """Convert kebab-case or snake_case name to Title Case."""
    return name.replace("-", " ").replace("_", " ").title()


def _get_string_value(node: ast.expr) -> Optional[str]:
    """Extract string value from an AST node."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _get_const_value(node: ast.expr) -> Any:
    """Extract constant value from an AST node."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        val = _get_const_value(node.operand)
        if val is not None:
            return -val
    if isinstance(node, ast.Attribute):
        # e.g., typer.Argument or something.NONE
        return None
    if isinstance(node, ast.Name):
        if node.id == "None":
            return None
        if node.id == "True":
            return True
        if node.id == "False":
            return False
    return None


def _find_package_dir(tool_dir: Path) -> Optional[Path]:
    """Find the Python package directory within a CLI tool directory.

    Looks for *_cli/ directories that contain __init__.py.
    """
    for child in tool_dir.iterdir():
        if child.is_dir() and child.name.endswith("_cli"):
            if (child / "__init__.py").exists():
                return child
    # Also check for hyphenated names (e.g., my-tool_cli)
    for child in tool_dir.iterdir():
        if child.is_dir() and "_cli" in child.name:
            if (child / "__init__.py").exists():
                return child
    return None


def _parse_pyproject(tool_dir: Path) -> Dict[str, str]:
    """Parse pyproject.toml for CLI metadata."""
    pyproject_path = tool_dir / "pyproject.toml"
    result = {"name": "", "version": "0.1.0", "description": "", "cli_command": ""}

    if not pyproject_path.exists():
        return result

    content = pyproject_path.read_text()

    # Parse version
    match = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if match:
        result["version"] = match.group(1)

    # Parse description
    match = re.search(r'^description\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if match:
        result["description"] = match.group(1)

    # Parse project name
    match = re.search(r'^name\s*=\s*"([^"]+)"', content, re.MULTILINE)
    if match:
        result["name"] = match.group(1)

    # Parse entry point command name
    match = re.search(r'^\s*(\S+)\s*=\s*"[^"]+:app"', content, re.MULTILINE)
    if match:
        result["cli_command"] = match.group(1)

    return result


def _parse_main_py(main_path: Path) -> Tuple[str, str, List[Dict[str, str]]]:
    """Parse main.py to extract CLI name, help text, and command group registrations.

    Returns:
        Tuple of (cli_name, help_text, list of {name, help} dicts)
    """
    if not main_path.exists():
        return "", "", []

    source = main_path.read_text()
    tree = ast.parse(source)

    cli_name = ""
    help_text = ""
    groups = []

    for node in ast.walk(tree):
        # Find typer.Typer(name="...", help="...")
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "app":
                    if isinstance(node.value, ast.Call):
                        for kw in node.value.keywords:
                            if kw.arg == "name":
                                cli_name = _get_string_value(kw.value) or ""
                            elif kw.arg == "help":
                                help_text = _get_string_value(kw.value) or ""

        # Find app.add_typer(..., name="order", help="...")
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            if (isinstance(call.func, ast.Attribute)
                    and call.func.attr == "add_typer"
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id == "app"):
                group_info = {"name": "", "help": ""}
                for kw in call.keywords:
                    if kw.arg == "name":
                        group_info["name"] = _get_string_value(kw.value) or ""
                    elif kw.arg == "help":
                        group_info["help"] = _get_string_value(kw.value) or ""
                if group_info["name"] and group_info["name"] != "auth":
                    groups.append(group_info)

    return cli_name, help_text, groups


def _parse_type_annotation(annotation: Optional[ast.expr]) -> Tuple[str, str, bool, Optional[List[str]]]:
    """Parse a type annotation to determine n8n type, python type, and if it's a list.

    Returns:
        Tuple of (n8n_type, python_type, is_list, choices)
    """
    if annotation is None:
        return "string", "str", False, None

    # Handle Optional[X] -> get inner type
    if isinstance(annotation, ast.Subscript):
        if isinstance(annotation.value, ast.Name) and annotation.value.id == "Optional":
            return _parse_type_annotation(annotation.slice)
        if isinstance(annotation.value, ast.Name) and annotation.value.id == "List":
            inner_type, inner_python, _, _ = _parse_type_annotation(annotation.slice)
            return inner_type, f"List[{inner_python}]", True, None

    if isinstance(annotation, ast.Name):
        type_name = annotation.id
        if type_name in ("str", "string"):
            return "string", "str", False, None
        elif type_name in ("int", "float"):
            return "number", type_name, False, None
        elif type_name == "bool":
            return "boolean", "bool", False, None
        else:
            return "string", type_name, False, None

    if isinstance(annotation, ast.Attribute):
        return "string", "str", False, None

    return "string", "str", False, None


def _parse_typer_call(call: ast.Call) -> Dict[str, Any]:
    """Parse a typer.Argument(...) or typer.Option(...) call.

    Returns dict with: default, help_text, cli_flag, cli_short, is_argument
    """
    result: Dict[str, Any] = {
        "default": None,
        "help_text": None,
        "cli_flag": None,
        "cli_short": None,
        "is_argument": False,
        "required": False,
    }

    if not isinstance(call.func, ast.Attribute):
        return result

    func_name = call.func.attr

    if func_name == "Argument":
        result["is_argument"] = True
        # Check if required (first arg is ...)
        if call.args:
            first_arg = call.args[0]
            if isinstance(first_arg, ast.Constant) and first_arg.value is ...:
                result["required"] = True
            else:
                result["default"] = _get_const_value(first_arg)
        else:
            result["required"] = True
    elif func_name == "Option":
        result["is_argument"] = False
        # Positional args are flag names
        for arg in call.args:
            val = _get_string_value(arg)
            if val:
                if val.startswith("--"):
                    result["cli_flag"] = val
                elif val.startswith("-") and len(val) == 2:
                    result["cli_short"] = val
        # Check for default value
        if call.args:
            first = call.args[0]
            val = _get_const_value(first)
            if val is not None and not isinstance(val, str):
                result["default"] = val
            elif isinstance(first, ast.Constant) and first.value is None:
                result["default"] = None
    else:
        return result

    # Parse keyword arguments
    for kw in call.keywords:
        if kw.arg == "help":
            result["help_text"] = _get_string_value(kw.value)
        elif kw.arg == "default":
            result["default"] = _get_const_value(kw.value)

    return result


def _should_exclude_param(name: str, cli_flag: Optional[str], cli_short: Optional[str]) -> bool:
    """Check if a parameter should be excluded from n8n generation."""
    if name in EXCLUDED_PARAMS:
        return True
    if cli_flag and cli_flag in EXCLUDED_FLAGS:
        return True
    if cli_short and cli_short in EXCLUDED_FLAGS:
        return True
    return False


def _parse_command_file(file_path: Path) -> List[Command]:
    """Parse a commands/*.py file to extract commands and their parameters."""
    if not file_path.exists():
        return []

    source = file_path.read_text()
    tree = ast.parse(source)

    commands = []

    for node in ast.walk(tree):
        # Find @app.command("name") decorated functions
        if not isinstance(node, ast.FunctionDef):
            continue

        command_name = None
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call):
                if isinstance(decorator.func, ast.Attribute) and decorator.func.attr == "command":
                    if decorator.args:
                        command_name = _get_string_value(decorator.args[0])
                    else:
                        # Use function name if no explicit name
                        command_name = node.name

        if command_name is None:
            continue

        # Extract docstring
        help_text = ast.get_docstring(node)
        # Clean up the docstring - take first line/paragraph only
        if help_text:
            first_para = help_text.split("\n\n")[0]
            # Remove "Examples:" section
            if "Examples:" in first_para:
                first_para = first_para.split("Examples:")[0]
            help_text = first_para.strip().split("\n")[0].strip()

        # Extract parameters from function signature
        parameters = []
        for arg in node.args.args:
            param_name = arg.arg
            if param_name == "self":
                continue

            # Parse type annotation
            n8n_type, python_type, is_list, choices = _parse_type_annotation(arg.annotation)

            # Find default value in function defaults
            # defaults are right-aligned with args
            num_args = len(node.args.args)
            num_defaults = len(node.args.defaults)
            arg_index = node.args.args.index(arg)
            default_index = arg_index - (num_args - num_defaults)

            typer_info: Dict[str, Any] = {
                "default": None,
                "help_text": None,
                "cli_flag": None,
                "cli_short": None,
                "is_argument": False,
                "required": False,
            }

            if default_index >= 0:
                default_node = node.args.defaults[default_index]
                if isinstance(default_node, ast.Call):
                    typer_info = _parse_typer_call(default_node)
                else:
                    typer_info["default"] = _get_const_value(default_node)

            # Determine cli_flag from param name if not set
            if not typer_info["is_argument"] and not typer_info["cli_flag"]:
                typer_info["cli_flag"] = f"--{param_name.replace('_', '-')}"

            # Skip excluded parameters
            if _should_exclude_param(param_name, typer_info["cli_flag"], typer_info["cli_short"]):
                continue

            # Determine required status
            is_required = typer_info["is_argument"] and typer_info["required"]

            param = CommandParameter(
                name=param_name,
                cli_flag=typer_info["cli_flag"] if not typer_info["is_argument"] else None,
                cli_short=typer_info["cli_short"],
                param_type=n8n_type,
                python_type=python_type,
                default=typer_info["default"],
                required=is_required,
                help_text=typer_info["help_text"],
                is_argument=typer_info["is_argument"],
                is_list=is_list,
                choices=choices,
            )
            parameters.append(param)

        cmd = Command(
            name=command_name,
            display_name=_title_case(command_name),
            help_text=help_text,
            parameters=parameters,
        )
        commands.append(cmd)

    return commands


def _parse_credentials(tool_dir: Path, pkg_dir: Path) -> List[CredentialField]:
    """Parse config.py and .env.example to extract credential information."""
    credentials = []
    env_comments: Dict[str, str] = {}

    # Parse .env.example for comments
    env_example = tool_dir / ".env.example"
    if env_example.exists():
        content = env_example.read_text()
        current_comment = ""
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("#"):
                current_comment = line.lstrip("# ").strip()
            elif "=" in line:
                var_name = line.split("=")[0].strip()
                if current_comment:
                    env_comments[var_name] = current_comment
                current_comment = ""
            else:
                current_comment = ""

    # Parse config.py for os.getenv() calls
    config_path = pkg_dir / "config.py"
    if not config_path.exists():
        return credentials

    source = config_path.read_text()
    tree = ast.parse(source)

    seen_vars = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # Look for os.getenv("VAR_NAME", default) calls
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "getenv"):
            continue

        if not node.args:
            continue

        env_var = _get_string_value(node.args[0])
        if not env_var or env_var in seen_vars:
            continue
        seen_vars.add(env_var)

        # Skip non-credential env vars (browser settings, etc.)
        if any(skip in env_var.upper() for skip in ["HEADLESS", "BROWSER", "DEBUG"]):
            continue

        default_val = None
        if len(node.args) > 1:
            default_val = _get_string_value(node.args[1])

        # Determine if secret
        secret_keywords = ["KEY", "SECRET", "TOKEN", "PASSWORD"]
        is_secret = any(kw in env_var.upper() for kw in secret_keywords)

        # Generate display name from env var
        # e.g., BRICKOWL_API_KEY -> API Key
        parts = env_var.split("_")
        # Remove the prefix (tool name) - find where it ends
        # e.g., BRICKOWL_API_KEY -> skip "BRICKOWL" -> "API KEY"
        display_parts = []
        found_separator = False
        for part in parts:
            if found_separator:
                display_parts.append(part.title())
            elif part.upper() in ("API", "BASE", "CLIENT", "ACCESS", "REFRESH", "TOKEN"):
                found_separator = True
                display_parts.append(part.title())
        if not display_parts:
            # Fallback: use last 2 parts
            display_parts = [p.title() for p in parts[-2:]]

        display_name = " ".join(display_parts)

        cred = CredentialField(
            env_var=env_var,
            display_name=display_name,
            required=default_val is None,
            default=default_val,
            is_secret=is_secret,
            comment=env_comments.get(env_var),
        )
        credentials.append(cred)

    return credentials


def parse_cli_tool(tool_name: str, tools_dir: str) -> CLIToolMetadata:
    """Parse a CLI tool and extract its complete metadata.

    Args:
        tool_name: Name of the CLI tool (directory name under tools_dir)
        tools_dir: Path to the CLI tools directory

    Returns:
        CLIToolMetadata with all parsed information

    Raises:
        ParserError: If the tool cannot be parsed
    """
    tool_dir = Path(tools_dir) / tool_name
    if not tool_dir.is_dir():
        raise ParserError(f"CLI tool directory not found: {tool_dir}")

    # Find package directory
    pkg_dir = _find_package_dir(tool_dir)
    if pkg_dir is None:
        raise ParserError(f"No Python package found in {tool_dir} (expected *_cli/ directory)")

    # Parse pyproject.toml
    pyproject = _parse_pyproject(tool_dir)

    # Parse main.py
    main_path = pkg_dir / "main.py"
    cli_name, main_help, group_infos = _parse_main_py(main_path)

    # Parse command files
    commands_dir = pkg_dir / "commands"
    command_groups = []

    for group_info in group_infos:
        group_name = group_info["name"]
        cmd_file = commands_dir / f"{group_name}.py"
        if not cmd_file.exists():
            # Try with underscores
            cmd_file = commands_dir / f"{group_name.replace('-', '_')}.py"
        if not cmd_file.exists():
            continue

        commands = _parse_command_file(cmd_file)
        if not commands:
            continue

        group = CommandGroup(
            name=group_name,
            display_name=_title_case(group_name),
            help_text=group_info.get("help", ""),
            commands=commands,
        )
        command_groups.append(group)

    # Parse credentials
    credentials = _parse_credentials(tool_dir, pkg_dir)

    # Build metadata
    metadata = CLIToolMetadata(
        name=tool_name,
        display_name=_title_case(tool_name),
        description=pyproject.get("description", main_help or ""),
        version=pyproject.get("version", "0.1.0"),
        cli_command=pyproject.get("cli_command", tool_name),
        command_groups=command_groups,
        credentials=credentials,
    )

    return metadata


def is_cli_tool(tool_dir: Path) -> bool:
    """Check if a directory is a valid CLI tool (has pyproject.toml and *_cli/ package)."""
    if not tool_dir.is_dir():
        return False
    if not (tool_dir / "pyproject.toml").exists():
        return False
    return _find_package_dir(tool_dir) is not None
