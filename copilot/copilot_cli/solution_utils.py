"""Utility functions for working with Power Platform solution zip files."""
import io
import zipfile
import xml.etree.ElementTree as ET
from typing import Optional


def parse_solution_zip(solution_bytes: bytes) -> dict:
    """
    Extract metadata from solution.xml inside a solution zip.

    Args:
        solution_bytes: Solution zip file as bytes

    Returns:
        Dict containing solution metadata:
        - UniqueName: Solution unique name
        - LocalizedNames: Display names by locale
        - Version: Solution version
        - Publisher: Publisher info
    """
    with zipfile.ZipFile(io.BytesIO(solution_bytes), 'r') as zf:
        # Read solution.xml
        if 'solution.xml' not in zf.namelist():
            raise ValueError("Invalid solution zip: missing solution.xml")

        with zf.open('solution.xml') as f:
            tree = ET.parse(f)
            root = tree.getroot()

        solution = {}

        # Get solution unique name
        unique_name = root.find('.//UniqueName')
        if unique_name is not None:
            solution['UniqueName'] = unique_name.text

        # Get version
        version = root.find('.//Version')
        if version is not None:
            solution['Version'] = version.text

        # Get localized names
        localized_names = {}
        for name in root.findall('.//LocalizedNames/LocalizedName'):
            desc = name.get('description')
            lang = name.get('languagecode')
            if desc and lang:
                localized_names[lang] = desc
        solution['LocalizedNames'] = localized_names

        # Get publisher info
        publisher = root.find('.//Publisher')
        if publisher is not None:
            pub_info = {}
            unique_name_elem = publisher.find('UniqueName')
            if unique_name_elem is not None:
                pub_info['UniqueName'] = unique_name_elem.text

            prefix = publisher.find('CustomizationPrefix')
            if prefix is not None:
                pub_info['CustomizationPrefix'] = prefix.text

            solution['Publisher'] = pub_info

        return solution


def extract_connection_references(solution_bytes: bytes) -> list[dict]:
    """
    Extract connection references from a solution zip.

    Args:
        solution_bytes: Solution zip file as bytes

    Returns:
        List of connection reference dicts with:
        - LogicalName: Schema name of the connection reference
        - DisplayName: Display name
        - ConnectorId: The connector identifier
        - ConnectionId: Current connection ID (if any)
    """
    connection_refs = []

    with zipfile.ZipFile(io.BytesIO(solution_bytes), 'r') as zf:
        # Connection references are in connectionreferences/*.xml
        for name in zf.namelist():
            if name.startswith('connectionreferences/') and name.endswith('.xml'):
                with zf.open(name) as f:
                    try:
                        tree = ET.parse(f)
                        root = tree.getroot()

                        # Extract connection reference info
                        conn_ref = {}

                        logical_name = root.find('.//connectionreferencelogicalname')
                        if logical_name is not None:
                            conn_ref['LogicalName'] = logical_name.text

                        display_name = root.find('.//connectionreferencedisplayname')
                        if display_name is not None:
                            conn_ref['DisplayName'] = display_name.text

                        connector_id = root.find('.//connectorid')
                        if connector_id is not None:
                            conn_ref['ConnectorId'] = connector_id.text

                        connection_id = root.find('.//connectionid')
                        if connection_id is not None:
                            conn_ref['ConnectionId'] = connection_id.text
                        else:
                            conn_ref['ConnectionId'] = ""

                        if conn_ref.get('LogicalName'):
                            connection_refs.append(conn_ref)
                    except ET.ParseError:
                        # Skip files that aren't valid XML
                        continue

    return connection_refs


def extract_environment_variables(solution_bytes: bytes) -> list[dict]:
    """
    Extract environment variable definitions from a solution zip.

    Args:
        solution_bytes: Solution zip file as bytes

    Returns:
        List of environment variable dicts with:
        - SchemaName: Schema name of the variable
        - DisplayName: Display name
        - Type: Variable type (String, Number, Boolean, etc.)
        - DefaultValue: Default value if any
        - Value: Current value (if set)
    """
    env_vars = []

    with zipfile.ZipFile(io.BytesIO(solution_bytes), 'r') as zf:
        # Environment variables are in environmentvariabledefinitions/*.xml
        for name in zf.namelist():
            if name.startswith('environmentvariabledefinitions/') and name.endswith('.xml'):
                with zf.open(name) as f:
                    try:
                        tree = ET.parse(f)
                        root = tree.getroot()

                        env_var = {}

                        schema_name = root.find('.//schemaname')
                        if schema_name is not None:
                            env_var['SchemaName'] = schema_name.text

                        display_name = root.find('.//displayname')
                        if display_name is not None:
                            env_var['DisplayName'] = display_name.text

                        var_type = root.find('.//type')
                        if var_type is not None:
                            env_var['Type'] = var_type.text

                        default_value = root.find('.//defaultvalue')
                        if default_value is not None:
                            env_var['DefaultValue'] = default_value.text

                        # Current value might be in a separate environmentvariablevalues file
                        env_var['Value'] = ""

                        if env_var.get('SchemaName'):
                            env_vars.append(env_var)
                    except ET.ParseError:
                        continue

        # Also check for environment variable values
        for name in zf.namelist():
            if name.startswith('environmentvariablevalues/') and name.endswith('.xml'):
                with zf.open(name) as f:
                    try:
                        tree = ET.parse(f)
                        root = tree.getroot()

                        schema_name = root.find('.//schemaname')
                        value = root.find('.//value')

                        if schema_name is not None and value is not None:
                            # Find matching definition and update value
                            for ev in env_vars:
                                if ev.get('SchemaName') == schema_name.text:
                                    ev['Value'] = value.text or ""
                                    break
                    except ET.ParseError:
                        continue

    return env_vars


def generate_settings_template(solution_bytes: bytes) -> dict:
    """
    Generate a deployment settings JSON template from a solution zip.

    This creates a template with all connection references and environment
    variables that need to be configured for the target environment.

    Args:
        solution_bytes: Solution zip file as bytes

    Returns:
        Dict with ConnectionReferences and EnvironmentVariables arrays
        ready for editing and use with solution import
    """
    conn_refs = extract_connection_references(solution_bytes)
    env_vars = extract_environment_variables(solution_bytes)

    # Format connection references for settings template
    connection_references = []
    for ref in conn_refs:
        connection_references.append({
            "LogicalName": ref.get('LogicalName', ''),
            "DisplayName": ref.get('DisplayName', ''),
            "ConnectorId": ref.get('ConnectorId', ''),
            "ConnectionId": ref.get('ConnectionId', ''),
            "_comment": "Set ConnectionId to the GUID of the connection in the target environment"
        })

    # Format environment variables for settings template
    environment_variables = []
    for var in env_vars:
        env_entry = {
            "SchemaName": var.get('SchemaName', ''),
            "DisplayName": var.get('DisplayName', ''),
            "Type": var.get('Type', ''),
            "Value": var.get('Value') or var.get('DefaultValue', ''),
        }
        if var.get('DefaultValue'):
            env_entry["_defaultValue"] = var.get('DefaultValue')
        env_entry["_comment"] = "Set Value for the target environment"
        environment_variables.append(env_entry)

    return {
        "ConnectionReferences": connection_references,
        "EnvironmentVariables": environment_variables,
    }
