"""Notion commands for ATA Blog CLI."""
import sys
from pathlib import Path
import typer
from typing import Optional, List

from ..client import get_client
from cli_tools_shared.output import print_json, print_table, command, print_success, print_info
from cli_tools_shared import FilterMap

# Filter map for translating CLI arguments to filter strings
_filter_map = FilterMap().add_argument_mapping("status", "Status", "in")

app = typer.Typer(help="Manage Notion pages")
content_app = typer.Typer(help="Manage article content")
app.add_typer(content_app, name="content")


@app.command("list")
@command
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

    if table:
        columns = ["id", "Title", "Status", "Author"]
        headers = ["ID", "Title", "Status", "Author"]
        if properties:
            columns = [p.strip() for p in properties.split(",")]
            headers = columns
        print_table(articles, columns, headers)
    else:
        print_json(articles)


@app.command("get")
@command
def articles_get(
    page_id: str = typer.Argument(..., help="Notion page ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get article details from Notion."""
    client = get_client()
    article = client.get_article(page_id)

    if table:
        rows = [{"field": k, "value": str(v)[:60]} for k, v in article.items() if v]
        print_table(rows, ["field", "value"], ["Field", "Value"])
    else:
        print_json(article)


@app.command("publish")
@command
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


@app.command("update")
@command
def articles_update(
    page_id: str = typer.Argument(..., help="Notion page ID"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="New status value"),
    prop: Optional[List[str]] = typer.Option(None, "--property", "-p", help="Property update (Name:value)"),
):
    """Update article properties in Notion.

    Property types are read from the live Notion database schema, so each value
    is sent with the correct typed payload. An empty value clears the property
    (url/email/number/select/date -> null, rich_text/multi_select/relation ->
    empty). Checkbox properties accept true/false/yes/no/1/0 (case-insensitive)
    and are rejected if ambiguous.

    Examples:
        ata-blog notion-page update PAGE_ID --status "Draft"
        ata-blog notion-page update PAGE_ID --status "Developmental Review"
        ata-blog notion-page update PAGE_ID --property "Keywords:azure, cloud"
        ata-blog notion-page update PAGE_ID -s "Draft" -p "Dev Review Iterations:2"
        ata-blog notion-page update PAGE_ID -p "Promoted:true"
        ata-blog notion-page update PAGE_ID -p "Published URL:" -p "Promoted:false"
    """
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


@app.command("search")
@command
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
    client = get_client()
    articles = client.search_articles(query, status=status, limit=limit)

    if not articles:
        print_info(f"No articles found matching '{query}'")
        return

    if table:
        print_table(articles, ["id", "Title", "Status"], ["ID", "Title", "Status"])
    else:
        print_json(articles)


@app.command("statuses")
@command
def articles_statuses(
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON array"),
):
    """List valid article status values.

    Examples:
        ata-blog notion-page statuses
        ata-blog notion-page statuses --json
    """
    statuses = get_client().get_valid_statuses()

    if json_output:
        print_json(statuses)
    else:
        print_info("Valid article statuses:")
        for status in statuses:
            typer.echo(f"  - {status}")


# Content subcommands
@content_app.command("get")
@command
def content_get(
    page_id: str = typer.Argument(..., help="Notion page ID"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output file path (default: stdout)"),
):
    """Get article content as markdown.

    Examples:
        ata-blog notion-page content get PAGE_ID
        ata-blog notion-page content get PAGE_ID --output ./post.md
    """
    client = get_client()
    markdown = client.get_article_markdown(page_id)

    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(markdown)
        print_success(f"Content saved to {output}")
    else:
        sys.stdout.write(markdown)


@content_app.command("set")
@command
def content_set(
    page_id: str = typer.Argument(..., help="Notion page ID"),
    file: str = typer.Option(..., "--file", "-f", help="Markdown file to set as content"),
):
    """Replace article content with markdown from file.

    Examples:
        ata-blog notion-page content set PAGE_ID --file ./post.md
    """
    if not Path(file).exists():
        raise typer.BadParameter(f"File not found: {file}")

    client = get_client()
    result = client.set_article_content(page_id, file)
    print_success(f"Content replaced for article {page_id}")
    if result and result != {"success": True}:
        print_json(result)


@content_app.command("append")
@command
def content_append(
    page_id: str = typer.Argument(..., help="Notion page ID"),
    file: str = typer.Option(..., "--file", "-f", help="Markdown file to append"),
):
    """Append markdown content to article.

    Examples:
        ata-blog notion-page content append PAGE_ID --file ./additions.md
    """
    if not Path(file).exists():
        raise typer.BadParameter(f"File not found: {file}")

    client = get_client()
    result = client.append_article_content(page_id, file)
    print_success(f"Content appended to article {page_id}")
    if result and result != {"success": True}:
        print_json(result)


@app.command("comments")
@command
def article_comments(
    page_id: str = typer.Argument(..., help="Notion page ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    no_context: bool = typer.Option(False, "--no-context", help="Exclude parent block context"),
):
    """Get comments on an article page with context.

    Returns comments with the text they're attached to, useful for
    gathering human review feedback from Notion inline comments.

    Examples:
        ata-blog notion-page comments PAGE_ID
        ata-blog notion-page comments PAGE_ID --table
        ata-blog notion-page comments PAGE_ID --no-context
    """
    client = get_client()
    comments = client.get_article_comments(page_id, with_context=not no_context)

    if not comments:
        print_info("No comments found on this page")
        print_json([])
        return

    if table:
        columns = ["context", "text", "created_time"]
        headers = ["Context", "Comment", "Created"]
        print_table(comments, columns, headers)
    else:
        print_json(comments)
