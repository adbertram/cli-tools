"""Google Sheets commands."""
COMMAND_CREDENTIALS = {
    "list": ["custom"],
    "get": ["custom"],
    "read": ["custom"],
    "create": ["custom"],
    "append": ["custom"],
    "update": ["custom"],
    "clear": ["custom"],
}

import json
import re
import typer
from typing import Optional
from googleapiclient.errors import HttpError
from ..client import get_client, DRIVE_LIST_ALL_DRIVES
from ..properties import parse_properties
from cli_tools_shared.output import command, print_json, print_table, handle_error, print_success, print_error
from cli_tools_shared.filters import apply_filters as _client_side_filter_reference
from ..filter_translator import translate_sheets_filters

app = typer.Typer(help="Manage Google Sheets spreadsheets")


@app.command("list")
@command
def sheets_list(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of spreadsheets to list"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter: Optional[list[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[list[str]] = typer.Option(None, "--properties", "-p", help="Properties to include in output"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """List Google Sheets spreadsheets."""
    try:
        properties = parse_properties(properties)
        client = get_client(profile=profile)
        service = client.get_drive_service()

        # Build query to filter for Google Sheets
        query_parts = ["mimeType='application/vnd.google-apps.spreadsheet'"]

        # Translate filters to Drive query syntax (supports both standard and native formats)
        if filter:
            filter_query = translate_sheets_filters(filter)
            if filter_query:
                query_parts.append(filter_query)

        query = " and ".join(query_parts)

        results = service.files().list(
            pageSize=limit,
            q=query,
            fields="files(id, name, createdTime, modifiedTime, webViewLink)",
            orderBy="modifiedTime desc",
            **DRIVE_LIST_ALL_DRIVES,
        ).execute()

        spreadsheets = results.get('files', [])

        # Filter to requested properties
        if properties:
            spreadsheets = [{k: v for k, v in s.items() if k in properties} for s in spreadsheets]

        if table:
            table_cols = properties[:3] if properties else ['name', 'id', 'modifiedTime']
            table_headers = {'name': 'Name', 'id': 'ID', 'modifiedTime': 'Modified'}
            print_table(spreadsheets, table_cols, [table_headers.get(c, c.title()) for c in table_cols])
        else:
            print_json(spreadsheets)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


def parse_spreadsheet_id(spreadsheet_id_or_url: str) -> str:
    """Extract spreadsheet ID from a URL or return the ID as-is.

    Supports URLs like:
    - https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit
    - https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit?gid=123#gid=123
    - https://docs.google.com/spreadsheets/d/SPREADSHEET_ID
    """
    # Check if it looks like a URL
    if spreadsheet_id_or_url.startswith(("http://", "https://", "docs.google.com")):
        # Extract the spreadsheet ID from the URL
        match = re.search(r'/spreadsheets/d/([a-zA-Z0-9_-]+)', spreadsheet_id_or_url)
        if match:
            return match.group(1)
        raise typer.BadParameter(f"Could not extract spreadsheet ID from URL: {spreadsheet_id_or_url}")

    # Otherwise, assume it's already a spreadsheet ID
    return spreadsheet_id_or_url

@app.command("get")
@command
def sheets_get(
    spreadsheet_id_or_url: str = typer.Argument(..., help="Spreadsheet ID or URL"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Get spreadsheet metadata."""
    try:
        spreadsheet_id = parse_spreadsheet_id(spreadsheet_id_or_url)
        client = get_client(profile=profile)
        service = client.get_sheets_service()

        spreadsheet = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()

        if table:
            props = spreadsheet.get('properties', {})
            data = [{
                'title': props.get('title'),
                'spreadsheetId': spreadsheet.get('spreadsheetId'),
                'locale': props.get('locale'),
            }]
            print_table(data, ['title', 'spreadsheetId', 'locale'], ['Title', 'Spreadsheet ID', 'Locale'])
        else:
            print_json(spreadsheet)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))

@app.command("read")
@command
def sheets_read(
    spreadsheet_id_or_url: str = typer.Argument(..., help="Spreadsheet ID or URL"),
    range_name: str = typer.Option("A:Z", "--range", "-r", help="Range to read (e.g., A1:D10 or TabName!A1:D10)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    formulas: bool = typer.Option(False, "--formulas", help="Return formula text for formula cells instead of computed values"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Read values from a spreadsheet."""
    try:
        spreadsheet_id = parse_spreadsheet_id(spreadsheet_id_or_url)
        client = get_client(profile=profile)
        service = client.get_sheets_service()

        get_kwargs = {"valueRenderOption": "FORMULA"} if formulas else {}
        result = service.spreadsheets().values().get(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            **get_kwargs,
        ).execute()

        values = result.get('values', [])

        if not values:
            print_error("No data found")
            raise typer.Exit(1)

        if table:
            # Use first row as headers
            headers = values[0] if values else []
            rows = values[1:] if len(values) > 1 else []

            # Convert rows to dicts
            data = []
            for row in rows:
                # Pad row with empty strings if needed
                row_dict = {}
                for i, header in enumerate(headers):
                    row_dict[header] = row[i] if i < len(row) else ""
                data.append(row_dict)

            if data:
                print_table(data, headers, headers)
            else:
                print("No data rows found")
        else:
            print_json(values)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))

@app.command("create")
@command
def sheets_create(
    title: str = typer.Option(..., "--title", "-t", help="Spreadsheet title"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Create a new spreadsheet."""
    try:
        client = get_client(profile=profile)
        service = client.get_sheets_service()

        spreadsheet = service.spreadsheets().create(
            body={'properties': {'title': title}}
        ).execute()

        print_success(f"Created spreadsheet: {spreadsheet.get('properties', {}).get('title')}")
        print_json({
            'spreadsheetId': spreadsheet.get('spreadsheetId'),
            'title': spreadsheet.get('properties', {}).get('title'),
            'url': spreadsheet.get('spreadsheetUrl')
        })

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))

@app.command("append")
@command
def sheets_append(
    spreadsheet_id_or_url: str = typer.Argument(..., help="Spreadsheet ID or URL"),
    range_name: str = typer.Option("A:Z", "--range", "-r", help="Range to append to"),
    values: str = typer.Option(..., "--values", "-v", help="Values to append (comma-separated)"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Append values to a spreadsheet."""
    try:
        spreadsheet_id = parse_spreadsheet_id(spreadsheet_id_or_url)
        client = get_client(profile=profile)
        service = client.get_sheets_service()

        # Parse values
        row_values = [v.strip() for v in values.split(',')]

        body = {
            'values': [row_values]
        }

        result = service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption='RAW',
            body=body
        ).execute()

        print_success(f"Appended {result.get('updates', {}).get('updatedCells', 0)} cells")
        print_json(result.get('updates', {}))

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update")
@command
def sheets_update(
    spreadsheet_id_or_url: str = typer.Argument(..., help="Spreadsheet ID or URL"),
    range_name: str = typer.Option(..., "--range", "-r", help="Cell or range to update (e.g., Sheet1!A1, Sheet1!A1:C3)"),
    values: Optional[str] = typer.Option(None, "--values", "-v", help="Values to write (comma-separated for row, semicolon-separated for multiple rows)"),
    values_json: Optional[str] = typer.Option(None, "--values-json", help="Values to write as a JSON array of rows (e.g. '[[\"a, b\", \"c; d\"]]'); cells may contain commas and semicolons. Mutually exclusive with --values"),
    raw: bool = typer.Option(False, "--raw", help="Use RAW input (default is USER_ENTERED which parses formulas/numbers)"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Update values in specific cells or range.

    Examples:
        # Update a single cell
        google sheets update <id> --range "Sheet1!A1" --values "Hello"

        # Update a row (columns A-C)
        google sheets update <id> --range "Sheet1!A1:C1" --values "John,Doe,john@example.com"

        # Update multiple rows (use semicolon to separate rows)
        google sheets update <id> --range "Sheet1!A1:B2" --values "Row1Col1,Row1Col2;Row2Col1,Row2Col2"

        # Update with formula (USER_ENTERED mode, default)
        google sheets update <id> --range "Sheet1!A1" --values "=SUM(B1:B10)"

        # Update with raw text (won't parse formulas)
        google sheets update <id> --range "Sheet1!A1" --values "=SUM(B1:B10)" --raw

        # Cell values containing commas or semicolons (JSON array of rows)
        google sheets update <id> --range "Sheet1!A1:B1" --values-json '[["Intro, part 1", "Setup; install"]]'
    """
    if (values is None) == (values_json is None):
        raise typer.BadParameter("Provide exactly one of --values or --values-json")
    if values_json is not None:
        try:
            parsed_values = json.loads(values_json)
        except json.JSONDecodeError as e:
            raise typer.BadParameter(f"--values-json is not valid JSON: {e}")
        if not isinstance(parsed_values, list) or not all(isinstance(r, list) for r in parsed_values):
            raise typer.BadParameter("--values-json must be a JSON array of rows (an array of arrays)")
    try:
        spreadsheet_id = parse_spreadsheet_id(spreadsheet_id_or_url)
        client = get_client(profile=profile)
        service = client.get_sheets_service()

        if values is not None:
            # Parse values: semicolons separate rows, commas separate columns
            parsed_values = [[v.strip() for v in row.split(',')] for row in values.split(';')]

        body = {
            'values': parsed_values
        }

        # USER_ENTERED parses formulas and numbers, RAW treats everything as strings
        value_input_option = 'RAW' if raw else 'USER_ENTERED'

        result = service.spreadsheets().values().update(
            spreadsheetId=spreadsheet_id,
            range=range_name,
            valueInputOption=value_input_option,
            body=body
        ).execute()

        print_success(f"Updated {result.get('updatedCells', 0)} cells in range {result.get('updatedRange', range_name)}")
        print_json({
            'updatedRange': result.get('updatedRange'),
            'updatedRows': result.get('updatedRows'),
            'updatedColumns': result.get('updatedColumns'),
            'updatedCells': result.get('updatedCells')
        })

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("clear")
@command
def sheets_clear(
    spreadsheet_id_or_url: str = typer.Argument(..., help="Spreadsheet ID or URL"),
    range_names: list[str] = typer.Option(..., "--range", "-r", help="A1 range to clear, may include Tab! (repeat for several ranges)"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Clear values from ranges (formatting is kept)."""
    try:
        spreadsheet_id = parse_spreadsheet_id(spreadsheet_id_or_url)
        client = get_client(profile=profile)
        values = client.get_sheets_service().spreadsheets().values()

        if len(range_names) == 1:
            result = values.clear(spreadsheetId=spreadsheet_id, range=range_names[0], body={}).execute()
            output = {"spreadsheetId": result.get("spreadsheetId"), "clearedRange": result.get("clearedRange")}
        else:
            result = values.batchClear(spreadsheetId=spreadsheet_id, body={"ranges": range_names}).execute()
            output = {"spreadsheetId": result.get("spreadsheetId"), "clearedRanges": result.get("clearedRanges")}

        print_json(output)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))
