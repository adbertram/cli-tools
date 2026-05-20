"""Notion commands for ATA Blog CLI."""
import subprocess
import sys
import tempfile
from pathlib import Path
import typer
from typing import Optional, List

from ..client import get_client, AtaBlogClient, ClientError
from ..utils.images import process_local_images_for_wordpress
from cli_tools_shared.filters import apply_filters, apply_limit, apply_properties_filter
from cli_tools_shared.output import print_json, print_table, handle_error, print_success, print_info
from cli_tools_shared import FilterMap

COMMAND_CREDENTIALS = {
    "list": ["custom"],
    "get": ["custom"],
    "create": ["custom"],
    "publish": ["custom"],
    "update": ["custom"],
    "search": ["custom"],
    "statuses": ["custom"],
    "comments": ["custom"],
    "comments add": ["custom"],
    "comments list": ["custom"],
    "comments get": ["custom"],
    "content": ["custom"],
    "content get": ["custom"],
    "content set": ["custom"],
    "content append": ["custom"],
    "schema": ["custom"],
    "schema add-property": ["custom"],
}

# Notion API property types that take an empty config object on creation
# (i.e., {"<type>": {}} body). Types that require additional configuration
# (select/multi_select options, relation database, formula expression, etc.)
# are intentionally excluded from this scope.
SCHEMA_EMPTY_CONFIG_TYPES = (
    "rich_text",
    "url",
    "checkbox",
    "number",
    "date",
    "email",
    "phone_number",
    "files",
)

# Filter map for translating CLI arguments to filter strings
_filter_map = FilterMap().add_argument_mapping("status", "Status", "in")

app = typer.Typer(help="Manage Notion pages")
content_app = typer.Typer(help="Manage article content")
app.add_typer(content_app, name="content")
schema_app = typer.Typer(help="Manage Notion database schema (properties/columns)")
app.add_typer(schema_app, name="schema")
comments_app = typer.Typer(help="Manage comments on Notion pages")
app.add_typer(comments_app, name="comments")


@app.command("list")
def articles_list(
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by Status (single or pipe-separated)"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum articles"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-P", help="Comma-separated fields"),
):
    """List articles from Notion database.

    Examples:
        ata-blog notion-page list --status "Draft"
        ata-blog notion-page list --status "Draft|Review"
        ata-blog notion-page list --filter "Status:in:Good Idea|Human Review"
        ata-blog notion-page list --filter "Title:contains:outsmarting"
        ata-blog notion-page list --filter "Title:ilike:%azure%"
    """
    try:
        client = get_client()

        # Parse filters: separate status filters from other filters
        effective_status = status
        non_status_filters = []
        if filter:
            for f in filter:
                if f.lower().startswith("status:"):
                    # Handle status:value, status:eq:value, or status:in:value|value2
                    parts = f.split(":", 2)  # Split max 2 times to preserve | in values
                    if len(parts) == 2:
                        # status:value format
                        effective_status = parts[1]
                    elif len(parts) == 3:
                        # status:op:value format (e.g., status:in:Draft|Review)
                        effective_status = parts[2]
                else:
                    # Non-status filter - pass through to client
                    non_status_filters.append(f)

        articles = client.list_articles(
            status=effective_status,
            limit=limit,
            filters=non_status_filters if non_status_filters else None,
        )

        if properties:
            prop_list = [p.strip() for p in properties.split(",")]
            articles = [{k: v for k, v in item.items() if k in prop_list} for item in articles]

        if table:
            columns = ["id", "Title", "Status", "Author"]
            headers = ["ID", "Title", "Status", "Author"]
            if properties:
                columns = prop_list
                headers = columns
            print_table(articles, columns, headers)
        else:
            print_json(articles)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("get")
def articles_get(
    page_id: str = typer.Argument(..., help="Notion page ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get article details from Notion."""
    try:
        client = get_client()
        article = client.get_article(page_id)

        if table:
            rows = [{"field": k, "value": str(v)[:60]} for k, v in article.items() if v]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(article)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("create")
def articles_create(
    title: str = typer.Option(..., "--title", help="Article title"),
    excerpt: str = typer.Option(..., "--excerpt", help="Article description/synopsis"),
    category: str = typer.Option(..., "--category", help="Category: IT Ops|Home Ops|DevOps|Cloud|Information Security|Ebook"),
    keywords: Optional[str] = typer.Option(None, "--keywords", help="Comma-separated SEO keywords"),
    post_type: str = typer.Option("Standard", "--type", help="Post type (default: Standard)"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Override default status (template sets 'Idea' by default)"),
    template_id: Optional[str] = typer.Option(None, "--template-id", help="Notion template ID (defaults to Standard ATA Tutorial AI-Created Idea)"),
):
    """Create a new article idea in the Notion database.

    Creates a page using the Standard ATA Tutorial AI-Created Idea template with
    the provided title, excerpt, category, and optional keywords.

    Examples:
        ata-blog notion-page create --title "My Post" --excerpt "Desc" --category "IT Ops"
        ata-blog notion-page create --title "My Post" --excerpt "Desc" --category "Cloud" --keywords "azure, cloud" --status "Good Idea"
    """
    try:
        client = get_client()
        result = client.create_article(
            title=title,
            excerpt=excerpt,
            category=category,
            keywords=keywords,
            post_type=post_type,
            status=status,
            template_id=template_id,
        )
        page_id = result.get("id", "").replace("-", "")
        print_success(f"Created article: {page_id}")
        print_json(result)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("publish")
def articles_publish(
    page_id: str = typer.Argument(..., help="Notion page ID to publish"),
    status: str = typer.Option("draft", "--status", "-s", help="WordPress status (draft/publish)"),
    slug: Optional[str] = typer.Option(None, "--slug", help="Custom URL slug (auto-generated if not provided)"),
    date: Optional[str] = typer.Option(None, "--date", "-d", help="Schedule date (ISO 8601)"),
    auto_schedule: bool = typer.Option(False, "--auto-schedule", help="Auto-find next available slot"),
    no_duplicate_check: bool = typer.Option(False, "--no-duplicate-check", help="Skip duplicate slug check"),
    featured_image: Optional[str] = typer.Option(None, "--featured-image", help="Path to featured image file to upload and attach"),
    force: bool = typer.Option(False, "--force", "-F", help="Force republish even if already published"),
):
    """Publish Notion article to WordPress with metadata mapping."""
    try:
        client = get_client()

        print_info(f"Publishing article {page_id}...")
        result = client.publish_article(
            page_id,
            status=status,
            slug=slug,
            date=date,
            auto_schedule=auto_schedule,
            check_duplicates=not no_duplicate_check,
            featured_image=featured_image,
            force=force,
        )

        if result.get("scheduled_date"):
            print_success(f"Scheduled for {result['scheduled_date']} (Post ID: {result['wordpress_post']['id']})")
        else:
            print_success(f"Published to WordPress (Post ID: {result['wordpress_post']['id']})")

        print_info(f"WordPress URL: {result.get('wordpress_url', 'N/A')}")
        print_json(result)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("update")
def articles_update(
    page_id: str = typer.Argument(..., help="Notion page ID"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="New status value"),
    prop: Optional[List[str]] = typer.Option(None, "--property", "-p", help="Property update (Name:value)"),
):
    """Update article properties in Notion.

    Examples:
        ata-blog notion-page update PAGE_ID --status "Draft"
        ata-blog notion-page update PAGE_ID --status "Developmental Review"
        ata-blog notion-page update PAGE_ID --property "Keywords:azure, cloud"
        ata-blog notion-page update PAGE_ID -s "Draft" -p "Dev Review Iterations:2"
    """
    try:
        if not status and not prop:
            raise typer.BadParameter("At least one of --status or --property is required")

        client = get_client()

        # Parse property updates
        properties = {}
        if prop:
            for p in prop:
                if ":" not in p:
                    raise typer.BadParameter(f"Invalid property format '{p}'. Use 'Name:value'")
                name, value = p.split(":", 1)
                properties[name.strip()] = value.strip()

        result = client.update_article(page_id, status=status, properties=properties or None)
        print_success(f"Updated article {page_id}")
        print_json(result)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("search")
def articles_search(
    query: str = typer.Argument(..., help="Search query (searches title)"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum results"),
):
    """Search articles by title.

    Examples:
        ata-blog notion-page search "azure functions"
        ata-blog notion-page search "azure" --status "Draft"
        ata-blog notion-page search "powershell" --table
    """
    try:
        client = get_client()
        articles = client.search_articles(query, status=status, limit=limit)

        if not articles:
            print_info(f"No articles found matching '{query}'")
            return

        if table:
            print_table(articles, ["id", "Title", "Status"], ["ID", "Title", "Status"])
        else:
            print_json(articles)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@app.command("statuses")
def articles_statuses(
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON array"),
):
    """List valid article status values.

    Examples:
        ata-blog notion-page statuses
        ata-blog notion-page statuses --json
    """
    statuses = AtaBlogClient.get_valid_statuses()

    if json_output:
        print_json(statuses)
    else:
        print_info("Valid article statuses:")
        for status in statuses:
            typer.echo(f"  - {status}")


# Content subcommands
@content_app.command("get")
def content_get(
    page_id: str = typer.Argument(..., help="Notion page ID"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file path (default: stdout)"),
):
    """Get article content as markdown.

    Examples:
        ata-blog notion-page content get PAGE_ID
        ata-blog notion-page content get PAGE_ID --output ./post.md
    """
    try:
        client = get_client()
        markdown = client.get_article_markdown(page_id)

        if output:
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Path(output).write_text(markdown)
            print_success(f"Content saved to {output}")
        else:
            sys.stdout.write(markdown)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@content_app.command("set")
def content_set(
    page_id: str = typer.Argument(..., help="Notion page ID"),
    file: str = typer.Option(..., "--file", "-f", help="Markdown file to set as content"),
):
    """Replace article content with markdown from file.

    Local image references (paths that are not http/https URLs) are uploaded
    to the WordPress media library before the markdown is pushed to Notion,
    and the markdown is rewritten to point at the returned WordPress URLs.

    Examples:
        ata-blog notion-page content set PAGE_ID --file ./post.md
    """
    try:
        source_path = Path(file)
        if not source_path.exists():
            raise typer.BadParameter(f"File not found: {file}")

        # Upload local image references to WordPress, rewriting the markdown
        # to point at the returned URLs. Paths are resolved relative to the
        # markdown file's parent directory.
        original_markdown = source_path.read_text()
        rewritten_markdown, uploaded = process_local_images_for_wordpress(
            original_markdown,
            base_dir=source_path.parent,
            verbose=True,
        )

        client = get_client()
        if uploaded > 0:
            # Write transformed markdown to a temp file so the existing client
            # contract (file path in, file path through to notion CLI) is
            # preserved without duplicating the underlying CLI surface.
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".md",
                delete=False,
                encoding="utf-8",
            ) as tmp:
                tmp.write(rewritten_markdown)
                rewritten_path = tmp.name
            try:
                result = client.set_article_content(page_id, rewritten_path)
            finally:
                Path(rewritten_path).unlink(missing_ok=True)
            print_info(f"Uploaded {uploaded} local image(s) to WordPress media.")
        else:
            result = client.set_article_content(page_id, file)

        print_success(f"Content replaced for article {page_id}")
        if result and result != {"success": True}:
            print_json(result)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@content_app.command("append")
def content_append(
    page_id: str = typer.Argument(..., help="Notion page ID"),
    file: str = typer.Option(..., "--file", "-f", help="Markdown file to append"),
):
    """Append markdown content to article.

    Examples:
        ata-blog notion-page content append PAGE_ID --file ./additions.md
    """
    try:
        if not Path(file).exists():
            raise typer.BadParameter(f"File not found: {file}")

        client = get_client()
        result = client.append_article_content(page_id, file)
        print_success(f"Content appended to article {page_id}")
        if result and result != {"success": True}:
            print_json(result)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@comments_app.command("list")
def comments_list(
    page_id: str = typer.Argument(..., help="Notion page ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum comments to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., text:contains:bug)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-P", help="Comma-separated fields to display"),
    no_context: bool = typer.Option(False, "--no-context", help="Exclude parent block context"),
):
    """List comments on a Notion page with context.

    Returns comments with the text they're attached to, useful for
    gathering human review feedback from Notion inline comments.

    Examples:
        ata-blog notion-page comments list PAGE_ID
        ata-blog notion-page comments list PAGE_ID --table
        ata-blog notion-page comments list PAGE_ID --limit 10
        ata-blog notion-page comments list PAGE_ID --filter "text:contains:review"
        ata-blog notion-page comments list PAGE_ID --no-context
    """
    try:
        client = get_client()
        comments = client.get_article_comments(page_id, with_context=not no_context)

        if filter:
            comments = apply_filters(comments, filter)
        comments = apply_limit(comments, limit)

        if not comments:
            print_info("No comments found on this page")
            print_json([])
            return

        if properties:
            comments = apply_properties_filter(comments, properties)

        if table:
            if properties:
                columns = [name.strip() for name in properties.split(",") if name.strip()]
                headers = columns
            else:
                columns = ["context", "text", "created_time"]
                headers = ["Context", "Comment", "Created"]
            print_table(comments, columns, headers)
        else:
            print_json(comments)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@comments_app.command("get")
def comments_get(
    comment_id: str = typer.Argument(..., help="Notion comment ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get a single Notion comment by ID.

    Examples:
        ata-blog notion-page comments get COMMENT_ID
        ata-blog notion-page comments get COMMENT_ID --table
    """
    try:
        client = get_client()
        comment = client.get_article_comment(comment_id)

        if table:
            rows = [{"field": k, "value": str(v)[:60]} for k, v in comment.items() if v]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(comment)
    except Exception as e:
        raise typer.Exit(handle_error(e))


@comments_app.command("add")
def comments_add(
    page_id: str = typer.Argument(..., help="Notion page ID"),
    body: str = typer.Option(..., "--body", "-b", help="Comment body text"),
):
    """Add a comment to a Notion page.

    Posts a top-level comment to the specified page using the same Notion
    authentication as the rest of the `notion-page` subcommands.

    Examples:
        ata-blog notion-page comments add PAGE_ID --body "No affiliate match — needs human review"
        ata-blog notion-page comments add PAGE_ID -b "Quick note from CLI"
    """
    try:
        client = get_client()
        result = client.create_article_comment(page_id, body)
        print_json(result)
    except Exception as e:
        raise typer.Exit(handle_error(e))


# Schema (database property) subcommands
@schema_app.command("add-property")
def schema_add_property(
    database_id: str = typer.Argument(..., help="Notion database ID"),
    name: str = typer.Option(..., "--name", "-n", help="Property (column) name to create"),
    type: str = typer.Option(
        ...,
        "--type",
        "-t",
        help=(
            "Property type. Supported (empty-config types only): "
            "rich_text, url, checkbox, number, date, email, phone_number, files. "
            "(select/multi_select require options and are out of scope for this command.)"
        ),
    ),
):
    """Add a new property (column) to a Notion database schema.

    Delegates to the underlying `notion field add` CLI, which performs the
    PATCH https://api.notion.com/v1/databases/{database_id} call using the
    same Notion authentication path as every other ata-blog notion-page
    subcommand.

    On success, emits a JSON object to stdout:
        {"database_id": "...", "property_name": "...", "type": "...", "created": true}

    Examples:
        ata-blog notion-page schema add-property DB_ID --name "Affiliate Promotion" --type rich_text
        ata-blog notion-page schema add-property DB_ID --name "Source URL" --type url
        ata-blog notion-page schema add-property DB_ID --name "Reviewed" --type checkbox
    """
    if type not in SCHEMA_EMPTY_CONFIG_TYPES:
        supported = ", ".join(SCHEMA_EMPTY_CONFIG_TYPES)
        typer.echo(
            f"Error: --type '{type}' is not supported by this command. "
            f"Supported types: {supported}. "
            f"(select/multi_select require options and are out of scope.)",
            err=True,
        )
        raise typer.Exit(2)

    try:
        # Validate the notion CLI is available via the same path get_client() uses.
        # This raises ClientError if `notion` isn't installed, matching the
        # error surface of every other notion-page subcommand.
        get_client()
    except Exception as e:
        raise typer.Exit(handle_error(e))

    cmd = ["notion", "field", "add", database_id, name, "--type", type]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except subprocess.TimeoutExpired as e:
        typer.echo(f"notion field add timed out after 60s: {e}", err=True)
        raise typer.Exit(1)

    if result.returncode != 0:
        # Notion error body (HTTP error from the underlying PATCH) is
        # printed to stderr exactly as the notion CLI reported it.
        err = result.stderr.strip() or result.stdout.strip() or "unknown error"
        typer.echo(err, err=True)
        raise typer.Exit(result.returncode or 1)

    print_json(
        {
            "database_id": database_id,
            "property_name": name,
            "type": type,
            "created": True,
        }
    )
