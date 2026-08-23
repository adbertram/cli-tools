"""n8n TypeScript node package generator.

Takes parsed CLIToolMetadata and generates a complete n8n community node package.
"""
import json
import re
import shutil
from pathlib import Path
from typing import List

from .models import (
    CLIToolMetadata,
    CommandGroup,
    Command,
    CommandParameter,
)
from . import templates


class GeneratorError(Exception):
    """Error during n8n node package generation."""
    pass


# Maps credential type strings to PascalCase suffixes for file/class naming
_CRED_TYPE_SUFFIX = {
    "api_key": "ApiKey",
    "oauth": "Oauth",
    "oauth_authorization_code": "OauthCode",
    "personal_access_token": "Pat",
    "username_password": "UserPass",
    "browser_session": "BrowserSession",
}

# Maps credential type strings to display name suffixes
_CRED_TYPE_DISPLAY = {
    "api_key": "API Key",
    "oauth": "OAuth",
    "oauth_authorization_code": "OAuth Code",
    "personal_access_token": "PAT",
    "username_password": "User/Pass",
    "browser_session": "Browser Session",
}

# Maps credential type strings to node name suffixes (for multi-node packages)
_NODE_SUFFIX = {
    "api_key": "Api",
    "oauth": "Oauth",
    "oauth_authorization_code": "OauthCode",
    "personal_access_token": "Pat",
    "username_password": "UserPass",
    "browser_session": "Browser",
}

# Maps credential type strings to node display name suffixes
_NODE_DISPLAY_SUFFIX = {
    "api_key": "(API)",
    "oauth": "(OAuth)",
    "oauth_authorization_code": "(OAuth)",
    "personal_access_token": "(PAT)",
    "username_password": "(User/Pass)",
    "browser_session": "(Browser)",
}


def _to_pascal_case(name: str) -> str:
    """Convert kebab-case or snake_case to PascalCase."""
    return "".join(word.title() for word in re.split(r"[-_]", name))


def _to_camel_case(name: str) -> str:
    """Convert kebab-case or snake_case to camelCase."""
    pascal = _to_pascal_case(name)
    return pascal[0].lower() + pascal[1:] if pascal else ""


def _cred_type_name(tool_pascal: str, cred_type: str) -> str:
    """Build the credential type name for n8n (e.g., 'BrickowlApiKey')."""
    suffix = _CRED_TYPE_SUFFIX.get(cred_type, _to_pascal_case(cred_type))
    return f"{tool_pascal}{suffix}"


def _cred_camel_name(tool_pascal: str, cred_type: str) -> str:
    """Build the camelCase credential name for n8n (e.g., 'brickowlApiKey')."""
    name = _cred_type_name(tool_pascal, cred_type)
    return name[0].lower() + name[1:]


def _filter_command_groups_by_cred_type(
    command_groups: List[CommandGroup], cred_type: str
) -> List[CommandGroup]:
    """Filter command groups to only include commands that use the given credential type.

    Returns a new list of CommandGroup objects with only matching commands.
    Groups with no matching commands are excluded.

    If cred_type is empty, returns all command groups unchanged (no filtering).
    If no commands specify per-command credential types, returns all commands
    (assumes all commands use the tool-level credential type).
    """
    if not cred_type:
        # No filtering needed - return all commands
        return command_groups

    # Check if any command in any group specifies per-command credential types.
    # If none do, all commands implicitly use the tool-level credential type.
    any_cmd_has_cred_types = any(
        cmd.credential_types
        for group in command_groups
        for cmd in group.commands
    )
    if not any_cmd_has_cred_types:
        return command_groups

    filtered_groups = []
    for group in command_groups:
        matching_cmds = [
            cmd for cmd in group.commands
            if cred_type in cmd.credential_types
        ]
        if matching_cmds:
            filtered_group = CommandGroup(
                name=group.name,
                display_name=group.display_name,
                help_text=group.help_text,
                commands=matching_cmds,
            )
            filtered_groups.append(filtered_group)
    return filtered_groups


def _escape_ts_string(s: str) -> str:
    """Escape a string for use in TypeScript single-quoted strings."""
    return s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ")


def _generate_credential_fields_for_type(
    creds: List["CredentialField"],
) -> str:
    """Generate credential field entries for a single credential TypeScript file."""
    from .models import CredentialField  # noqa: avoid circular at module level
    fields = []
    for cred in creds:
        field_name = cred.field_name

        field_type = "string"
        type_options = ""
        if cred.is_secret:
            type_options = "\n\t\t\ttypeOptions: { password: true },"

        required_str = ""
        if cred.required:
            required_str = "\n\t\t\trequired: true,"

        field_str = templates.CREDENTIAL_FIELD_TEMPLATE % {
            "display_name": _escape_ts_string(cred.display_name),
            "field_name": field_name,
            "field_type": field_type,
            "type_options": type_options,
            "default": cred.default or "",
            "required": required_str,
        }
        fields.append(field_str)

    return "\n".join(fields)


def _generate_credential_env_code(
    metadata: CLIToolMetadata, for_cred_type: str = ""
) -> str:
    """Generate TypeScript code that maps n8n credentials and config fields to env vars.

    Produces code that reads credentials from n8n and passes them as environment
    variables to the CLI subprocess.

    Args:
        metadata: The CLI tool metadata
        for_cred_type: If specified, only generate code for this credential type.
                      If empty, generates code for all credential types.
    """
    has_creds = bool(metadata.credentials)
    has_config = bool(metadata.config_fields)
    if not has_creds and not has_config:
        return ""

    pascal_name = _to_pascal_case(metadata.name)
    lines = [
        "\t\t// Build env vars for CLI subprocess",
        "\t\tconst env: Record<string, string> = {};",
        "\t\tObject.keys(process.env).forEach(k => { if (process.env[k]) env[k] = process.env[k]!; });",
    ]

    if has_creds:
        # Determine which credential types to process
        cred_types_to_process = [for_cred_type] if for_cred_type else metadata.credential_types

        for ct in cred_types_to_process:
            type_creds = [c for c in metadata.credentials if c.credential_type == ct]
            if not type_creds:
                continue
            camel = _cred_camel_name(pascal_name, ct)
            var_name = f"creds{_CRED_TYPE_SUFFIX.get(ct, ct.title())}"
            lines.append(f"\t\tconst {var_name} = await this.getCredentials('{camel}');")
            for cred in type_creds:
                lines.append(
                    f"\t\tif ({var_name}.{cred.field_name}) env['{cred.env_var}'] = {var_name}.{cred.field_name} as string;"
                )

    lines.append("")  # trailing blank line for readability
    return "\n".join(lines)


def _generate_config_properties(metadata: CLIToolMetadata) -> str:
    """Generate top-level node properties for config fields (non-auth env vars).

    Config fields are NOT added as node properties because CLI tools read their
    own .env profiles on the server. The deploy step copies the .env file to
    the server so the CLI can authenticate autonomously.
    """
    return ""


def _generate_config_env_code(metadata: CLIToolMetadata) -> str:
    """Generate TypeScript code that reads config node parameters and adds them to env.

    Config fields are no longer added as node properties — the CLI reads its own
    .env file on the server. This function returns empty string.
    """
    return ""


def _generate_resource_property(metadata: CLIToolMetadata) -> str:
    """Generate the resource dropdown property."""
    options = []
    for group in metadata.command_groups:
        options.append(
            f"\t\t\t\t\t{{\n"
            f"\t\t\t\t\t\tname: '{_escape_ts_string(group.display_name)}',\n"
            f"\t\t\t\t\t\tvalue: '{group.name}',\n"
            f"\t\t\t\t\t\tdescription: '{_escape_ts_string(group.help_text or '')}',\n"
            f"\t\t\t\t\t}},"
        )
    options_str = "\n".join(options)

    return (
        f"\t\t\t{{\n"
        f"\t\t\t\tdisplayName: 'Resource',\n"
        f"\t\t\t\tname: 'resource',\n"
        f"\t\t\t\ttype: 'options',\n"
        f"\t\t\t\tnoDataExpression: true,\n"
        f"\t\t\t\toptions: [\n"
        f"{options_str}\n"
        f"\t\t\t\t],\n"
        f"\t\t\t\tdefault: '{metadata.command_groups[0].name if metadata.command_groups else ''}',\n"
        f"\t\t\t}},"
    )


def _generate_operation_properties(metadata: CLIToolMetadata) -> str:
    """Generate operation dropdown properties for each resource."""
    properties = []
    for group in metadata.command_groups:
        options = []
        for cmd in group.commands:
            description = _escape_ts_string(cmd.help_text or cmd.display_name)
            options.append(
                f"\t\t\t\t\t{{\n"
                f"\t\t\t\t\t\tname: '{_escape_ts_string(cmd.display_name)}',\n"
                f"\t\t\t\t\t\tvalue: '{cmd.name}',\n"
                f"\t\t\t\t\t\tdescription: '{description}',\n"
                f"\t\t\t\t\t\taction: '{_escape_ts_string(cmd.display_name)} {_escape_ts_string(group.display_name.lower())}',\n"
                f"\t\t\t\t\t}},"
            )
        options_str = "\n".join(options)
        default_op = group.commands[0].name if group.commands else ""

        prop = (
            f"\t\t\t{{\n"
            f"\t\t\t\tdisplayName: 'Operation',\n"
            f"\t\t\t\tname: 'operation',\n"
            f"\t\t\t\ttype: 'options',\n"
            f"\t\t\t\tnoDataExpression: true,\n"
            f"\t\t\t\tdisplayOptions: {{\n"
            f"\t\t\t\t\tshow: {{\n"
            f"\t\t\t\t\t\tresource: ['{group.name}'],\n"
            f"\t\t\t\t\t}},\n"
            f"\t\t\t\t}},\n"
            f"\t\t\t\toptions: [\n"
            f"{options_str}\n"
            f"\t\t\t\t],\n"
            f"\t\t\t\tdefault: '{default_op}',\n"
            f"\t\t\t}},"
        )
        properties.append(prop)

    return "\n".join(properties)


def _n8n_type(param: CommandParameter) -> str:
    """Map parameter type to n8n property type."""
    if param.choices:
        return "options"
    return param.param_type


def _generate_field_property(
    param: CommandParameter,
    group_name: str,
    cmd_name: str,
    is_additional: bool = False,
) -> str:
    """Generate a single field property definition."""
    field_type = _n8n_type(param)
    display_name = _escape_ts_string(param.help_text or param.name.replace("_", " ").title())
    # Use short display name
    short_name = param.name.replace("_", " ").title()

    parts = [
        f"\t\t\t\t{{\n",
        f"\t\t\t\t\tdisplayName: '{_escape_ts_string(short_name)}',\n",
        f"\t\t\t\t\tname: '{param.name}',\n",
        f"\t\t\t\t\ttype: '{field_type}',\n",
    ]

    if param.help_text:
        parts.append(f"\t\t\t\t\tdescription: '{_escape_ts_string(param.help_text)}',\n")

    if not is_additional:
        parts.append(
            f"\t\t\t\t\tdisplayOptions: {{\n"
            f"\t\t\t\t\t\tshow: {{\n"
            f"\t\t\t\t\t\t\tresource: ['{group_name}'],\n"
            f"\t\t\t\t\t\t\toperation: ['{cmd_name}'],\n"
            f"\t\t\t\t\t\t}},\n"
            f"\t\t\t\t\t}},\n"
        )

    if param.required and not is_additional:
        parts.append(f"\t\t\t\t\trequired: true,\n")

    if field_type == "options" and param.choices:
        opts = []
        for choice in param.choices:
            opts.append(
                f"\t\t\t\t\t\t{{ name: '{_escape_ts_string(choice.title())}', value: '{choice}' }}"
            )
        parts.append(f"\t\t\t\t\toptions: [\n" + ",\n".join(opts) + "\n\t\t\t\t\t],\n")

    # Default value
    if param.param_type == "boolean":
        default = "true" if param.default is True else "false"
        parts.append(f"\t\t\t\t\tdefault: {default},\n")
    elif param.param_type == "number":
        parts.append(f"\t\t\t\t\tdefault: {param.default if param.default is not None else 0},\n")
    else:
        parts.append(f"\t\t\t\t\tdefault: '{param.default or ''}',\n")

    parts.append(f"\t\t\t\t}},")
    return "".join(parts)


def _generate_field_properties(metadata: CLIToolMetadata) -> str:
    """Generate field properties for all commands."""
    all_properties = []

    for group in metadata.command_groups:
        for cmd in group.commands:
            # Separate required args and optional params
            required_params = [p for p in cmd.parameters if p.required]
            optional_params = [p for p in cmd.parameters if not p.required]

            # Required parameters get their own top-level fields
            for param in required_params:
                prop = _generate_field_property(param, group.name, cmd.name)
                all_properties.append(prop)

            # Optional parameters go into an "Additional Fields" collection
            if optional_params:
                additional_fields = []
                for param in optional_params:
                    field = _generate_field_property(param, group.name, cmd.name, is_additional=True)
                    additional_fields.append(field)

                additional_str = "\n".join(additional_fields)

                collection = (
                    f"\t\t\t{{\n"
                    f"\t\t\t\tdisplayName: 'Additional Fields',\n"
                    f"\t\t\t\tname: 'additionalFields',\n"
                    f"\t\t\t\ttype: 'collection',\n"
                    f"\t\t\t\tplaceholder: 'Add Field',\n"
                    f"\t\t\t\tdefault: {{}},\n"
                    f"\t\t\t\tdisplayOptions: {{\n"
                    f"\t\t\t\t\tshow: {{\n"
                    f"\t\t\t\t\t\tresource: ['{group.name}'],\n"
                    f"\t\t\t\t\t\toperation: ['{cmd.name}'],\n"
                    f"\t\t\t\t\t}},\n"
                    f"\t\t\t\t}},\n"
                    f"\t\t\t\toptions: [\n"
                    f"{additional_str}\n"
                    f"\t\t\t\t],\n"
                    f"\t\t\t}},"
                )
                all_properties.append(collection)

    return "\n".join(all_properties)


def _generate_execute_body(metadata: CLIToolMetadata) -> str:
    """Generate the execute method body that builds CLI args per resource/operation."""
    lines = []

    for gi, group in enumerate(metadata.command_groups):
        condition = "if" if gi == 0 else "} else if"
        lines.append(f"\t\t\t\t{condition} (resource === '{group.name}') {{")

        for ci, cmd in enumerate(group.commands):
            op_condition = "if" if ci == 0 else "} else if"
            lines.append(f"\t\t\t\t\t{op_condition} (operation === '{cmd.name}') {{")

            required_params = [p for p in cmd.parameters if p.required]
            optional_params = [p for p in cmd.parameters if not p.required]

            # Required arguments (positional)
            for param in required_params:
                lines.append(
                    f"\t\t\t\t\t\tconst {param.name} = this.getNodeParameter('{param.name}', i) as {_ts_type(param)};"
                )
                if param.is_argument:
                    lines.append(f"\t\t\t\t\t\targs.push(String({param.name}));")
                else:
                    flag = param.cli_flag or f"--{param.name.replace('_', '-')}"
                    lines.append(f"\t\t\t\t\t\targs.push('{flag}', String({param.name}));")

            # Optional parameters from additionalFields
            if optional_params:
                lines.append(
                    f"\t\t\t\t\t\tconst additionalFields = this.getNodeParameter('additionalFields', i) as Record<string, any>;"
                )
                for param in optional_params:
                    flag = param.cli_flag or f"--{param.name.replace('_', '-')}"
                    if param.param_type == "boolean":
                        lines.append(
                            f"\t\t\t\t\t\tif (additionalFields.{param.name} === true) {{"
                        )
                        lines.append(f"\t\t\t\t\t\t\targs.push('{flag}');")
                        lines.append(f"\t\t\t\t\t\t}}")
                    else:
                        lines.append(
                            f"\t\t\t\t\t\tif (additionalFields.{param.name} !== undefined && additionalFields.{param.name} !== '') {{"
                        )
                        if param.is_argument:
                            lines.append(f"\t\t\t\t\t\t\targs.push(String(additionalFields.{param.name}));")
                        else:
                            lines.append(f"\t\t\t\t\t\t\targs.push('{flag}', String(additionalFields.{param.name}));")
                        lines.append(f"\t\t\t\t\t\t}}")

        if metadata.command_groups and metadata.command_groups[-1].commands:
            lines.append(f"\t\t\t\t\t}}")  # Close last operation if

    if metadata.command_groups:
        lines.append(f"\t\t\t\t}}")  # Close last resource if

    return "\n".join(lines)


def _ts_type(param: CommandParameter) -> str:
    """Get TypeScript type for a parameter."""
    if param.param_type == "number":
        return "number"
    elif param.param_type == "boolean":
        return "boolean"
    return "string"


_BUNDLE_IGNORE = shutil.ignore_patterns(
    ".venv",
    "__pycache__",
    "*.egg-info",
    ".git",
    ".gitignore",
    ".env",
    ".env.*",
    ".pytest_cache",
    "authentication_profiles",
    "node_modules",
    "README.md",
)


def _bundle_cli_source(cli_name: str, tools_dir: str, pkg_dir: Path):
    """Copy CLI tool Python source and cli-tools-shared into the node package.

    Bundles the CLI tool's source code into pkg_dir/cli/ and the shared
    cli-tools-shared library into pkg_dir/cli/cli-tools-shared/ so the n8n
    node has no external dependency on locally installed packages.
    The venv is created later during deploy.

    Args:
        cli_name: Name of the CLI tool (directory name under tools_dir)
        tools_dir: Path to the CLI tools directory
        pkg_dir: Path to the generated n8n node package directory
    """
    src = Path(tools_dir) / cli_name
    dst = pkg_dir / "cli"

    if not src.is_dir():
        raise GeneratorError(f"CLI tool source not found: {src}")

    if dst.exists():
        shutil.rmtree(dst)

    shutil.copytree(src, dst, ignore=_BUNDLE_IGNORE)

    # Bundle cli-tools-shared alongside the CLI source
    common_src = Path(tools_dir) / "_repo" / "cli-tools-shared"
    if common_src.is_dir():
        common_dst = dst / "cli-tools-shared"
        if common_dst.exists():
            shutil.rmtree(common_dst)
        shutil.copytree(common_src, common_dst, ignore=_BUNDLE_IGNORE)

        # Ensure cli-tools-shared is a dependency pointing to the bundled copy.
        pyproject_path = dst / "pyproject.toml"
        if pyproject_path.exists():
            content = pyproject_path.read_text()
            local_ref = 'cli-tools-shared @ file:./cli-tools-shared'

            patched = re.sub(
                r'"cli-tools-shared"',
                f'"{local_ref}"',
                content,
            )

            # Last resort: inject the dependency into the list if not present at all
            if patched == content and 'cli-tools-shared' not in content:
                patched = re.sub(
                    r'(dependencies\s*=\s*\[)',
                    f'\\1\n    "{local_ref}",',
                    content,
                )

            if patched != content:
                pyproject_path.write_text(patched)


def _generate_node_for_cred_type(
    metadata: CLIToolMetadata,
    cred_type: str,
    pascal_name: str,
    pkg_dir: Path,
    cred_file_infos: list,
    is_multi_node: bool,
) -> str:
    """Generate a node file for a specific credential type.

    Returns the node filename (e.g., 'BrickowlApi.node.ts').
    """
    # Filter command groups to only include commands for this credential type
    filtered_groups = _filter_command_groups_by_cred_type(metadata.command_groups, cred_type)

    # Build node-specific metadata with filtered groups
    node_metadata = CLIToolMetadata(
        name=metadata.name,
        display_name=metadata.display_name,
        description=metadata.description,
        version=metadata.version,
        cli_command=metadata.cli_command,
        command_groups=filtered_groups,
        credentials=metadata.credentials,
        config_fields=metadata.config_fields,
        credential_types=[cred_type],  # Only this credential type
    )

    # Node naming
    if is_multi_node:
        node_suffix = _NODE_SUFFIX.get(cred_type, _to_pascal_case(cred_type))
        node_pascal = f"{pascal_name}{node_suffix}"
        node_camel = node_pascal[0].lower() + node_pascal[1:]
        node_display = f"{metadata.display_name} {_NODE_DISPLAY_SUFFIX.get(cred_type, f'({cred_type})')}"
    else:
        node_pascal = pascal_name
        node_camel = _to_camel_case(metadata.name)
        node_display = metadata.display_name

    # Build credentials array for this node (only its credential type)
    creds_entry = ""
    for ct, _, _, camel, _, _ in cred_file_infos:
        if ct == cred_type:
            creds_entry = (
                f"\t\t\t{{\n"
                f"\t\t\t\tname: '{camel}',\n"
                f"\t\t\t\trequired: true,\n"
                f"\t\t\t}},"
            )
            break

    # Generate node components using filtered metadata
    resource_property = _generate_resource_property(node_metadata) if filtered_groups else ""
    operation_properties = _generate_operation_properties(node_metadata) if filtered_groups else ""
    field_properties = _generate_field_properties(node_metadata) if filtered_groups else ""
    execute_body = _generate_execute_body(node_metadata) if filtered_groups else ""
    credential_env_setup = _generate_credential_env_code(node_metadata, for_cred_type=cred_type)
    config_properties = _generate_config_properties(node_metadata)
    config_env_code = _generate_config_env_code(node_metadata)
    has_env = bool(node_metadata.credentials)
    exec_env_arg = ",\n\t\t\t\t\t\tenv" if has_env else ""

    node_ts = templates.NODE_TEMPLATE % {
        "pascal_name": node_pascal,
        "camel_name": node_camel,
        "name": metadata.name,
        "display_name": node_display,
        "description": _escape_ts_string(metadata.description),
        "cli_command": metadata.cli_command,
        "config_properties": config_properties,
        "resource_property": resource_property,
        "operation_properties": operation_properties,
        "field_properties": field_properties,
        "execute_body": execute_body,
        "credential_env_setup": credential_env_setup,
        "config_env_code": config_env_code,
        "exec_env_arg": exec_env_arg,
        "credentials_array": creds_entry,
    }

    node_filename = f"{node_pascal}.node.ts"
    (pkg_dir / "nodes" / pascal_name / node_filename).write_text(node_ts)

    # Generate node.json for this node
    node_json = templates.NODE_JSON_TEMPLATE % {
        "name": metadata.name,
        "camel_name": node_camel,
    }
    (pkg_dir / "nodes" / pascal_name / f"{node_pascal}.node.json").write_text(node_json)

    return node_filename


def generate_node_package(
    metadata: CLIToolMetadata, output_dir: str, force: bool = False, tools_dir: str = "",
    name_override: str | None = None, display_name_override: str | None = None,
) -> str:
    """Generate a complete n8n community node package.

    Args:
        metadata: Parsed CLI tool metadata
        output_dir: Base output directory
        force: Overwrite existing package
        tools_dir: Path to CLI tools directory (for bundling CLI source)
        name_override: Override the package/node name (keeps original CLI source name for bundling)
        display_name_override: Override the display name shown in the n8n UI

    Returns:
        Path to the generated package directory

    Raises:
        GeneratorError: If generation fails
    """
    # Store original CLI tool name for bundling, then apply name override
    cli_source_name = metadata.name
    if name_override:
        metadata = metadata.model_copy(update={"name": name_override})
    if display_name_override:
        metadata = metadata.model_copy(update={"display_name": display_name_override})

    pascal_name = _to_pascal_case(metadata.name)

    pkg_dir = Path(output_dir) / metadata.name

    if pkg_dir.exists() and not force:
        raise GeneratorError(
            f"Package already exists at {pkg_dir}. Use --force to overwrite."
        )

    # Create directory structure (clean on force to remove stale files)
    pkg_dir.mkdir(parents=True, exist_ok=True)
    creds_dir = pkg_dir / "credentials"
    nodes_dir = pkg_dir / "nodes" / pascal_name
    if force:
        if creds_dir.exists():
            shutil.rmtree(creds_dir)
        if nodes_dir.exists():
            shutil.rmtree(nodes_dir)
    creds_dir.mkdir(exist_ok=True)
    nodes_dir.mkdir(parents=True, exist_ok=True)

    # Determine credential types to generate
    cred_types = metadata.credential_types or []
    is_multi_node = len(cred_types) > 1

    # Build per-type credential info for package.json and node template
    cred_file_infos = []  # list of (cred_type, file_name, class_name, camel_name, display_name, type_creds)
    for ct in cred_types:
        type_creds = [c for c in metadata.credentials if c.credential_type == ct]
        if not type_creds:
            continue
        class_name = _cred_type_name(pascal_name, ct)
        camel = _cred_camel_name(pascal_name, ct)
        display = f"{metadata.display_name} {_CRED_TYPE_DISPLAY.get(ct, ct.replace('_', ' ').title())}"
        file_name = f"{class_name}.credentials.ts"
        cred_file_infos.append((ct, file_name, class_name, camel, display, type_creds))

    # Generate credential files (one per credential type)
    for ct, file_name, class_name, camel, display, type_creds in cred_file_infos:
        credential_fields = _generate_credential_fields_for_type(type_creds)
        credentials_ts = templates.CREDENTIAL_TEMPLATE % {
            "class_name": class_name,
            "type_name": camel,
            "display_name": display,
            "credential_fields": credential_fields,
        }
        (pkg_dir / "credentials" / file_name).write_text(credentials_ts)

    # Build credential paths for package.json
    if cred_file_infos:
        cred_paths = ",\n".join(
            f'      "dist/credentials/{info[1].replace(".ts", ".js")}"'
            for info in cred_file_infos
        )
    else:
        cred_paths = ""

    # Generate node files - one per credential type if multi-node, else single node
    node_filenames = []
    if is_multi_node:
        for ct in cred_types:
            # Skip if no credentials for this type
            if not any(info[0] == ct for info in cred_file_infos):
                continue
            node_filename = _generate_node_for_cred_type(
                metadata, ct, pascal_name, pkg_dir, cred_file_infos, is_multi_node=True
            )
            node_filenames.append(node_filename)
    else:
        # Single credential type - use current behavior (no suffix)
        if cred_types:
            node_filename = _generate_node_for_cred_type(
                metadata, cred_types[0], pascal_name, pkg_dir, cred_file_infos, is_multi_node=False
            )
            node_filenames.append(node_filename)
        else:
            # No credentials - generate single node with all commands
            node_filename = _generate_node_for_cred_type(
                metadata, "", pascal_name, pkg_dir, cred_file_infos, is_multi_node=False
            )
            node_filenames.append(node_filename)

    # Build node paths for package.json
    node_paths = ",\n".join(
        f'      "dist/nodes/{pascal_name}/{fn.replace(".ts", ".js")}"'
        for fn in node_filenames
    )

    # Generate package.json with dynamic credential and node paths
    package_json = templates.PACKAGE_JSON % {
        "name": metadata.name,
        "version": metadata.version,
        "display_name": metadata.display_name,
        "pascal_name": pascal_name,
        "credential_paths": cred_paths,
        "node_paths": node_paths,
        "cli_command": metadata.cli_command,
    }
    (pkg_dir / "package.json").write_text(package_json)

    # Generate tsconfig.json
    (pkg_dir / "tsconfig.json").write_text(templates.TSCONFIG)

    # Generate README
    resources_list = "\n".join(
        f"- **{g.display_name}**: {g.help_text or ''}" for g in metadata.command_groups
    )
    operations_list = ""
    for g in metadata.command_groups:
        operations_list += f"\n### {g.display_name}\n\n"
        for c in g.commands:
            operations_list += f"- **{c.display_name}**: {c.help_text or ''}\n"

    readme = templates.README_TEMPLATE % {
        "name": metadata.name,
        "display_name": metadata.display_name,
        "cli_command": metadata.cli_command,
        "resources_list": resources_list,
        "operations_list": operations_list,
    }
    (pkg_dir / "README.md").write_text(readme)

    # Bundle CLI tool source into the package
    if tools_dir:
        _bundle_cli_source(cli_source_name, tools_dir, pkg_dir)

    return str(pkg_dir)
