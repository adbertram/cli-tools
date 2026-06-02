"""Pages commands for WordPress CLI."""
import typer
from typing import Optional, List
from pathlib import Path

from cli_tools_shared.output import print_json, print_table, handle_error, print_success, print_info
from ..filter_map import wordpress_filter_map
from . import model_to_dict, extract_fields, apply_client_side_filters


app = typer.Typer(help="Manage WordPress pages")

COMMAND_CREDENTIALS = {
    "create": [
        "username_password"
    ],
    "delete": [
        "username_password"
    ],
    "get": [
        "username_password"
    ],
    "list": [
        "username_password"
    ],
    "update": [
        "username_password"
    ]
}


def get_client():
    from ..client import get_client as _get_client
    return _get_client()


@app.command("list")
def pages_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of pages to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display (supports dot-notation)"),
):
    """List WordPress pages."""
    try:
        client = get_client()

        filters = wordpress_filter_map.to_api_params(filter) if filter else {}
        pages = client.list_pages(limit=limit, filters=filters)
        pages = apply_client_side_filters(pages, filter)

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            pages = extract_fields(pages, fields)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(pages, fields, fields)
            else:
                print_table(
                    pages,
                    ["id", "title", "status", "slug", "parent"],
                    ["ID", "Title", "Status", "Slug", "Parent"],
                )
        else:
            print_json(pages)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def pages_get(
    page_id: int = typer.Argument(..., help="The page ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display (supports dot-notation)"),
    raw: bool = typer.Option(False, "--raw", "-r", help="Return raw Gutenberg blocks instead of rendered HTML"),
):
    """Get details for a specific WordPress page."""
    try:
        client = get_client()
        context = "edit" if raw else "view"
        page = client.get_page(page_id, context=context)

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            page = extract_fields([page], fields)[0]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([page], fields, fields)
            else:
                page_dict = model_to_dict(page)
                rows = [{"field": k, "value": str(v)} for k, v in page_dict.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(page)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def pages_create(
    title: Optional[str] = typer.Option(None, "--title", help="Page title (required for manual content)"),
    content: Optional[str] = typer.Option(None, "--content", help="Page content (required for manual content)"),
    status: str = typer.Option("draft", "--status", help="Page status (publish, draft, pending, private, future)"),
    slug: Optional[str] = typer.Option(None, "--slug", help="URL slug for the page"),
    from_docx: Optional[Path] = typer.Option(None, "--from-docx", help="Path to DOCX file to convert"),
    from_markdown: Optional[Path] = typer.Option(None, "--from-markdown", help="Path to Markdown file to convert"),
    date: Optional[str] = typer.Option(None, "--date", help="Schedule date (ISO 8601)"),
    excerpt: Optional[str] = typer.Option(None, "--excerpt", help="Page excerpt"),
    parent: Optional[int] = typer.Option(None, "--parent", help="Parent page ID"),
    menu_order: Optional[int] = typer.Option(None, "--menu-order", help="Order in menus"),
    template: Optional[str] = typer.Option(None, "--template", help="Page template slug"),
    meta: Optional[List[str]] = typer.Option(None, "--meta", help="Page meta (key=value, repeatable)"),
):
    """Create a new WordPress page."""
    try:
        client = get_client()

        input_count = sum([
            bool(title and content),
            bool(from_docx),
            bool(from_markdown)
        ])

        if input_count == 0:
            raise ValueError("Must provide either --title and --content, --from-docx, or --from-markdown")

        if input_count > 1:
            raise ValueError("Cannot use multiple content sources (--title/--content, --from-docx, --from-markdown)")

        if from_docx:
            if not from_docx.exists():
                raise FileNotFoundError(f"DOCX file not found: {from_docx}")

            print_info(f"Converting DOCX file: {from_docx}")
            from ..utils.docx import extract_post_from_docx

            def upload_image(filename: str, data: bytes, content_type: str) -> str:
                media = client.upload_media(filename, data, content_type)
                return media.source_url

            title, content = extract_post_from_docx(from_docx, upload_image)
            print_info(f"Extracted title: {title}")

        elif from_markdown:
            if not from_markdown.exists():
                raise FileNotFoundError(f"Markdown file not found: {from_markdown}")

            print_info(f"Converting Markdown file: {from_markdown}")
            from ..utils.markdown import convert_markdown_to_html
            markdown_content = from_markdown.read_text(encoding='utf-8')
            content = convert_markdown_to_html(markdown_content)

            if not title:
                title = from_markdown.stem.replace('-', ' ').replace('_', ' ').title()
                print_info(f"Using title from filename: {title}")

        meta_dict = None
        if meta:
            meta_dict = {}
            for m in meta:
                key, value = m.split("=", 1)
                meta_dict[key] = value

        print_info(f"Creating page with status: {status}")
        page = client.create_page(
            title=title,
            content=content,
            status=status,
            slug=slug,
            date=date,
            excerpt=excerpt,
            parent=parent,
            menu_order=menu_order,
            template=template,
            meta=meta_dict,
        )

        print_success(f"Page created successfully (ID: {page.id})")
        print_json(page)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update")
def pages_update(
    page_id: int = typer.Argument(..., help="The page ID to update"),
    title: Optional[str] = typer.Option(None, "--title", help="New page title"),
    content: Optional[str] = typer.Option(None, "--content", help="New page content"),
    content_file: Optional[Path] = typer.Option(None, "--content-file", help="Read new page content from file"),
    status: Optional[str] = typer.Option(None, "--status", help="New page status"),
    slug: Optional[str] = typer.Option(None, "--slug", help="New URL slug"),
    date: Optional[str] = typer.Option(None, "--date", help="Schedule date (ISO 8601)"),
    featured_media: Optional[int] = typer.Option(None, "--featured-media", help="Featured image media ID"),
    parent: Optional[int] = typer.Option(None, "--parent", help="Parent page ID"),
    menu_order: Optional[int] = typer.Option(None, "--menu-order", help="Order in menus"),
    template: Optional[str] = typer.Option(None, "--template", help="Page template slug"),
    excerpt: Optional[str] = typer.Option(None, "--excerpt", help="Page excerpt"),
    meta: Optional[List[str]] = typer.Option(None, "--meta", help="Page meta (key=value, repeatable)"),
):
    """Update an existing WordPress page."""
    try:
        client = get_client()

        if content is not None and content_file is not None:
            raise ValueError("Cannot use both --content and --content-file")

        fields = {}
        if title is not None:
            fields["title"] = title
        if content is not None:
            fields["content"] = content
        if content_file is not None:
            if not content_file.exists():
                raise FileNotFoundError(f"Content file not found: {content_file}")
            fields["content"] = content_file.read_text(encoding="utf-8")
        if slug is not None:
            fields["slug"] = slug
        if status is not None:
            fields["status"] = status
        if date is not None:
            fields["date"] = date
        if featured_media is not None:
            fields["featured_media"] = featured_media
        if parent is not None:
            fields["parent"] = parent
        if menu_order is not None:
            fields["menu_order"] = menu_order
        if template is not None:
            fields["template"] = template
        if excerpt is not None:
            fields["excerpt"] = excerpt
        if meta:
            meta_dict = {}
            for m in meta:
                if "=" not in m:
                    raise ValueError(f"Invalid meta format '{m}'. Use key=value format.")
                key, value = m.split("=", 1)
                meta_dict[key] = value
            fields["meta"] = meta_dict

        if not fields:
            raise ValueError("Must provide at least one field to update")

        print_info(f"Updating page {page_id}")
        page = client.update_page(page_id, fields)

        print_success(f"Page {page_id} updated successfully")
        print_json(page)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def pages_delete(
    page_id: int = typer.Argument(..., help="The page ID to delete"),
    force: bool = typer.Option(False, "--force", help="Permanently delete (skip trash)"),
):
    """Delete a WordPress page."""
    try:
        client = get_client()

        action = "Permanently deleting" if force else "Moving to trash"
        print_info(f"{action} page {page_id}")

        result = client.delete_page(page_id, force=force)

        if force:
            print_success(f"Page {page_id} permanently deleted")
        else:
            print_success(f"Page {page_id} moved to trash")

        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))
