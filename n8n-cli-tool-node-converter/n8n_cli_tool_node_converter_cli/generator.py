"""n8n TypeScript node package generator.

Takes parsed CLIToolMetadata and generates a complete n8n community node package.
"""
import json
import re
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


def _to_pascal_case(name: str) -> str:
    """Convert kebab-case or snake_case to PascalCase."""
    return "".join(word.title() for word in re.split(r"[-_]", name))


def _to_camel_case(name: str) -> str:
    """Convert kebab-case or snake_case to camelCase."""
    pascal = _to_pascal_case(name)
    return pascal[0].lower() + pascal[1:] if pascal else ""


def _escape_ts_string(s: str) -> str:
    """Escape a string for use in TypeScript single-quoted strings."""
    return s.replace("\\", "\\\\").replace("'", "\\'").replace("\n", " ")


def _generate_credential_fields(metadata: CLIToolMetadata) -> str:
    """Generate credential field entries for the credentials TypeScript file."""
    fields = []
    for cred in metadata.credentials:
        # Determine field name (camelCase from env var)
        parts = cred.env_var.split("_")
        # Skip the prefix (tool name portion)
        field_parts = []
        found_separator = False
        for part in parts:
            if found_separator:
                field_parts.append(part.lower())
            elif part.upper() in ("API", "BASE", "CLIENT", "ACCESS", "REFRESH", "TOKEN"):
                found_separator = True
                field_parts.append(part.lower())
        if not field_parts:
            field_parts = [p.lower() for p in parts[-2:]]

        field_name = field_parts[0] + "".join(w.title() for w in field_parts[1:])

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


def generate_node_package(metadata: CLIToolMetadata, output_dir: str, force: bool = False) -> str:
    """Generate a complete n8n community node package.

    Args:
        metadata: Parsed CLI tool metadata
        output_dir: Base output directory
        force: Overwrite existing package

    Returns:
        Path to the generated package directory

    Raises:
        GeneratorError: If generation fails
    """
    pascal_name = _to_pascal_case(metadata.name)
    camel_name = _to_camel_case(metadata.name)

    pkg_dir = Path(output_dir) / f"n8n-nodes-{metadata.name}"

    if pkg_dir.exists() and not force:
        raise GeneratorError(
            f"Package already exists at {pkg_dir}. Use --force to overwrite."
        )

    # Create directory structure
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / "credentials").mkdir(exist_ok=True)
    (pkg_dir / "nodes" / pascal_name).mkdir(parents=True, exist_ok=True)

    # Generate package.json
    package_json = templates.PACKAGE_JSON % {
        "name": metadata.name,
        "version": metadata.version,
        "display_name": metadata.display_name,
        "pascal_name": pascal_name,
    }
    (pkg_dir / "package.json").write_text(package_json)

    # Generate tsconfig.json
    (pkg_dir / "tsconfig.json").write_text(templates.TSCONFIG)

    # Generate credentials file
    credential_fields = _generate_credential_fields(metadata)
    credentials_ts = templates.CREDENTIAL_TEMPLATE % {
        "pascal_name": pascal_name,
        "camel_name": camel_name,
        "display_name": metadata.display_name,
        "credential_fields": credential_fields,
    }
    (pkg_dir / "credentials" / f"{pascal_name}Api.credentials.ts").write_text(credentials_ts)

    # Generate node file
    resource_property = _generate_resource_property(metadata) if metadata.command_groups else ""
    operation_properties = _generate_operation_properties(metadata) if metadata.command_groups else ""
    field_properties = _generate_field_properties(metadata) if metadata.command_groups else ""
    execute_body = _generate_execute_body(metadata) if metadata.command_groups else ""

    node_ts = templates.NODE_TEMPLATE % {
        "pascal_name": pascal_name,
        "camel_name": camel_name,
        "name": metadata.name,
        "display_name": metadata.display_name,
        "description": _escape_ts_string(metadata.description),
        "cli_command": metadata.cli_command,
        "resource_property": resource_property,
        "operation_properties": operation_properties,
        "field_properties": field_properties,
        "execute_body": execute_body,
    }
    (pkg_dir / "nodes" / pascal_name / f"{pascal_name}.node.ts").write_text(node_ts)

    # Generate node.json
    node_json = templates.NODE_JSON_TEMPLATE % {
        "name": metadata.name,
        "camel_name": camel_name,
    }
    (pkg_dir / "nodes" / pascal_name / f"{pascal_name}.node.json").write_text(node_json)

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

    return str(pkg_dir)
