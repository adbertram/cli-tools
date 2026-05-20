"""Schema markup commands for ATA Blog CLI.

Manages Rank Math schema via WordPress REST API.
"""
import json
import subprocess
import typer
from typing import Optional, List
from enum import Enum

from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import print_json, print_table

COMMAND_CREDENTIALS = {
    "list": ["custom"],
    "types": ["custom"],
    "set": ["custom"],
    "get": ["custom"],
    "remove": ["custom"],
}

app = typer.Typer(help="Manage Rank Math schema markup for WordPress posts")


class SchemaType(str, Enum):
    """Supported schema types."""
    ARTICLE = "Article"
    TECH_ARTICLE = "TechArticle"
    REVIEW = "Review"


class ProficiencyLevel(str, Enum):
    """Proficiency levels for TechArticle schema."""
    BEGINNER = "Beginner"
    INTERMEDIATE = "Intermediate"
    EXPERT = "Expert"


def _build_schema_json(
    schema_type: SchemaType,
    proficiency: Optional[ProficiencyLevel] = None,
    rating: Optional[float] = None,
    item_reviewed: Optional[str] = None,
    dependencies: Optional[str] = None,
) -> str:
    """Build Rank Math schema JSON structure."""

    # Base schema structure that Rank Math expects
    schema = {
        "@type": schema_type.value,
        "metadata": {
            "title": "%seo_title%",
            "description": "%seo_description%",
            "author": {
                "@type": "Person"
            }
        }
    }

    # Add type-specific properties
    if schema_type == SchemaType.TECH_ARTICLE:
        if proficiency:
            schema["proficiencyLevel"] = proficiency.value
        if dependencies:
            schema["dependencies"] = dependencies

    elif schema_type == SchemaType.REVIEW:
        if rating is not None:
            schema["reviewRating"] = {
                "@type": "Rating",
                "ratingValue": str(rating),
                "bestRating": "5",
                "worstRating": "1"
            }
        if item_reviewed:
            schema["itemReviewed"] = {
                "@type": "Thing",
                "name": item_reviewed
            }

    # Rank Math expects an array of schema objects
    return json.dumps([schema])


def _run_wordpress(args: list) -> subprocess.CompletedProcess:
    """Run a wordpress CLI command."""
    cmd = ["wordpress"] + args
    return subprocess.run(cmd, capture_output=True, text=True)


@app.command("list")
def list_schemas(
    limit: int = typer.Option(50, "--limit", "-l", help="Maximum posts to check"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
):
    """List WordPress posts with their schema configurations.

    Examples:
        ata-blog schema list --table
        ata-blog schema list --limit 100
        ata-blog schema list --filter schema_type:eq:TechArticle
    """
    # Get recent posts
    result = _run_wordpress(["posts", "list", "--limit", str(limit)])

    if result.returncode != 0:
        typer.echo(f"Error listing posts: {result.stderr}", err=True)
        raise typer.Exit(result.returncode)

    try:
        posts = json.loads(result.stdout)
    except json.JSONDecodeError:
        typer.echo("Error parsing posts data", err=True)
        raise typer.Exit(1)

    # Extract schema info for each post
    schemas_data = []
    for post in posts:
        meta = post.get("meta", {})
        schema_raw = meta.get("rank_math_schemas") or meta.get("rank_math_schema")

        schema_type = "None"
        if schema_raw:
            try:
                if isinstance(schema_raw, str):
                    schemas = json.loads(schema_raw)
                else:
                    schemas = schema_raw
                if schemas and isinstance(schemas, list) and len(schemas) > 0:
                    schema_type = schemas[0].get("@type", "Unknown")
            except (json.JSONDecodeError, TypeError):
                schema_type = "Invalid"

        schemas_data.append({
            "id": post.get("id"),
            "title": post.get("title", {}).get("rendered", "")[:50] if isinstance(post.get("title"), dict) else str(post.get("title", ""))[:50],
            "schema_type": schema_type,
        })

    # Apply client-side filtering
    schemas_data = apply_filters(schemas_data, filter)

    # Apply property filtering if specified
    if properties:
        prop_list = [p.strip() for p in properties.split(",")]
        schemas_data = [{k: v for k, v in item.items() if k in prop_list} for item in schemas_data]

    if table:
        columns = prop_list if properties else ["id", "title", "schema_type"]
        headers = [c.replace("_", " ").title() for c in columns]
        print_table(schemas_data, columns, headers)
    else:
        print_json(schemas_data)


@app.command("types")
def list_types():
    """List available schema types."""
    typer.echo("Available schema types for ATA Blog:\n")

    typer.echo("Primary Types:")
    typer.echo("  Article       - General blog posts, news, opinion pieces")
    typer.echo("  TechArticle   - Technical tutorials, how-to guides, documentation")
    typer.echo("  Review        - Product or service reviews (supports ratings)")
    typer.echo("")
    typer.echo("Secondary Types (auto-detected):")
    typer.echo("  FAQPage       - FAQ sections within posts")
    typer.echo("  VideoObject   - Embedded video content")
    typer.echo("")
    typer.echo("Proficiency Levels (for TechArticle):")
    typer.echo("  Beginner      - Basic concepts, getting started")
    typer.echo("  Intermediate  - Best practices, implementation")
    typer.echo("  Expert        - Advanced topics, deep dives")


@app.command("set")
def set_schema(
    post_id: int = typer.Argument(..., help="WordPress post ID"),
    schema_type: SchemaType = typer.Argument(..., help="Schema type (Article, TechArticle, Review)"),
    proficiency: Optional[ProficiencyLevel] = typer.Option(
        None, "--proficiency", "-p",
        help="Proficiency level for TechArticle (Beginner, Intermediate, Expert)"
    ),
    rating: Optional[float] = typer.Option(
        None, "--rating", "-r",
        help="Rating value 1-5 for Review schema"
    ),
    item_reviewed: Optional[str] = typer.Option(
        None, "--item", "-i",
        help="Name of item being reviewed for Review schema"
    ),
    dependencies: Optional[str] = typer.Option(
        None, "--dependencies", "-d",
        help="Prerequisites/dependencies for TechArticle"
    ),
):
    """Set Rank Math schema on a WordPress post.

    Examples:
        ata-blog schema set 123 TechArticle --proficiency Intermediate
        ata-blog schema set 456 Review --rating 4.5 --item "Azure DevOps"
        ata-blog schema set 789 Article
    """
    # Validate type-specific options
    if schema_type == SchemaType.TECH_ARTICLE and not proficiency:
        proficiency = ProficiencyLevel.INTERMEDIATE  # Default

    if schema_type == SchemaType.REVIEW:
        if rating is not None and (rating < 1 or rating > 5):
            typer.echo("Error: Rating must be between 1 and 5", err=True)
            raise typer.Exit(1)

    # Build schema JSON
    schema_json = _build_schema_json(
        schema_type=schema_type,
        proficiency=proficiency,
        rating=rating,
        item_reviewed=item_reviewed,
        dependencies=dependencies,
    )

    # Update post via wordpress CLI
    # Rank Math uses 'rank_math_schemas' meta key (note the 's')
    result = _run_wordpress([
        "posts", "update", str(post_id),
        "--meta", f"rank_math_schemas={schema_json}"
    ])

    if result.returncode != 0:
        typer.echo(f"Error setting schema: {result.stderr}", err=True)
        raise typer.Exit(result.returncode)

    typer.echo(f"Schema set successfully on post {post_id}")
    typer.echo(f"  Type: {schema_type.value}")
    if proficiency:
        typer.echo(f"  Proficiency: {proficiency.value}")
    if rating:
        typer.echo(f"  Rating: {rating}/5")
    if item_reviewed:
        typer.echo(f"  Item Reviewed: {item_reviewed}")


@app.command("get")
def get_schema(
    post_id: int = typer.Argument(..., help="WordPress post ID"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get current schema configuration for a WordPress post."""
    # Get post with meta
    result = _run_wordpress(["posts", "get", str(post_id)])

    if result.returncode != 0:
        typer.echo(f"Error getting post: {result.stderr}", err=True)
        raise typer.Exit(result.returncode)

    try:
        post = json.loads(result.stdout)
    except json.JSONDecodeError:
        typer.echo("Error parsing post data", err=True)
        raise typer.Exit(1)

    # Extract schema from meta
    meta = post.get("meta", {})
    schema_data = meta.get("rank_math_schemas") or meta.get("rank_math_schema")

    if not schema_data:
        print_json({"post_id": post_id, "schemas": []})
        raise typer.Exit(0)

    # Parse schema JSON
    try:
        if isinstance(schema_data, str):
            schemas = json.loads(schema_data)
        else:
            schemas = schema_data
    except json.JSONDecodeError:
        typer.echo(f"Error parsing schema data: {schema_data}", err=True)
        raise typer.Exit(1)

    if json_output:
        typer.echo(json.dumps(schemas, indent=2))
    elif table:
        # Build table data
        table_data = []
        for schema in (schemas if isinstance(schemas, list) else [schemas]):
            schema_type = schema.get("@type", "Unknown")
            row = {"type": schema_type, "proficiency": "", "rating": "", "item": ""}
            if schema_type == "TechArticle":
                row["proficiency"] = schema.get("proficiencyLevel", "")
            elif schema_type == "Review":
                rating_obj = schema.get("reviewRating", {})
                row["rating"] = rating_obj.get("ratingValue", "")
                item = schema.get("itemReviewed", {})
                row["item"] = item.get("name", "") if item else ""
            table_data.append(row)
        print_table(table_data, ["type", "proficiency", "rating", "item"], ["Type", "Proficiency", "Rating", "Item"])
    else:
        typer.echo(f"Schema for post {post_id}:\n")
        for i, schema in enumerate(schemas if isinstance(schemas, list) else [schemas]):
            schema_type = schema.get("@type", "Unknown")
            typer.echo(f"  [{i+1}] Type: {schema_type}")

            if schema_type == "TechArticle":
                level = schema.get("proficiencyLevel", "Not set")
                typer.echo(f"      Proficiency: {level}")
                deps = schema.get("dependencies")
                if deps:
                    typer.echo(f"      Dependencies: {deps}")

            elif schema_type == "Review":
                rating_obj = schema.get("reviewRating", {})
                rating = rating_obj.get("ratingValue", "Not set")
                typer.echo(f"      Rating: {rating}/5")
                item = schema.get("itemReviewed", {})
                if item:
                    typer.echo(f"      Item: {item.get('name', 'Unknown')}")


@app.command("remove")
def remove_schema(
    post_id: int = typer.Argument(..., help="WordPress post ID"),
):
    """Remove Rank Math schema from a WordPress post."""
    # Set empty schema
    result = _run_wordpress([
        "posts", "update", str(post_id),
        "--meta", "rank_math_schemas="
    ])

    if result.returncode != 0:
        typer.echo(f"Error removing schema: {result.stderr}", err=True)
        raise typer.Exit(result.returncode)

    typer.echo(f"Schema removed from post {post_id}")
