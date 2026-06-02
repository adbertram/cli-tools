"""Grammarly Docs commands.

Manage Grammarly documents using cookie-based authentication.
Requires browser-session cookies from app.grammarly.com.

To get cookies:
    1. Open https://app.grammarly.com in your browser and log in
    2. Open DevTools (F12) → Network tab
    3. Find any request to grammarly.com
    4. Copy the 'Cookie' request header value
    5. Save to file: echo 'grauth=xxx; csrf-token=xxx; ...' > ~/.grammarly_cookies
       or export GRAMMARLY_COOKIES='grauth=xxx; csrf-token=xxx; ...'
    6. Run: grammarly auth login --credential-type browser_session
"""
import typer
import random
import string
from typing import Optional, List

from ..client import get_docs_client, ClientError
from cli_tools_shared.filters import apply_filters, validate_filters
from cli_tools_shared.output import print_json, print_table, print_error, print_success


app = typer.Typer(help="Manage Grammarly documents", no_args_is_help=True)


def _generate_doc_id(length: int = 10) -> str:
    """Generate a random document ID similar to Grammarly's format."""
    chars = string.ascii_letters + string.digits
    return "".join(random.choice(chars) for _ in range(length))


@app.command("list")
def docs_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(20, "--limit", "-l", help="Maximum number of documents"),
    search: str = typer.Option("", "--search", "-s", help="Search query"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"
    ),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated list of fields to include"
    ),
):
    """List Grammarly documents."""
    try:
        client = get_docs_client()
        docs = client.list_documents(limit=limit, search=search)

        # Convert to dicts for filtering/output
        docs_data = [doc.model_dump(by_alias=True) for doc in docs]

        # Apply client-side filters if provided
        if filter:
            validate_filters(filter)
            docs_data = apply_filters(docs_data, filter)

        # Filter to requested properties
        if properties:
            prop_list = [p.strip() for p in properties.split(",")]
            docs_data = [{k: v for k, v in d.items() if k in prop_list} for d in docs_data]

        if table:
            columns = ["title", "id", "updated_at"]
            if properties:
                columns = [p.strip() for p in properties.split(",")][:4]
            headers = [c.replace("_", " ").title() for c in columns]
            print_table(docs_data, columns, headers)
        else:
            print_json(docs_data)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("get")
def docs_get(
    document_id: str = typer.Argument(..., help="Document ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get a document by ID."""
    try:
        client = get_docs_client()
        doc = client.get_document(document_id)

        doc_data = doc.model_dump(by_alias=True)

        if table:
            print_table(
                [doc_data],
                ["title", "id", "updated_at"],
                ["Title", "ID", "Modified"],
            )
        else:
            print_json(doc_data)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("read")
def docs_read(
    document_id: str = typer.Argument(..., help="Document ID"),
):
    """Read document content (text only).

    Returns the document with its full text content.
    """
    try:
        client = get_docs_client()
        doc = client.get_document_content(document_id)

        result = {
            "id": doc.id,
            "title": doc.title,
            "content": doc.content,
        }

        print_json(result)

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


@app.command("new")
def docs_new(
    title: Optional[str] = typer.Option(None, "--title", "-t", help="Document title"),
):
    """Create a new document.

    Opens a URL to create a new Grammarly document.
    Note: Grammarly creates documents client-side via URL navigation.
    This command outputs the URL to open.
    """
    try:
        # Verify authentication first
        client = get_docs_client()
        user = client.get_user()

        # Generate a new document ID
        doc_id = _generate_doc_id()

        # Grammarly creates docs by navigating to this URL pattern
        doc_url = f"https://coda.grammarly.com/d/_{doc_id}?isBlank="
        editor_url = f"https://app.grammarly.com/ddocs/{doc_id}"

        print_success(f"Document ID generated: {doc_id}")
        print_json({
            "id": doc_id,
            "title": title or "Untitled",
            "coda_url": doc_url,
            "editor_url": editor_url,
            "instructions": "Open the editor_url in your browser to create and edit the document.",
        })

    except ClientError as e:
        print_error(str(e))
        raise typer.Exit(1)


COMMAND_CREDENTIALS = {
    "get": [
        "browser_session"
    ],
    "list": [
        "browser_session"
    ],
    "new": [
        "browser_session"
    ],
    "read": [
        "browser_session"
    ]
}
