"""AST-based parser for standardized CLI tools.

Parses Python CLI tool source code to extract metadata:
- main.py: CLI name, help text, command groups (from app.add_typer())
- commands/*.py: Commands and parameters (from @app.command() and function signatures)
- .env / .env.example: Credential env var names and documentation comments
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
        # Ellipsis (...) is used as a sentinel in Typer for required args — treat as None
        if node.value is ...:
            return None
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

    # Parse entry point command name from [project.scripts] section
    # Matches lines like: bricklink = "bricklink_cli.main:main"
    match = re.search(r'^\[project\.scripts\]\s*\n\s*(\S+)\s*=\s*"[^"]+"', content, re.MULTILINE)
    if match:
        result["cli_command"] = match.group(1)

    return result


def _parse_main_py(main_path: Path) -> Tuple[str, str, List[Dict[str, str]]]:
    """Parse main.py to extract CLI name, help text, and command group registrations.

    Returns:
        Tuple of (cli_name, help_text, list of {name, help, module, app_var} dicts)

    Each group dict contains:
        - name: The group name (e.g., "seller-orders")
        - help: Help text
        - module: The Python module name (e.g., "orders" from orders.app)
        - app_var: The app variable name (e.g., "app" or "shipping_label_app")
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

        # Find app.add_typer(module.app_var, name="order", help="...")
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
            call = node.value
            if (isinstance(call.func, ast.Attribute)
                    and call.func.attr == "add_typer"
                    and isinstance(call.func.value, ast.Name)
                    and call.func.value.id == "app"):
                group_info = {"name": "", "help": "", "module": "", "app_var": "app"}

                # Extract module and app_var from first positional arg (e.g., orders.app)
                if call.args:
                    first_arg = call.args[0]
                    if isinstance(first_arg, ast.Attribute):
                        group_info["app_var"] = first_arg.attr
                        if isinstance(first_arg.value, ast.Name):
                            group_info["module"] = first_arg.value.id

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


def _parse_command_credentials(tree: ast.Module) -> Dict[str, List[str]]:
    """Extract COMMAND_CREDENTIALS mapping from a parsed AST module.

    Looks for module-level assignment:
        COMMAND_CREDENTIALS = {
            "list": ["api_key"],
            "get": ["browser_session"],
        }

    Returns dict mapping command name to list of credential types.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == "COMMAND_CREDENTIALS":
                if isinstance(node.value, ast.Dict):
                    result: Dict[str, List[str]] = {}
                    for key, value in zip(node.value.keys, node.value.values):
                        cmd_name = _get_string_value(key)
                        if cmd_name and isinstance(value, ast.List):
                            cred_types = []
                            for elt in value.elts:
                                ct = _get_string_value(elt)
                                if ct:
                                    cred_types.append(ct)
                            result[cmd_name] = cred_types
                    return result
    return {}


def _parse_command_file(file_path: Path, app_var: str = "app") -> List[Command]:
    """Parse a commands/*.py file to extract commands and their parameters.

    Args:
        file_path: Path to the command file
        app_var: Name of the app variable to parse commands from (e.g., "app",
                 "shipping_label_app"). Only commands decorated with this
                 variable's .command() will be included.
    """
    if not file_path.exists():
        return []

    source = file_path.read_text()
    tree = ast.parse(source)

    # First, extract COMMAND_CREDENTIALS mapping
    cmd_cred_map = _parse_command_credentials(tree)

    commands = []

    for node in ast.walk(tree):
        # Find @<app_var>.command("name") decorated functions
        if not isinstance(node, ast.FunctionDef):
            continue

        command_name = None
        for decorator in node.decorator_list:
            if isinstance(decorator, ast.Call):
                if (isinstance(decorator.func, ast.Attribute)
                        and decorator.func.attr == "command"
                        and isinstance(decorator.func.value, ast.Name)
                        and decorator.func.value.id == app_var):
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
            credential_types=cmd_cred_map.get(command_name, []),
        )
        commands.append(cmd)

    return commands


# Maps CredentialType enum values to their auth-related env var names.
# Sourced from cli_tools_shared.credentials.CredentialType.all_fields.
_CREDENTIAL_TYPE_FIELDS = {
    "api_key": {"API_KEY", "BASE_URL"},
    "personal_access_token": {"PERSONAL_ACCESS_TOKEN", "BASE_URL"},
    "oauth": {"CLIENT_ID", "CLIENT_SECRET", "ACCESS_TOKEN", "REFRESH_TOKEN", "TOKEN_EXPIRES_AT", "BASE_URL"},
    "oauth_authorization_code": {"CLIENT_ID", "CLIENT_SECRET", "ACCESS_TOKEN", "REFRESH_TOKEN", "TOKEN_EXPIRES_AT", "REDIRECT_URI", "BASE_URL"},
    "username_password": {"USERNAME", "PASSWORD", "BASE_URL"},
    "browser_session": {"USERNAME", "PASSWORD", "BASE_URL"},
}


def _detect_credential_types(pkg_dir: Path) -> List[str]:
    """Detect credential types from config.py via AST.

    Handles both patterns:
    - CREDENTIAL_TYPE = CredentialType.API_KEY  (singular, deprecated)
    - CREDENTIAL_TYPES = [CredentialType.API_KEY, CredentialType.OAUTH]  (plural)

    Returns list of credential type strings (e.g., ["api_key"]) or empty list.
    """
    config_path = pkg_dir / "config.py"
    if not config_path.exists():
        return []

    try:
        tree = ast.parse(config_path.read_text())
    except SyntaxError:
        return []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if not isinstance(target, ast.Name):
                continue
            if target.id == "CREDENTIAL_TYPE":
                # Singular: CREDENTIAL_TYPE = CredentialType.API_KEY
                if isinstance(node.value, ast.Attribute):
                    return [node.value.attr.lower()]
            elif target.id == "CREDENTIAL_TYPES":
                # Plural: CREDENTIAL_TYPES = [CredentialType.API_KEY, ...]
                if isinstance(node.value, ast.List):
                    types = []
                    for elt in node.value.elts:
                        if isinstance(elt, ast.Attribute):
                            types.append(elt.attr.lower())
                    return types
    return []


def _parse_env_fields(
    tool_dir: Path, pkg_dir: Path,
) -> Tuple[List[CredentialField], List[CredentialField], List[str]]:
    """Parse .env file and split into credential fields vs config fields.

    Uses CREDENTIAL_TYPE(S) from config.py to determine which env vars are
    auth credentials. Remaining vars become config fields (e.g., BASE_ID)
    that appear as top-level node parameters.

    Returns:
        Tuple of (credentials, config_fields, credential_types)
    """
    env_comments: Dict[str, str] = {}

    # Internal vars to skip
    SKIP_VARS = {"ACTIVE"}

    # Detect which env vars are auth credentials (supports multiple types)
    cred_types = _detect_credential_types(pkg_dir)
    # Union all auth vars across all detected types
    auth_vars: Dict[str, str] = {}  # env_var -> first credential_type that claims it
    for ct in cred_types:
        for var in _CREDENTIAL_TYPE_FIELDS.get(ct, set()):
            if var not in auth_vars:
                auth_vars[var] = ct

    # Find env file: .env.example for structure, else .env, else first .env.*
    env_file = tool_dir / ".env.example"
    if not env_file.exists():
        env_file = tool_dir / ".env"
    if not env_file.exists():
        for f in sorted(tool_dir.glob(".env.*")):
            env_file = f
            break
    if not env_file.exists():
        return [], []

    # First pass: collect comments
    current_comment = ""
    for line in env_file.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            current_comment = stripped.lstrip("# ").strip()
        elif "=" in stripped and stripped:
            var_name = stripped.split("=", 1)[0].strip()
            if current_comment:
                env_comments[var_name] = current_comment
            current_comment = ""
        else:
            current_comment = ""

    # Second pass: build fields and split by type
    credentials = []
    config_fields = []

    for line in env_file.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        env_var = stripped.split("=", 1)[0].strip()
        if env_var in SKIP_VARS:
            continue

        secret_keywords = ["KEY", "SECRET", "TOKEN", "PASSWORD"]
        is_secret = any(kw in env_var.upper() for kw in secret_keywords)

        parts = env_var.split("_")
        display_name = " ".join(p.title() for p in parts)
        field_name = parts[0].lower() + "".join(w.title() for w in parts[1:])

        field = CredentialField(
            env_var=env_var,
            field_name=field_name,
            display_name=display_name,
            required=True,
            default=None,
            is_secret=is_secret,
            comment=env_comments.get(env_var),
            credential_type=auth_vars.get(env_var, ""),
        )

        if env_var in auth_vars:
            credentials.append(field)
        else:
            config_fields.append(field)

    return credentials, config_fields, cred_types


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
        module_name = group_info.get("module", "")
        app_var = group_info.get("app_var", "app")

        # Use the module name from the import if available, otherwise fall back to group name
        file_base = module_name or group_name
        cmd_file = commands_dir / f"{file_base}.py"
        if not cmd_file.exists():
            # Try with underscores
            cmd_file = commands_dir / f"{file_base.replace('-', '_')}.py"
        if not cmd_file.exists():
            # Fall back to group name if module name didn't work
            if module_name and module_name != group_name:
                cmd_file = commands_dir / f"{group_name}.py"
                if not cmd_file.exists():
                    cmd_file = commands_dir / f"{group_name.replace('-', '_')}.py"
        if not cmd_file.exists():
            continue

        commands = _parse_command_file(cmd_file, app_var=app_var)
        if not commands:
            continue

        group = CommandGroup(
            name=group_name,
            display_name=_title_case(group_name),
            help_text=group_info.get("help", ""),
            commands=commands,
        )
        command_groups.append(group)

    # Parse credentials and config fields
    credentials, config_fields, credential_types = _parse_env_fields(tool_dir, pkg_dir)

    # Build metadata
    metadata = CLIToolMetadata(
        name=tool_name,
        display_name=_title_case(tool_name),
        description=pyproject.get("description", main_help or ""),
        version=pyproject.get("version", "0.1.0"),
        cli_command=pyproject.get("cli_command", tool_name),
        command_groups=command_groups,
        credentials=credentials,
        config_fields=config_fields,
        credential_types=credential_types,
    )

    return metadata


def is_cli_tool(tool_dir: Path) -> bool:
    """Check if a directory is a valid CLI tool (has pyproject.toml and *_cli/ package)."""
    if not tool_dir.is_dir():
        return False
    if not (tool_dir / "pyproject.toml").exists():
        return False
    return _find_package_dir(tool_dir) is not None
