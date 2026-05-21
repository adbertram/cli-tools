"""Application commands for Podio CLI."""

COMMAND_CREDENTIALS = {
    "activate": [
        "oauth_authorization_code"
    ],
    "create": [
        "oauth_authorization_code"
    ],
    "deactivate": [
        "oauth_authorization_code"
    ],
    "export": [
        "oauth_authorization_code"
    ],
    "field": [
        "oauth_authorization_code"
    ],
    "get": [
        "oauth_authorization_code"
    ],
    "items": [
        "oauth_authorization_code"
    ],
    "list": [
        "oauth_authorization_code"
    ],
    "update": [
        "oauth_authorization_code"
    ]
}
import typer
import time
import sys
from pathlib import Path
from typing import Optional, Any, List

from cli_tools_shared.filters import apply_filters, validate_filters, FilterValidationError
from ..client import get_client
from ..config import get_config
from ..output import print_json, print_output, print_error, handle_api_error, format_response
from ..filter_map import FilterMap, apply_properties

app = typer.Typer(help="Manage Podio applications")

# Subcommand group for field operations
field_app = typer.Typer(help="Manage application fields")
app.add_typer(field_app, name="field")


def _flatten_app(app_data: dict) -> dict:
    """Flatten app data by promoting config fields to top level."""
    if not isinstance(app_data, dict):
        return app_data

    result = {}
    for key, value in app_data.items():
        if key == "config" and isinstance(value, dict):
            # Promote config fields to top level (config fields take precedence)
            for config_key, config_value in value.items():
                result[config_key] = config_value
        else:
            result[key] = value

    return result


def _flatten_apps(data: Any) -> Any:
    """Flatten app list data by promoting config fields to top level."""
    if isinstance(data, list):
        return [_flatten_app(item) for item in data]
    elif isinstance(data, dict):
        return _flatten_app(data)
    return data


@app.command("get")
def get_app(
    app_id: int = typer.Argument(..., help="Application ID to retrieve"),
    fields: bool = typer.Option(False, "--fields", "-f", help="Return only the field schema"),
    include_deleted: bool = typer.Option(False, "--include-deleted", help="Include deleted fields in the response"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Get a Podio application by ID.

    By default, deleted fields are excluded from the response.
    Use --include-deleted to show all fields including deleted ones.
    Use --fields to return only the field schema.

    Examples:
        podio app get 12345
        podio app get 12345 --fields
        podio app get 12345 --fields --table
        podio app get 12345 --include-deleted
        podio app get 12345 --table
    """
    try:
        client = get_client()
        result = client.Application.find(app_id=app_id)

        # Filter out deleted fields by default
        if not include_deleted and 'fields' in result:
            result['fields'] = [f for f in result['fields'] if f.get('status') != 'deleted']

        # Return only fields if requested
        if fields:
            result = result.get('fields', [])

        formatted = format_response(result)
        print_output(formatted, table=table)
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@app.command("list")
def list_apps(
    space_id: Optional[int] = typer.Option(None, "--space-id", "-s", help="Space ID to list apps from (defaults to PODIO_WORKSPACE_ID)"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum apps to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of fields to include"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    List all applications in a space.

    If space_id is not provided, uses PODIO_WORKSPACE_ID from environment.

    Filter examples:
        --filter "status:active"
        --filter "name:contains:Sales"

    Examples:
        podio app list --space-id 87654321
        podio app list  # Uses PODIO_WORKSPACE_ID
        podio app list --limit 10
        podio app list --filter "status:active"
        podio app list --properties "app_id,name,link"
        podio app list --table
    """
    try:
        # Use workspace_id from config if space_id not provided
        if space_id is None:
            config = get_config()
            if config.workspace_id:
                space_id = int(config.workspace_id)
            else:
                print_error("No space_id provided and PODIO_WORKSPACE_ID not set in environment")
                raise typer.Exit(1)

        client = get_client()
        result = client.Application.list_in_space(space_id=space_id)
        formatted = _flatten_apps(format_response(result))

        # Apply client-side filter if specified
        if filter:
            formatted = apply_filters(formatted, filter)

        # Apply limit (client-side)
        if isinstance(formatted, list) and len(formatted) > limit:
            formatted = formatted[:limit]

        # Apply properties filter
        if properties:
            formatted = apply_properties(formatted, properties)

        print_output(formatted, table=table)
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@app.command("items")
def get_app_items(
    app_id: int = typer.Argument(..., help="Application ID to get items from"),
    limit: int = typer.Option(30, "--limit", help="Maximum number of items to return"),
    offset: int = typer.Option(0, "--offset", help="Offset for pagination"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Get all items from an application.

    Examples:
        podio app items 12345
        podio app items 12345 --limit 100
        podio app items 12345 --table
    """
    try:
        client = get_client()
        result = client.Application.get_items(app_id=app_id, limit=limit, offset=offset)
        formatted = format_response(result)
        print_output(formatted, table=table)
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@app.command("activate")
def activate_app(
    app_id: int = typer.Argument(..., help="Application ID to activate"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Activate a Podio application.

    Examples:
        podio app activate 12345
        podio app activate 12345 --table
    """
    try:
        client = get_client()
        result = client.Application.activate(app_id=app_id)
        formatted = format_response(result)
        print_output(formatted, table=table)
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@app.command("deactivate")
def deactivate_app(
    app_id: int = typer.Argument(..., help="Application ID to deactivate"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Deactivate a Podio application.

    Examples:
        podio app deactivate 12345
        podio app deactivate 12345 --table
    """
    try:
        client = get_client()
        result = client.Application.deactivate(app_id=app_id)
        formatted = format_response(result)
        print_output(formatted, table=table)
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@app.command("create")
def create_app(
    json_file: Optional[Path] = typer.Option(None, "--json-file", "-f", help="JSON file with app configuration"),
    space_id: Optional[int] = typer.Option(None, "--space-id", "-s", help="Space ID to create app in (defaults to PODIO_WORKSPACE_ID)"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Create a new Podio application.

    The app configuration must include space_id, config, and fields.
    You can either provide a JSON file with --json-file or pipe JSON via stdin.

    Examples:
        podio app create --json-file app.json
        podio app create --space-id 10479826 --json-file app.json
        cat app.json | podio app create
        podio app create --json-file app.json --table
    """
    try:
        import json

        # Read JSON from file or stdin
        if json_file:
            with open(json_file, 'r') as f:
                app_data = json.load(f)
        else:
            # Read from stdin
            app_data = json.load(sys.stdin)

        # Override space_id if provided as option
        if space_id is not None:
            app_data['space_id'] = space_id
        elif 'space_id' not in app_data:
            # Try to use workspace_id from config
            config = get_config()
            if config.workspace_id:
                app_data['space_id'] = int(config.workspace_id)
            else:
                raise ValueError(
                    "No space_id provided in JSON and PODIO_WORKSPACE_ID not set in environment"
                )

        client = get_client()
        result = client.Application.create(attributes=app_data)
        formatted = format_response(result)

        print(f"✓ App created successfully", file=sys.stderr)
        print_output(formatted, table=table)

    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@app.command("update")
def update_app(
    app_id: int = typer.Argument(..., help="Application ID to update"),
    json_file: Optional[Path] = typer.Option(None, "--json-file", "-f", help="JSON file with app configuration to update"),
    name: Optional[str] = typer.Option(None, "--name", "-n", help="App name"),
    item_name: Optional[str] = typer.Option(None, "--item-name", help="Item name (singular, e.g., 'Topic')"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="App description (supports markdown, shows in sidebar)"),
    icon_id: Optional[int] = typer.Option(None, "--icon-id", help="Icon ID (1-650)"),
    allow_edit: Optional[bool] = typer.Option(None, "--allow-edit/--no-allow-edit", help="Allow editing items"),
    allow_attachments: Optional[bool] = typer.Option(None, "--allow-attachments/--no-allow-attachments", help="Allow file attachments"),
    allow_comments: Optional[bool] = typer.Option(None, "--allow-comments/--no-allow-comments", help="Allow comments on items"),
    disable_notifications: Optional[bool] = typer.Option(None, "--disable-notifications/--enable-notifications", help="Disable notifications for this app"),
    silent_creates: Optional[bool] = typer.Option(None, "--silent-creates/--no-silent-creates", help="Silent mode for item creation"),
    silent_edits: Optional[bool] = typer.Option(None, "--silent-edits/--no-silent-edits", help="Silent mode for item edits"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Update a Podio application's configuration.

    You can update the app configuration using a JSON file or by specifying
    individual options. When using options, only the specified values are updated.

    Config properties that can be updated:
      - name: App name
      - item_name: Item name (singular)
      - description: App description (supports markdown)
      - icon_id: Icon ID (1-650)
      - allow_edit, allow_attachments, allow_comments
      - disable_notifications, silent_creates, silent_edits
      - And more (use --json-file for full control)

    Examples:
        podio app update 12345 --description "New description"
        podio app update 12345 --name "My App" --item-name "Task"
        podio app update 12345 --icon-id 42
        podio app update 12345 --json-file config.json
        podio app update 12345 --silent-edits
        podio app update 12345 --no-allow-comments
        podio app update 12345 --table
    """
    try:
        import json as json_module

        # Build config from options or JSON file
        if json_file:
            with open(json_file, 'r') as f:
                config = json_module.load(f)
        else:
            config = {}

        # Override with individual options if provided
        if name is not None:
            config['name'] = name
        if item_name is not None:
            config['item_name'] = item_name
        if description is not None:
            config['description'] = description
        if icon_id is not None:
            config['icon_id'] = icon_id
        if allow_edit is not None:
            config['allow_edit'] = allow_edit
        if allow_attachments is not None:
            config['allow_attachments'] = allow_attachments
        if allow_comments is not None:
            config['allow_comments'] = allow_comments
        if disable_notifications is not None:
            config['disable_notifications'] = disable_notifications
        if silent_creates is not None:
            config['silent_creates'] = silent_creates
        if silent_edits is not None:
            config['silent_edits'] = silent_edits

        if not config:
            print_error("No configuration provided. Use --json-file or individual options like --name, --description")
            raise typer.Exit(1)

        client = get_client()

        # Fetch current app config to preserve required fields
        current_app = client.Application.find(app_id=app_id)
        current_config = current_app.get('config', {})

        # Merge updates into current config (updates take precedence)
        merged_config = {**current_config, **config}

        # Build the API request structure
        # The API expects: {"config": {...}}
        attributes = {'config': merged_config}

        result = client.Application.update(app_id=app_id, attributes=attributes)
        formatted = format_response(result)

        print(f"✓ App {app_id} updated successfully", file=sys.stderr)
        print_output(formatted, table=table)

    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@app.command("export")
def export_app(
    app_id: int = typer.Argument(..., help="Application ID to export"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file path (defaults to app_name.xlsx)"),
    format: str = typer.Option("xlsx", "--format", "-f", help="Export format (xlsx or xls)"),
    limit: Optional[int] = typer.Option(None, "--limit", help="Maximum number of items to export"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Export a Podio application to Excel.

    This command exports all items from an app to an Excel file.
    The export is processed asynchronously by Podio, so this command
    will poll for completion and download the file when ready.

    Examples:
        podio app export 12345
        podio app export 12345 --output my_export.xlsx
        podio app export 12345 --format xls --limit 1000
        podio app export 12345 --table
    """
    try:
        client = get_client()

        # Get app info for default filename
        if output is None:
            app_info = client.Application.find(app_id=app_id)
            app_name = app_info.get('config', {}).get('name', f'app_{app_id}')
            # Sanitize filename
            app_name = "".join(c for c in app_name if c.isalnum() or c in (' ', '-', '_')).strip()
            app_name = app_name.replace(' ', '_')
            output = f"{app_name}.{format}"

        # Prepare export attributes
        export_attrs = {}
        if limit:
            export_attrs['limit'] = limit

        # Print status to stderr so stdout can be used for JSON output
        print(f"Starting export for app {app_id}...", file=sys.stderr)

        # Start the export
        export_result = client.Item.export(app_id=app_id, exporter=format, attributes=export_attrs)
        batch_id = export_result.get('batch_id')

        if not batch_id:
            print("Error: No batch_id returned from export", file=sys.stderr)
            raise typer.Exit(1)

        print(f"Export batch created: {batch_id}", file=sys.stderr)
        print("Waiting for export to complete...", file=sys.stderr)

        # Poll for batch completion
        max_attempts = 60  # 5 minutes max (60 * 5 seconds)
        attempt = 0

        while attempt < max_attempts:
            batch_status = client.Batch.get(batch_id=batch_id)
            status = batch_status.get('status')

            if status == 'completed':
                file_id = batch_status.get('file_id')
                if not file_id:
                    print("Error: Export completed but no file_id returned", file=sys.stderr)
                    raise typer.Exit(1)

                print(f"Export completed. Downloading file {file_id}...", file=sys.stderr)

                # Download the file
                file_data = client.Files.find_raw(file_id=file_id)

                # Write to file
                output_path = Path(output)
                with open(output_path, 'wb') as f:
                    f.write(file_data)

                print(f"Export saved to: {output_path.absolute()}", file=sys.stderr)

                # Output JSON result to stdout
                result = {
                    'app_id': app_id,
                    'batch_id': batch_id,
                    'file_id': file_id,
                    'output_file': str(output_path.absolute()),
                    'format': format
                }
                print_output(result, table=table)
                return

            elif status == 'failed':
                print(f"Export failed: {batch_status}", file=sys.stderr)
                raise typer.Exit(1)

            # Still processing
            attempt += 1
            time.sleep(5)

        # Timeout
        print(f"Export timed out after {max_attempts * 5} seconds", file=sys.stderr)
        raise typer.Exit(1)

    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


# Field subcommands
@field_app.command("add")
def add_field(
    app_id: int = typer.Argument(..., help="Application ID to add field to"),
    field_type: Optional[str] = typer.Option(None, "--type", help="Field type (text, number, image, date, app, money, progress, location, duration, contact, calculation, embed, question, file, tel)"),
    label: Optional[str] = typer.Option(None, "--label", "-l", help="Field label"),
    required: bool = typer.Option(False, "--required", "-r", help="Whether field is required"),
    json_file: Optional[Path] = typer.Option(None, "--json-file", "-f", help="JSON file with full field configuration (overrides other options)"),
    mimetypes: Optional[str] = typer.Option(None, "--mimetypes", "-m", help="Allowed mimetypes for file fields (comma-separated, e.g., 'application/*,image/*')"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Add a new field to an application.

    Supported field types: text, number, image, date, app, money, progress,
    location, duration, contact, calculation, embed, question, file, tel

    You can either provide --type and --label options, or use --json-file for
    full field configuration. When using --json-file, --type and --label are
    not required.

    Examples:
        podio app field add 12345 --type text --label "Title"
        podio app field add 12345 --type file --label "Attachments" --mimetypes "application/*,image/*"
        podio app field add 12345 --json-file field.json
        podio app field add 12345 --type text --label "Title" --table
    """
    try:
        import json as json_module

        if json_file:
            with open(json_file, 'r') as f:
                field_data = json_module.load(f)
            # Extract label from JSON for success message
            field_label = field_data.get('config', {}).get('label', 'field')
        else:
            # Validate that --type and --label are provided when not using --json-file
            if not field_type:
                print_error("--type is required when not using --json-file")
                raise typer.Exit(2)
            if not label:
                print_error("--label is required when not using --json-file")
                raise typer.Exit(2)

            field_label = label
            field_data = {
                'type': field_type,
                'config': {
                    'label': label,
                    'required': required,
                }
            }

            # Add type-specific settings
            if field_type == 'file' and mimetypes:
                field_data['config']['settings'] = {
                    'allowed_mimetypes': [m.strip() for m in mimetypes.split(',')]
                }
            elif field_type == 'text':
                field_data['config']['settings'] = {
                    'size': 'small',
                    'format': 'plain'
                }

        client = get_client()
        result = client.Application.add_field(app_id=app_id, attributes=field_data)
        formatted = format_response(result)

        print(f"✓ Field '{field_label}' added successfully", file=sys.stderr)
        print_output(formatted, table=table)

    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@field_app.command("get")
def get_field(
    app_id: int = typer.Argument(..., help="Application ID"),
    field_id: int = typer.Argument(..., help="Field ID to retrieve"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Get a field from an application.

    Examples:
        podio app field get 12345 67890
        podio app field get 12345 67890 --table
    """
    try:
        client = get_client()
        result = client.Application.get_field(app_id=app_id, field_id=field_id)
        formatted = format_response(result)
        print_output(formatted, table=table)
    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


def _deep_merge(base: dict, updates: dict) -> dict:
    """
    Deep merge updates into base dict. Only keys present in updates are modified.
    For nested dicts, recursively merge. For other values, updates take precedence.
    """
    result = base.copy()
    for key, value in updates.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


@field_app.command("update")
def update_field(
    app_id: int = typer.Argument(..., help="Application ID"),
    field_id: int = typer.Argument(..., help="Field ID to update"),
    json_file: Path = typer.Option(..., "--json-file", "-f", help="JSON file with field configuration"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Update a field in an application.

    Only attributes explicitly provided in the JSON file are modified.
    All other field properties (delta, required, hidden, settings, etc.)
    are automatically preserved from the current field configuration.

    Examples:
        podio app field update 12345 67890 --json-file field.json
        podio app field update 12345 67890 --json-file field.json --table
    """
    try:
        import json as json_module

        with open(json_file, 'r') as f:
            field_data = json_module.load(f)

        client = get_client()

        # Fetch current field configuration
        current_field = client.Application.get_field(app_id=app_id, field_id=field_id)
        current_config = current_field.get('config', {})

        # Build base from current config (flattened to API update format)
        # The API expects: label, description, delta, required, hidden, hidden_create_view_edit, settings, mapping, unique
        base_data = {
            'label': current_field.get('label'),
        }

        # Copy all config properties that the API accepts for updates
        config_keys = ['description', 'delta', 'required', 'hidden', 'hidden_create_view_edit',
                       'settings', 'mapping', 'unique', 'default_value']
        for key in config_keys:
            if key in current_config:
                base_data[key] = current_config[key]

        # Deep merge the update data onto the base
        merged_data = _deep_merge(base_data, field_data)

        result = client.Application.update_field(app_id=app_id, field_id=field_id, attributes=merged_data)
        formatted = format_response(result)

        print(f"✓ Field updated successfully", file=sys.stderr)
        print_output(formatted, table=table)

    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


def _clear_field_values_from_items(client, app_id: int, field_id: int, external_id: str) -> int:
    """
    Clear field values from all items in an app.

    The Podio API's delete_values parameter does not actually remove data from
    existing items, so we need to manually clear values before deleting the field.

    Returns the number of items updated.
    """
    updated_count = 0
    offset = 0
    limit = 100  # Process in batches

    while True:
        # Get items that might have this field
        items_result = client.Item.filter(
            app_id=app_id,
            attributes={'limit': limit, 'offset': offset}
        )

        items = items_result.get('items', [])
        if not items:
            break

        for item in items:
            item_id = item.get('item_id')
            fields = item.get('fields', [])

            # Check if this item has a value for the target field
            has_field_value = any(
                f.get('field_id') == field_id or f.get('external_id') == external_id
                for f in fields
            )

            if has_field_value:
                # Clear the field value by setting it to an empty array
                try:
                    client.Item.update(
                        item_id=item_id,
                        attributes={'fields': {external_id: []}},
                        silent=True,  # Don't spam notifications
                        hook=False    # Don't trigger webhooks for cleanup
                    )
                    updated_count += 1
                    print(f"  Cleared field value from item {item_id}", file=sys.stderr)
                except Exception as e:
                    print(f"  Warning: Failed to clear field from item {item_id}: {e}", file=sys.stderr)

        # Check if we've processed all items
        total = items_result.get('total', 0)
        offset += limit
        if offset >= total:
            break

    return updated_count


@field_app.command("delete")
def delete_field(
    app_id: int = typer.Argument(..., help="Application ID"),
    field_id: int = typer.Argument(..., help="Field ID to delete"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
    delete_values: bool = typer.Option(False, "--delete-values", "-d", help="Also delete field values from existing items"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    Delete a field from an application.

    WARNING: This will delete all data stored in this field for all items.

    When --delete-values is specified, field values are cleared from all existing
    items before the field is deleted. This works around a Podio API limitation
    where delete_values=true does not actually remove data from items.

    Examples:
        podio app field delete 12345 67890
        podio app field delete 12345 67890 --force
        podio app field delete 12345 67890 --delete-values
        podio app field delete 12345 67890 --table
    """
    try:
        if not force:
            confirm = typer.confirm(
                "WARNING: Deleting a field will remove all data stored in it. Use --force to skip this prompt. Continue?"
            )
            if not confirm:
                print("Aborted.", file=sys.stderr)
                raise typer.Exit(0)

        client = get_client()

        # If delete_values is requested, we need to manually clear field values first
        # because the Podio API's delete_values parameter does not actually work
        if delete_values:
            # Get field info to determine external_id
            field_info = client.Application.get_field(app_id=app_id, field_id=field_id)
            external_id = field_info.get('external_id')

            if not external_id:
                print_error(f"Could not determine external_id for field {field_id}")
                raise typer.Exit(1)

            print(f"Clearing field values from existing items...", file=sys.stderr)
            updated_count = _clear_field_values_from_items(client, app_id, field_id, external_id)
            print(f"Cleared field values from {updated_count} items", file=sys.stderr)

        # Now delete the field from the app schema
        # Pass delete_values=True to the API as well (in case Podio fixes this in the future)
        if delete_values:
            result = client.Application.delete_field(app_id=app_id, field_id=field_id, delete_values=True)
        else:
            result = client.Application.delete_field(app_id=app_id, field_id=field_id)
        formatted = format_response(result)

        print(f"✓ Field deleted successfully", file=sys.stderr)
        print_output(formatted, table=table)

    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)


@field_app.command("list")
def list_fields(
    app_id: int = typer.Argument(..., help="Application ID"),
    include_deleted: bool = typer.Option(False, "--include-deleted", "-d", help="Include deleted fields"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum fields to return"),
    filter: Optional[str] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated list of fields to include"),
    table: bool = typer.Option(False, "--table", "-t", help="Output as formatted table"),
):
    """
    List all fields in an application.

    By default, only active fields are shown. Use --include-deleted to show all fields.

    Examples:
        podio app field list 12345
        podio app field list 12345 --include-deleted
        podio app field list 12345 --table
        podio app field list 12345 --limit 10
        podio app field list 12345 --filter "type:eq:text"
    """
    try:
        client = get_client()
        result = client.Application.find(app_id=app_id)

        fields = result.get('fields', [])
        if not include_deleted:
            fields = [f for f in fields if f.get('status') != 'deleted']

        # Format output with renamed/reordered columns
        output = []
        for field in fields:
            output.append({
                'id': field.get('field_id'),
                'display_name': field.get('label'),
                'name': field.get('external_id'),
                'type': field.get('type'),
                'status': field.get('status'),
                'required': field.get('config', {}).get('required', False),
                'deleted': field.get('status') == 'deleted',
            })

        # Apply client-side filter if specified
        if filter and isinstance(output, list):
            output = apply_filters(output, [filter])

        # Apply limit
        if isinstance(output, list) and len(output) > limit:
            output = output[:limit]

        # Apply properties filter
        if properties:
            output = apply_properties(output, properties)

        print_output(output, table=table)

    except Exception as e:
        exit_code = handle_api_error(e)
        raise typer.Exit(exit_code)
