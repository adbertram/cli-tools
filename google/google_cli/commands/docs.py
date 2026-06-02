"""Google Docs commands."""
COMMAND_CREDENTIALS = {
    "list": ["custom"],
    "get": ["custom"],
    "read": ["custom"],
    "create": ["custom"],
    "export": ["custom"],
    "update": ["custom"],
    "tables": ["custom"],
}

import typer
import io
import os
import re
import json
from typing import Optional, List, Dict, Any
from pathlib import Path
from googleapiclient.errors import HttpError
from ..client import get_client
from cli_tools_shared.output import print_json, print_table, handle_error, print_success, print_error
from cli_tools_shared.filters import apply_filters as _client_side_filter_reference
from ..filter_translator import translate_docs_filters

# Export format MIME types
EXPORT_FORMATS = {
    'txt': 'text/plain',
    'pdf': 'application/pdf',
    'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'html': 'text/html',
    'rtf': 'application/rtf',
    'epub': 'application/epub+zip',
    'md': 'text/plain',  # Export as text, then we'll format as markdown
}

app = typer.Typer(help="Manage Google Docs documents")

@app.command("list")
def docs_list(
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of documents to list"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[List[str]] = typer.Option(None, "--properties", "-p", help="Properties to include in output"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """List Google Docs documents."""
    try:
        client = get_client(profile=profile)
        service = client.get_drive_service()

        # Build query to filter for Google Docs
        query_parts = ["mimeType='application/vnd.google-apps.document'"]

        # Translate filters to Drive query syntax (supports both standard and native formats)
        if filter:
            filter_query = translate_docs_filters(filter)
            if filter_query:
                query_parts.append(filter_query)

        query = " and ".join(query_parts)

        results = service.files().list(
            pageSize=limit,
            q=query,
            fields="files(id, name, createdTime, modifiedTime, webViewLink)",
            orderBy="modifiedTime desc"
        ).execute()

        documents = results.get('files', [])

        # Filter to requested properties
        if properties:
            documents = [{k: v for k, v in d.items() if k in properties} for d in documents]

        if table:
            table_cols = properties[:3] if properties else ['name', 'id', 'modifiedTime']
            table_headers = {'name': 'Name', 'id': 'ID', 'modifiedTime': 'Modified'}
            print_table(documents, table_cols, [table_headers.get(c, c.title()) for c in table_cols])
        else:
            print_json(documents)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))

@app.command("get")
def docs_get(
    document_id: str = typer.Argument(..., help="Document ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Get a document by ID."""
    try:
        client = get_client(profile=profile)
        service = client.get_docs_service()

        document = service.documents().get(documentId=document_id).execute()

        if table:
            # Display basic document metadata as table
            data = [{
                'documentId': document.get('documentId'),
                'title': document.get('title'),
                'revisionId': document.get('revisionId'),
            }]
            print_table(data, ['title', 'documentId', 'revisionId'], ['Title', 'Document ID', 'Revision ID'])
        else:
            print_json(document)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))

def _extract_all_text(obj: Any) -> str:
    """Recursively extract ALL text content from any Google Docs structure.

    Traverses the entire document structure and extracts text from:
    - textRun elements (main text content)
    - All nested structures (tables, lists, etc.)
    """
    if isinstance(obj, dict):
        # If this is a textRun, extract its content
        if 'textRun' in obj:
            return obj['textRun'].get('content', '')

        # Otherwise, recursively process all values
        texts = []
        for key, value in obj.items():
            # Skip non-content keys that don't contain text
            if key in ('startIndex', 'endIndex', 'textStyle', 'paragraphStyle',
                       'bullet', 'tableCellStyle', 'tableStyle', 'namedStyleType',
                       'documentId', 'revisionId', 'title', 'documentStyle',
                       'namedStyles', 'suggestionsViewMode', 'inlineObjectProperties',
                       'positionedObjectProperties'):
                continue
            texts.append(_extract_all_text(value))
        return ''.join(texts)

    elif isinstance(obj, list):
        return ''.join(_extract_all_text(item) for item in obj)

    return ''


@app.command("read")
def docs_read(
    document_id: str = typer.Argument(..., help="Document ID"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Read document content (text only).

    Extracts 100% of all text from the document including paragraphs,
    tables, headers, footers, and all other content.
    """
    try:
        client = get_client(profile=profile)
        service = client.get_docs_service()

        document = service.documents().get(documentId=document_id).execute()

        # Extract ALL text content recursively from the body
        content = _extract_all_text(document.get('body', {}))

        result = {
            'documentId': document.get('documentId'),
            'title': document.get('title'),
            'content': content
        }

        print_json(result)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))

@app.command("create")
def docs_create(
    title: str = typer.Option(..., "--title", "-t", help="Document title"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Create a new document."""
    try:
        client = get_client(profile=profile)
        service = client.get_docs_service()

        document = service.documents().create(body={'title': title}).execute()

        print_success(f"Created document: {document.get('title')}")
        print_json({
            'documentId': document.get('documentId'),
            'title': document.get('title'),
            'url': f"https://docs.google.com/document/d/{document.get('documentId')}/edit"
        })

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


def _extract_markdown_from_doc(document: dict) -> str:
    """Extract markdown-formatted content from a Google Doc structure.

    Converts Google Doc elements to markdown, preserving:
    - Headings (H1-H6)
    - Bold and italic text
    - Links
    - Lists (ordered and unordered)
    - Tables
    """
    lines = []
    body = document.get('body', {})

    for element in body.get('content', []):
        if 'paragraph' in element:
            paragraph = element['paragraph']
            style = paragraph.get('paragraphStyle', {})
            named_style = style.get('namedStyleType', 'NORMAL_TEXT')

            # Build paragraph text with formatting
            para_text = []
            for text_element in paragraph.get('elements', []):
                if 'textRun' in text_element:
                    text_run = text_element['textRun']
                    content = text_run.get('content', '')
                    text_style = text_run.get('textStyle', {})

                    # Skip empty content
                    if not content or content == '\n':
                        continue

                    # Apply formatting
                    text = content.rstrip('\n')

                    # Check for link
                    if 'link' in text_style:
                        url = text_style['link'].get('url', '')
                        if url:
                            text = f"[{text}]({url})"

                    # Apply bold/italic
                    is_bold = text_style.get('bold', False)
                    is_italic = text_style.get('italic', False)

                    if is_bold and is_italic:
                        text = f"***{text}***"
                    elif is_bold:
                        text = f"**{text}**"
                    elif is_italic:
                        text = f"*{text}*"

                    para_text.append(text)

            full_text = ''.join(para_text).strip()

            if not full_text:
                lines.append('')
                continue

            # Apply heading styles
            if named_style == 'TITLE':
                lines.append(f"# {full_text}")
            elif named_style == 'HEADING_1':
                lines.append(f"# {full_text}")
            elif named_style == 'HEADING_2':
                lines.append(f"## {full_text}")
            elif named_style == 'HEADING_3':
                lines.append(f"### {full_text}")
            elif named_style == 'HEADING_4':
                lines.append(f"#### {full_text}")
            elif named_style == 'HEADING_5':
                lines.append(f"##### {full_text}")
            elif named_style == 'HEADING_6':
                lines.append(f"###### {full_text}")
            else:
                # Check for list items
                bullet = paragraph.get('bullet')
                if bullet:
                    nesting_level = bullet.get('nestingLevel', 0)
                    indent = '  ' * nesting_level
                    lines.append(f"{indent}- {full_text}")
                else:
                    lines.append(full_text)

        elif 'table' in element:
            table = element['table']
            table_rows = table.get('tableRows', [])

            if not table_rows:
                continue

            md_table = []
            for row_idx, row in enumerate(table_rows):
                cells = row.get('tableCells', [])
                row_content = []

                for cell in cells:
                    cell_text = []
                    for content in cell.get('content', []):
                        if 'paragraph' in content:
                            for elem in content['paragraph'].get('elements', []):
                                if 'textRun' in elem:
                                    cell_text.append(elem['textRun'].get('content', '').strip())
                    row_content.append(' '.join(cell_text).replace('\n', ' ').strip())

                md_table.append('| ' + ' | '.join(row_content) + ' |')

                # Add header separator after first row
                if row_idx == 0:
                    separator = '| ' + ' | '.join(['---'] * len(row_content)) + ' |'
                    md_table.append(separator)

            lines.extend(md_table)
            lines.append('')

    return '\n'.join(lines)


@app.command("export")
def docs_export(
    document_id: str = typer.Argument(..., help="Document ID"),
    format: str = typer.Option("txt", "--format", "-f", help="Export format: txt, pdf, docx, html, rtf, epub, md"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file path (default: stdout for text formats)"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Export a Google Doc to various formats.

    Supported formats:
    - txt: Plain text
    - md: Markdown (preserves headings, bold, italic, links, tables)
    - pdf: PDF document
    - docx: Microsoft Word
    - html: HTML
    - rtf: Rich Text Format
    - epub: EPUB ebook

    Examples:
        google docs export DOC_ID --format md
        google docs export DOC_ID --format pdf -o document.pdf
        google docs export DOC_ID --format txt > content.txt
    """
    format = format.lower()

    if format not in EXPORT_FORMATS:
        print_error(f"Unsupported format: {format}")
        print_error(f"Supported formats: {', '.join(EXPORT_FORMATS.keys())}")
        raise typer.Exit(1)

    try:
        client = get_client(profile=profile)
        drive_service = client.get_drive_service()

        # For markdown, we need the full document structure
        if format == 'md':
            docs_service = client.get_docs_service()
            document = docs_service.documents().get(documentId=document_id).execute()
            content = _extract_markdown_from_doc(document)

            if output:
                with open(output, 'w', encoding='utf-8') as f:
                    f.write(content)
                print_success(f"Exported to {output}")
            else:
                print(content)
            return

        # For other formats, use Drive API export
        mime_type = EXPORT_FORMATS[format]
        request = drive_service.files().export_media(fileId=document_id, mimeType=mime_type)

        # For binary formats (pdf, docx, epub), require output file
        binary_formats = ['pdf', 'docx', 'epub', 'rtf']

        if format in binary_formats and not output:
            # Generate default filename
            file_info = drive_service.files().get(fileId=document_id, fields='name').execute()
            base_name = file_info.get('name', 'document')
            # Clean filename
            base_name = re.sub(r'[^\w\s-]', '', base_name).strip()
            output = f"{base_name}.{format}"

        # Download content
        from googleapiclient.http import MediaIoBaseDownload
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)

        done = False
        while not done:
            status, done = downloader.next_chunk()

        content = fh.getvalue()

        if output:
            with open(output, 'wb') as f:
                f.write(content)
            print_success(f"Exported to {output}")
        else:
            # Text formats can go to stdout
            if format in ['txt', 'html']:
                print(content.decode('utf-8'))
            else:
                print_error(f"Binary format '{format}' requires --output file path")
                raise typer.Exit(1)

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update")
def docs_update(
    document_id: str = typer.Argument(..., help="Document ID"),
    content: Optional[str] = typer.Option(None, "--content", "-c", help="New content to replace document body"),
    content_file: Optional[Path] = typer.Option(None, "--file", "-f", help="Path to file containing new content"),
    append: bool = typer.Option(False, "--append", "-a", help="Append content instead of replacing"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Update a Google Doc's content.

    Replaces the entire document body with new content, or appends to the end.

    Examples:
        google docs update DOC_ID --content "New content here"
        google docs update DOC_ID --file content.md
        google docs update DOC_ID --file content.md --append
    """
    # Validate input
    if not content and not content_file:
        print_error("Must provide either --content or --file")
        raise typer.Exit(1)

    if content and content_file:
        print_error("Cannot provide both --content and --file")
        raise typer.Exit(1)

    # Read content from file if provided
    if content_file:
        if not content_file.exists():
            print_error(f"File not found: {content_file}")
            raise typer.Exit(1)
        content = content_file.read_text(encoding='utf-8')

    try:
        client = get_client(profile=profile)
        service = client.get_docs_service()

        # Get the document to find its current structure
        document = service.documents().get(documentId=document_id).execute()

        requests = []

        if append:
            # Find the end of the document
            body_content = document.get('body', {}).get('content', [])
            if body_content:
                # Get the end index of the last element
                last_element = body_content[-1]
                end_index = last_element.get('endIndex', 1) - 1  # -1 to insert before final newline
            else:
                end_index = 1

            # Insert at the end
            requests.append({
                'insertText': {
                    'location': {'index': end_index},
                    'text': '\n' + content
                }
            })
        else:
            # Replace: Delete all content first, then insert new content
            body_content = document.get('body', {}).get('content', [])
            if body_content:
                # Find the end index (last element's endIndex - 1 to preserve required trailing newline)
                last_element = body_content[-1]
                end_index = last_element.get('endIndex', 1) - 1

                # Only delete if there's content beyond the first character
                if end_index > 1:
                    requests.append({
                        'deleteContentRange': {
                            'range': {
                                'startIndex': 1,
                                'endIndex': end_index
                            }
                        }
                    })

            # Insert new content at the beginning
            requests.append({
                'insertText': {
                    'location': {'index': 1},
                    'text': content
                }
            })

        # Execute the batch update
        if requests:
            service.documents().batchUpdate(
                documentId=document_id,
                body={'requests': requests}
            ).execute()

        print_success(f"Updated document: {document.get('title')}")
        print_json({
            'documentId': document_id,
            'title': document.get('title'),
            'url': f"https://docs.google.com/document/d/{document_id}/edit"
        })

    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))


def _find_tables_in_document(document: dict) -> List[Dict[str, Any]]:
    """Extract all tables from a document with their structure and cell positions.

    Returns a list of tables, each containing:
    - table_index: 0-based index of the table in the document
    - start_index: document index where table starts
    - rows: list of rows, each containing cells with their content and indices
    """
    tables = []
    body = document.get('body', {})
    table_index = 0

    for element in body.get('content', []):
        if 'table' not in element:
            continue

        table = element['table']
        table_start = element.get('startIndex', 0)
        table_data = {
            'table_index': table_index,
            'start_index': table_start,
            'rows': []
        }

        for row in table.get('tableRows', []):
            row_data = []
            for cell in row.get('tableCells', []):
                cell_start = cell.get('startIndex', 0)
                cell_end = cell.get('endIndex', 0)

                # Extract cell text content - track both first paragraph and full content range
                cell_text = []
                first_para_start = None
                first_para_end = None
                all_text = []
                all_text_start = None
                all_text_end = None

                for content in cell.get('content', []):
                    if 'paragraph' in content:
                        para_text = []
                        para_start = None
                        para_end = None

                        for elem in content['paragraph'].get('elements', []):
                            if 'textRun' in elem:
                                text = elem['textRun'].get('content', '')
                                para_text.append(text)
                                all_text.append(text)
                                elem_start = elem.get('startIndex', 0)
                                elem_end = elem.get('endIndex', 0)
                                if para_start is None:
                                    para_start = elem_start
                                para_end = elem_end

                        # Track full content range (first start to last end)
                        para_content = ''.join(para_text).strip()
                        if para_start is not None and para_content:
                            if all_text_start is None:
                                all_text_start = para_start
                            all_text_end = para_end

                        # Track first paragraph for comparison
                        if first_para_start is None and para_start is not None and para_content:
                            first_para_start = para_start
                            first_para_end = para_end
                            cell_text = para_text

                row_data.append({
                    'start_index': cell_start,
                    'end_index': cell_end,
                    'text_start': all_text_start,  # Use full content range for updates
                    'text_end': all_text_end,
                    'content': ''.join(all_text).strip(),
                    'first_para_content': ''.join(cell_text).strip(),
                    'colspan': cell.get('tableCellStyle', {}).get('columnSpan', 1)
                })

            table_data['rows'].append(row_data)

        tables.append(table_data)
        table_index += 1

    return tables


def _get_cell_content_range(cell: Dict[str, Any]) -> tuple:
    """Get the start and end indices for the content within a table cell.

    Returns (content_start, content_end) for replacing cell content.
    Cell structure: startIndex points to cell start, content starts after that.
    We need to find the actual text range within the cell.
    """
    # The cell content starts after the cell start index
    # We need to account for the paragraph structure
    content_start = cell['start_index'] + 2  # Skip cell marker and paragraph start
    content_end = cell['end_index'] - 1  # Before cell end marker

    return content_start, content_end


# Create tables subcommand group
tables_app = typer.Typer(help="Manage tables in Google Docs")
app.add_typer(tables_app, name="tables")


@tables_app.command("update")
def tables_update(
    document_id: str = typer.Argument(..., help="Document ID"),
    updates_data: Optional[str] = typer.Option(None, "--data", "-d", help="JSON array of updates: [{table, row, col, content}, ...]"),
    updates_file: Optional[Path] = typer.Option(None, "--file", help="Path to JSON file with updates"),
    table_index: Optional[int] = typer.Option(None, "--table", "-t", help="Table index (0-based) for single update"),
    row: Optional[int] = typer.Option(None, "--row", "-r", help="Row index (0-based) for single update"),
    col: Optional[int] = typer.Option(None, "--col", "-c", help="Column index (0-based) for single update"),
    content: Optional[str] = typer.Option(None, "--content", help="New content for single update"),
    label: Optional[str] = typer.Option(None, "--label", "-l", help="Find row by label in first column (alternative to --row)"),
    list_tables: bool = typer.Option(False, "--list", help="List all tables and their structure"),
    profile: Optional[str] = typer.Option(None, "--profile", help="Profile name"),
):
    """Update table cells in a Google Doc.

    Supports two modes:
    1. Single cell update: Use --table, --row (or --label), --col, and --content
    2. Batch updates: Use --data or --file with array of updates

    For batch updates, JSON format:
    [
        {"table": 0, "row": 1, "col": 1, "content": "New value"},
        {"table": 0, "label": "Course Title", "col": 1, "content": "My Course"}
    ]

    When using --label, it finds the row where the first column matches the label.

    Examples:
        # List tables structure
        google docs tables update DOC_ID --list

        # Update single cell by position
        google docs tables update DOC_ID --table 0 --row 1 --col 1 --content "New value"

        # Update single cell by label
        google docs tables update DOC_ID --table 0 --label "Course Title" --col 1 --content "My Course"

        # Batch update from JSON
        google docs tables update DOC_ID --data '[{"table":0,"row":1,"col":1,"content":"Value"}]'
    """
    try:
        client = get_client(profile=profile)
        service = client.get_docs_service()

        # Get document structure
        document = service.documents().get(documentId=document_id).execute()
        tables = _find_tables_in_document(document)

        if not tables:
            print_error("No tables found in document")
            raise typer.Exit(1)

        # List mode - just show table structure
        if list_tables:
            for t in tables:
                print(f"\nTable {t['table_index']}:")
                for row_idx, row in enumerate(t['rows']):
                    row_preview = []
                    for cell in row:
                        preview = cell['content'][:30] + '...' if len(cell['content']) > 30 else cell['content']
                        preview = preview.replace('\n', ' ')
                        row_preview.append(preview)
                    print(f"  Row {row_idx}: {row_preview}")
            return

        # Build updates list
        updates = []

        if updates_data or updates_file:
            # Batch mode
            if updates_file:
                if not updates_file.exists():
                    print_error(f"File not found: {updates_file}")
                    raise typer.Exit(1)
                updates = json.loads(updates_file.read_text())
            else:
                updates = json.loads(updates_data)
        elif table_index is not None and col is not None and content is not None:
            # Single update mode
            if row is None and label is None:
                print_error("Must provide either --row or --label")
                raise typer.Exit(1)

            update = {"table": table_index, "col": col, "content": content}
            if label:
                update["label"] = label
            else:
                update["row"] = row
            updates = [update]
        else:
            print_error("Must provide updates via --data/--file or --table/--row/--col/--content")
            raise typer.Exit(1)

        # Resolve labels to row indices
        for update in updates:
            if "label" in update:
                table_idx = update["table"]
                if table_idx >= len(tables):
                    print_error(f"Table {table_idx} not found (document has {len(tables)} tables)")
                    raise typer.Exit(1)

                table_data = tables[table_idx]
                found_row = None
                search_label = update["label"].strip().lower()

                for row_idx, row in enumerate(table_data['rows']):
                    if row:
                        # Normalize cell content: collapse whitespace/newlines
                        cell_content = ' '.join(row[0]['content'].split()).lower()
                        # Match if cell content starts with the search label
                        # This ensures "Course Title" matches "course title" but not "Course Information"
                        if cell_content.startswith(search_label):
                            found_row = row_idx
                            break

                if found_row is None:
                    print_error(f"Label '{update['label']}' not found in table {table_idx}")
                    raise typer.Exit(1)

                update["row"] = found_row

        # Build batch update requests
        # Process updates in reverse order of document position to avoid index shifting
        requests = []
        update_positions = []

        for update in updates:
            table_idx = update["table"]
            row_idx = update["row"]
            col_idx = update["col"]
            new_content = update["content"]

            if table_idx >= len(tables):
                print_error(f"Table {table_idx} not found")
                raise typer.Exit(1)

            table_data = tables[table_idx]

            if row_idx >= len(table_data['rows']):
                print_error(f"Row {row_idx} not found in table {table_idx}")
                raise typer.Exit(1)

            row = table_data['rows'][row_idx]

            if col_idx >= len(row):
                print_error(f"Column {col_idx} not found in row {row_idx}")
                raise typer.Exit(1)

            cell = row[col_idx]

            # Get the actual text range within the cell
            text_start = cell.get('text_start')
            text_end = cell.get('text_end')

            # If no text content found, use cell structure estimate
            if text_start is None or text_end is None:
                text_start = cell['start_index'] + 2
                text_end = cell['end_index'] - 1

            # text_end includes trailing newline which is structural - exclude it
            # We want to replace content but keep the final newline
            if text_end > text_start:
                text_end = text_end - 1

            # Get first paragraph content for comparison
            first_para = cell.get('first_para_content', cell['content']).strip()

            # DEBUG (uncomment to enable)
            # print(f"DEBUG: table={table_idx} row={row_idx} col={col_idx}")
            # print(f"  first_para: {repr(first_para[:50] if first_para else '')}")
            # print(f"  new_content: {repr(new_content[:50] if new_content else '')}")

            # Skip if first paragraph content is the same (avoid unnecessary updates)
            if first_para == new_content.strip():
                continue

            # Skip if range is invalid
            if text_end <= text_start:
                continue

            update_positions.append({
                'start': text_start,
                'end': text_end,
                'content': new_content,
                'old_content': first_para,
                'table': table_idx,
                'row': row_idx,
                'col': col_idx
            })

        # Sort by position descending (update from end to start to avoid index shifts)
        update_positions.sort(key=lambda x: x['start'], reverse=True)

        for pos in update_positions:
            # Delete existing content in the first paragraph
            if pos['end'] > pos['start']:
                requests.append({
                    'deleteContentRange': {
                        'range': {
                            'startIndex': pos['start'],
                            'endIndex': pos['end']
                        }
                    }
                })

            # Insert new content
            requests.append({
                'insertText': {
                    'location': {'index': pos['start']},
                    'text': pos['content']
                }
            })

        if not requests:
            print_success("No updates needed (content unchanged)")
            print_json({
                'documentId': document_id,
                'title': document.get('title'),
                'url': f"https://docs.google.com/document/d/{document_id}/edit",
                'updates': 0
            })
            return

        # Execute batch update
        service.documents().batchUpdate(
            documentId=document_id,
            body={'requests': requests}
        ).execute()

        print_success(f"Updated {len(update_positions)} cell(s) in document")
        print_json({
            'documentId': document_id,
            'title': document.get('title'),
            'url': f"https://docs.google.com/document/d/{document_id}/edit",
            'updates': len(update_positions)
        })

    except json.JSONDecodeError as e:
        print_error(f"Invalid JSON: {e}")
        raise typer.Exit(1)
    except HttpError as e:
        print_error(f"HTTP error: {e}")
        raise typer.Exit(1)
    except Exception as e:
        raise typer.Exit(handle_error(e))
