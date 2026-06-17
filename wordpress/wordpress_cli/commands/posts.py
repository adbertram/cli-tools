"""Posts commands for WordPress CLI."""
import html
import re
import typer
from typing import Optional, List
from pathlib import Path

from cli_tools_shared.output import print_json, print_table, handle_error, print_success, print_info
from ..filter_map import wordpress_filter_map
from . import model_to_dict, extract_fields, apply_client_side_filters


app = typer.Typer(help="Manage WordPress posts")

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


# A WordPress post excerpt doubles as the SEO meta description and the text shown
# on archive/homepage cards. ATA standard: target 150-200 chars, hard maximum 300
# (matches the Notion "Excerpt Length" threshold). An excerpt longer than this is
# almost always article body text pasted in by mistake, which then leaks into the
# meta description and homepage tiles.
EXCERPT_MAX_CHARS = 300


def _validate_excerpt(excerpt: Optional[str]) -> None:
    """Reject an excerpt longer than the meta-description hard maximum.

    Fails loudly so a bloated excerpt never reaches WordPress, rather than being
    silently truncated or published as-is.
    """
    if excerpt is None:
        return
    length = len(excerpt.strip())
    if length > EXCERPT_MAX_CHARS:
        raise ValueError(
            f"Excerpt is {length} characters; maximum is {EXCERPT_MAX_CHARS}. "
            "The excerpt is the SEO meta description (target 150-200 chars) -- "
            "provide a short summary, not article body text."
        )


def _normalize_heading_text(text: str) -> str:
    """Collapse a heading/title to comparable plain text (tags, entities, case)."""
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip().casefold()


def _strip_duplicate_title_heading(content: str, title: Optional[str]) -> str:
    """Drop a leading <h1> whose text duplicates the post title.

    WordPress renders the Title field as the page H1. DOCX/Markdown conversion
    also emits the document's title as a leading <h1>, so the body would show the
    title twice. Only strips when the leading heading text matches the title, so
    a legitimate first section heading is left untouched.
    """
    if not content or not title:
        return content
    match = re.match(r"\s*<h1\b[^>]*>(.*?)</h1>\s*", content, re.IGNORECASE | re.DOTALL)
    if not match:
        return content
    if _normalize_heading_text(match.group(1)) == _normalize_heading_text(title):
        return content[match.end():]
    return content


@app.command("list")
def posts_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of posts to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display (supports dot-notation)"),
):
    """List WordPress posts."""
    try:
        client = get_client()

        # Convert filter strings to API params using FilterMap
        filters = wordpress_filter_map.to_api_params(filter) if filter else {}

        # Returns List[Post] models
        posts = client.list_posts(limit=limit, filters=filters)

        # Apply client-side filtering for fields without API translators
        posts = apply_client_side_filters(posts, filter)

        # Apply properties field selection with dot-notation support
        if properties:
            fields = [f.strip() for f in properties.split(",")]
            posts = extract_fields(posts, fields)

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table(posts, fields, fields)
            else:
                print_table(
                    posts,
                    ["id", "title", "status", "date"],
                    ["ID", "Title", "Status", "Date"],
                )
        else:
            print_json(posts)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def posts_get(
    post_id: int = typer.Argument(..., help="The post ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display (supports dot-notation)"),
    raw: bool = typer.Option(False, "--raw", "-r", help="Return raw Gutenberg blocks instead of rendered HTML"),
):
    """Get details for a specific WordPress post."""
    try:
        client = get_client()
        context = "edit" if raw else "view"
        post = client.get_post(post_id, context=context)

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            post = extract_fields([post], fields)[0]

        if table:
            if properties:
                fields = [f.strip() for f in properties.split(",")]
                print_table([post], fields, fields)
            else:
                post_dict = model_to_dict(post)
                rows = [{"field": k, "value": str(v)} for k, v in post_dict.items() if v is not None]
                print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(post)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def posts_create(
    title: Optional[str] = typer.Option(None, "--title", help="Post title (required for manual content)"),
    content: Optional[str] = typer.Option(None, "--content", help="Post content (required for manual content)"),
    status: str = typer.Option("draft", "--status", help="Post status (publish, draft, pending, private, future)"),
    slug: Optional[str] = typer.Option(None, "--slug", help="URL slug for the post"),
    from_docx: Optional[Path] = typer.Option(None, "--from-docx", help="Path to DOCX file to convert"),
    from_markdown: Optional[Path] = typer.Option(None, "--from-markdown", help="Path to Markdown file to convert"),
    sponsored: bool = typer.Option(False, "--sponsored", help="Add rel='sponsored nofollow' to all links"),
    date: Optional[str] = typer.Option(None, "--date", help="Schedule date (ISO 8601, e.g., 2026-01-10T09:00:00)"),
    categories: Optional[str] = typer.Option(None, "--categories", help="Category IDs (comma-separated)"),
    tags: Optional[str] = typer.Option(None, "--tags", help="Tag IDs (comma-separated)"),
    excerpt: Optional[str] = typer.Option(None, "--excerpt", help="Post excerpt"),
    meta: Optional[List[str]] = typer.Option(None, "--meta", help="Post meta (key=value, repeatable)"),
):
    """Create a new WordPress post."""
    try:
        _validate_excerpt(excerpt)
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

        # WordPress renders the Title field as the page H1, so a body that opens
        # with the title as <h1> shows it twice. DOCX/Markdown conversion produces
        # exactly that leading heading -- drop it when it matches the title.
        content = _strip_duplicate_title_heading(content, title)

        _is_sponsored = False
        if sponsored:
            _is_sponsored = True
            print_info("Adding rel='sponsored nofollow' to all links")
            from ..utils.docx import _add_link_attributes
            content = _add_link_attributes(content)
            SPONSORED_TAG_ID = "7"
            if tags:
                tags = f"{tags},{SPONSORED_TAG_ID}"
            else:
                tags = SPONSORED_TAG_ID
            print_info("Adding 'Sponsored' tag")

        cat_ids = None
        if categories:
            cat_ids = [int(x.strip()) for x in categories.split(",")]

        tag_ids = None
        if tags:
            tag_ids = [int(x.strip()) for x in tags.split(",")]

        meta_dict = None
        if meta:
            meta_dict = {}
            for m in meta:
                key, value = m.split("=", 1)
                meta_dict[key] = value

        print_info(f"Creating post with status: {status}")
        post = client.create_post(
            title=title,
            content=content,
            status=status,
            slug=slug,
            date=date,
            categories=cat_ids,
            tags=tag_ids,
            excerpt=excerpt,
            meta=meta_dict,
        )

        if _is_sponsored:
            print_info("Disabling Raptive ads")
            ad_meta = {
                "adthrive_ads_disable": "on",
                "adthrive_ads_disable_content_ads": "on",
                "adthrive_ads_disable_auto_insert_videos": "on",
            }
            client.update_post(post.id, {"meta": ad_meta})

        print_success(f"Post created successfully (ID: {post.id})")
        print_json(post)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update")
def posts_update(
    post_id: int = typer.Argument(..., help="The post ID to update"),
    title: Optional[str] = typer.Option(None, "--title", help="New post title"),
    content: Optional[str] = typer.Option(None, "--content", help="New post content"),
    content_file: Optional[Path] = typer.Option(None, "--content-file", help="Read new post content from file"),
    status: Optional[str] = typer.Option(None, "--status", help="New post status (publish, draft, pending, private, future)"),
    slug: Optional[str] = typer.Option(None, "--slug", help="New URL slug"),
    date: Optional[str] = typer.Option(None, "--date", help="Schedule date (ISO 8601, e.g., 2026-01-10T09:00:00)"),
    auto_schedule: bool = typer.Option(False, "--auto-schedule", help="Auto-find next available slot (max 2/day, 4hr gaps, weekdays only)"),
    featured_media: Optional[int] = typer.Option(None, "--featured-media", help="Featured image media ID"),
    tags: Optional[str] = typer.Option(None, "--tags", help="Tag IDs (comma-separated)"),
    excerpt: Optional[str] = typer.Option(None, "--excerpt", help="Post excerpt"),
    meta: Optional[List[str]] = typer.Option(None, "--meta", help="Post meta (key=value, repeatable)"),
):
    """Update an existing WordPress post."""
    try:
        _validate_excerpt(excerpt)

        if content is not None and content_file is not None:
            raise ValueError("Cannot use both --content and --content-file")

        client = get_client()

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

        effective_date = None
        effective_status = status

        if auto_schedule:
            effective_date = client.find_next_schedule_slot()
            effective_status = "future"
            print_info(f"Auto-scheduled for: {effective_date}")
        elif date:
            effective_date = date
            effective_status = "future"

        if effective_date:
            fields["date"] = effective_date
        if effective_status is not None:
            fields["status"] = effective_status

        if featured_media is not None:
            fields["featured_media"] = featured_media

        if excerpt is not None:
            fields["excerpt"] = excerpt

        if tags:
            tag_ids = [int(x.strip()) for x in tags.split(",")]
            fields["tags"] = tag_ids

        if meta:
            meta_dict = {}
            for m in meta:
                if "=" not in m:
                    raise ValueError(f"Invalid meta format '{m}'. Use key=value format.")
                key, value = m.split("=", 1)
                meta_dict[key] = value
            fields["meta"] = meta_dict

        if not fields:
            raise ValueError("Must provide at least one field to update (--title, --content, --status, --slug, --date, --auto-schedule, --featured-media, --tags, or --meta)")

        print_info(f"Updating post {post_id}")
        post = client.update_post(post_id, fields)

        # Clear schedule reservation now that post is committed to WordPress
        if auto_schedule:
            client.clear_schedule_reservation()

        if effective_date:
            print_success(f"Post {post_id} scheduled for {effective_date}")
        else:
            print_success(f"Post {post_id} updated successfully")
        print_json(post)

    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("delete")
def posts_delete(
    post_id: int = typer.Argument(..., help="The post ID to delete"),
    force: bool = typer.Option(False, "--force", help="Permanently delete (skip trash)"),
):
    """Delete a WordPress post."""
    try:
        client = get_client()

        action = "Permanently deleting" if force else "Moving to trash"
        print_info(f"{action} post {post_id}")

        result = client.delete_post(post_id, force=force)

        if force:
            print_success(f"Post {post_id} permanently deleted")
        else:
            print_success(f"Post {post_id} moved to trash")

        print_json(result)

    except Exception as e:
        raise typer.Exit(handle_error(e))
