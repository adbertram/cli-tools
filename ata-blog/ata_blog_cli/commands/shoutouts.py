"""Shoutout commands for ATA Blog CLI.

Manages sponsored content blocks (shoutouts) in WordPress posts.
Supports both Classic Editor HTML and Gutenberg block formats.
"""
import json
import os
import re
import subprocess
from typing import Optional, List, Tuple
from pathlib import Path
from urllib.parse import urlparse

import typer

from cli_tools_shared.filters import apply_filters
from cli_tools_shared.output import print_json, print_table

COMMAND_CREDENTIALS = {
    "list": ["custom"],
    "get": ["custom"],
    "add": ["custom"],
    "remove": ["custom"],
}

app = typer.Typer(help="Manage sponsored shoutouts in WordPress posts")

SPONSORED_TAG_ID = "7"
SPONSORED_POST_SCAN_LIMIT = 1000


# =============================================================================
# Format Detection
# =============================================================================

def _is_gutenberg(content: str) -> bool:
    """Detect if content uses Gutenberg blocks.

    Args:
        content: Post content

    Returns:
        True if content contains Gutenberg block comments
    """
    return bool(re.search(r'<!-- wp:[a-z]', content))


# =============================================================================
# Gutenberg Block Patterns
# =============================================================================

# WordPress block pattern for shoutouts (wp:quote with sponsored link)
GUTENBERG_SHOUTOUT_PATTERN = re.compile(
    r'<!-- wp:quote -->([\s\S]*?)<!-- /wp:quote -->',
    re.MULTILINE
)

# Content blocks for Gutenberg
GUTENBERG_BLOCK_PATTERNS = [
    re.compile(r'<!-- wp:paragraph -->'),
    re.compile(r'<!-- wp:html -->'),
    re.compile(r'<!-- wp:heading[^>]*-->'),
    re.compile(r'<!-- wp:table[^>]*-->'),
    re.compile(r'<!-- wp:list[^>]*-->'),
    re.compile(r'<!-- wp:code[^>]*-->'),
    re.compile(r'<!-- wp:preformatted[^>]*-->'),
    re.compile(r'<!-- wp:separator[^>]*-->'),
]

# Template for new Gutenberg shoutouts
GUTENBERG_SHOUTOUT_TEMPLATE = """<!-- wp:quote -->
<blockquote class="wp-block-quote"><!-- wp:paragraph -->
<p>{text}<br></p>
<!-- /wp:paragraph --></blockquote>
<!-- /wp:quote -->"""


# =============================================================================
# Classic HTML Patterns
# =============================================================================

# Classic shoutout: <blockquote> with sponsored link
CLASSIC_SHOUTOUT_PATTERN = re.compile(
    r'<blockquote[^>]*>([\s\S]*?)</blockquote>',
    re.MULTILINE | re.IGNORECASE
)

# Content elements for Classic HTML (order matters for matching)
# We match opening tags and find their corresponding closing tags
CLASSIC_CONTENT_TAGS = ['p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'table', 'pre', 'ol', 'ul', 'hr']

# Template for new Classic shoutouts
CLASSIC_SHOUTOUT_TEMPLATE = """<blockquote>
<p><em>{text}</em></p>
</blockquote>"""


# =============================================================================
# Common Patterns
# =============================================================================

# Pattern to detect sponsored links
SPONSORED_LINK_PATTERN = re.compile(
    r'<a[^>]*rel="[^"]*sponsored[^"]*"[^>]*>',
    re.IGNORECASE
)

LINK_HREF_PATTERN = re.compile(
    r'<a[^>]+href=["\']([^"\']+)["\']',
    re.IGNORECASE
)


def _normalize_domain(domain: str) -> str:
    value = domain.strip().lower()
    if value.startswith("http://"):
        value = value[7:]
    if value.startswith("https://"):
        value = value[8:]
    value = value.split("/", 1)[0]
    if value.startswith("www."):
        value = value[4:]
    return value.rstrip(".")


def _sponsors_file_path() -> Path:
    configured = os.environ.get("ATABLOGGER_SPONSORS_FILE")
    if not configured:
        raise ValueError("ATABLOGGER_SPONSORS_FILE must point to sponsors.json")
    return Path(configured)


def _load_sponsors() -> List[dict]:
    path = _sponsors_file_path()
    if not path.exists():
        raise ValueError(f"Sponsor registry not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    sponsors = data.get("sponsors")
    if not isinstance(sponsors, list):
        raise ValueError("Sponsor registry must contain a sponsors array")
    return sponsors


def _resolve_sponsor_domains(name: str) -> List[str]:
    matches = [sponsor for sponsor in _load_sponsors() if sponsor.get("name") == name]
    if len(matches) > 1:
        raise ValueError(f"Duplicate sponsor name in registry: {name}")
    if not matches:
        raise ValueError(f"Unknown sponsor: {name}")
    domains = matches[0].get("domains")
    if not isinstance(domains, list) or not domains:
        raise ValueError(f"Sponsor has no domains: {name}")
    normalized = [_normalize_domain(str(domain)) for domain in domains]
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"Sponsor has duplicate domains: {name}")
    return normalized


def _html_matches_domains(html: str, domains: List[str]) -> bool:
    for href in LINK_HREF_PATTERN.findall(html):
        host = _normalize_domain(urlparse(href).netloc or href)
        if any(host == domain or host.endswith(f".{domain}") for domain in domains):
            return True
    return False


def _run_wordpress(args: list) -> subprocess.CompletedProcess:
    """Run a wordpress CLI command."""
    cmd = ["wordpress"] + args
    return subprocess.run(cmd, capture_output=True, text=True)


def _run_wordpress_json(args: list):
    result = _run_wordpress(args)
    if result.returncode != 0:
        typer.echo(f"Error running wordpress: {result.stderr}", err=True)
        raise typer.Exit(result.returncode)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        typer.echo("Error parsing WordPress response", err=True)
        raise typer.Exit(1)


def _resolve_post_id(post_id_or_slug: str) -> int:
    """Resolve a post slug to its ID, or validate and return a numeric ID.

    Args:
        post_id_or_slug: Either a numeric post ID or a post slug

    Returns:
        The numeric post ID

    Raises:
        typer.Exit: If the post cannot be found
    """
    # Check if it's already a numeric ID
    if post_id_or_slug.isdigit():
        return int(post_id_or_slug)

    # It's a slug - search for the post using filter
    result = _run_wordpress([
        "posts", "list",
        "--filter", f"slug:eq:{post_id_or_slug}",
        "--properties", "id,slug"
    ])

    if result.returncode != 0:
        typer.echo(f"Error finding post by slug: {result.stderr}", err=True)
        raise typer.Exit(result.returncode)

    try:
        posts = json.loads(result.stdout)
    except json.JSONDecodeError:
        typer.echo("Error parsing posts response", err=True)
        raise typer.Exit(1)

    # Filter is client-side, so we need to find the exact match
    matching = [p for p in posts if p.get("slug") == post_id_or_slug]

    if not matching:
        typer.echo(f"No post found with slug: {post_id_or_slug}", err=True)
        raise typer.Exit(1)

    return matching[0].get("id")


def _get_post_content(post_id: int) -> str:
    """Fetch raw post content from WordPress.

    Args:
        post_id: WordPress post ID

    Returns:
        Raw post content (HTML/Gutenberg blocks)

    Raises:
        typer.Exit: If the post cannot be fetched
    """
    # Use --raw to get Gutenberg blocks if present
    result = _run_wordpress(["posts", "get", str(post_id), "--raw"])

    if result.returncode != 0:
        typer.echo(f"Error getting post: {result.stderr}", err=True)
        raise typer.Exit(result.returncode)

    try:
        post = json.loads(result.stdout)
    except json.JSONDecodeError:
        typer.echo("Error parsing post data", err=True)
        raise typer.Exit(1)

    content = post.get("content", "")
    if isinstance(content, dict):
        content = content.get("raw", content.get("rendered", ""))
    return str(content)


def _update_post_content(post_id: int, content: str) -> None:
    """Update post content in WordPress.

    Args:
        post_id: WordPress post ID
        content: New raw content

    Raises:
        typer.Exit: If the update fails
    """
    result = _run_wordpress([
        "posts", "update", str(post_id),
        "--content", content
    ])

    if result.returncode != 0:
        typer.echo(f"Error updating post: {result.stderr}", err=True)
        raise typer.Exit(result.returncode)


def _has_sponsored_link(content: str) -> bool:
    """Check if content contains a sponsored link.

    Args:
        content: HTML content

    Returns:
        True if content contains a sponsored link
    """
    return bool(SPONSORED_LINK_PATTERN.search(content))


# =============================================================================
# Gutenberg Functions
# =============================================================================

def _find_gutenberg_shoutouts(content: str) -> List[dict]:
    """Find all shoutouts in Gutenberg content.

    Args:
        content: Post content with Gutenberg blocks

    Returns:
        List of dicts with 'match', 'start', 'end', 'inner' keys
    """
    shoutouts = []

    for match in GUTENBERG_SHOUTOUT_PATTERN.finditer(content):
        inner_content = match.group(1)
        if _has_sponsored_link(inner_content):
            shoutouts.append({
                'match': match.group(0),
                'start': match.start(),
                'end': match.end(),
                'inner': inner_content,
            })

    return shoutouts


def _count_gutenberg_blocks_before(content: str, position: int) -> int:
    """Count Gutenberg content blocks before a character position.

    Args:
        content: Post content
        position: Character position

    Returns:
        Number of content blocks before position
    """
    content_before = content[:position]
    count = 0

    for pattern in GUTENBERG_BLOCK_PATTERNS:
        count += len(pattern.findall(content_before))

    # Count non-shoutout quote blocks
    for match in GUTENBERG_SHOUTOUT_PATTERN.finditer(content_before):
        if not _has_sponsored_link(match.group(1)):
            count += 1

    return count


def _get_total_gutenberg_blocks(content: str) -> int:
    """Get total Gutenberg content blocks.

    Args:
        content: Post content

    Returns:
        Total block count
    """
    count = 0

    for pattern in GUTENBERG_BLOCK_PATTERNS:
        count += len(pattern.findall(content))

    # Count non-shoutout quote blocks
    for match in GUTENBERG_SHOUTOUT_PATTERN.finditer(content):
        if not _has_sponsored_link(match.group(1)):
            count += 1

    return count


def _find_gutenberg_insertion_point(content: str, position: int) -> int:
    """Find insertion point after Nth Gutenberg block.

    Args:
        content: Post content
        position: Block number to insert after

    Returns:
        Character position for insertion
    """
    block_positions = []

    for pattern in GUTENBERG_BLOCK_PATTERNS:
        for match in pattern.finditer(content):
            block_positions.append(match.start())

    # Add non-shoutout quote blocks
    for match in GUTENBERG_SHOUTOUT_PATTERN.finditer(content):
        if not _has_sponsored_link(match.group(1)):
            block_positions.append(match.start())

    block_positions.sort()

    if position <= 0 or position > len(block_positions):
        raise ValueError(f"Invalid position {position}. Must be 1-{len(block_positions)}")

    nth_block_start = block_positions[position - 1]
    remaining = content[nth_block_start:]

    # Find end of block based on type
    block_endings = [
        ('<!-- wp:paragraph -->', r'<!-- /wp:paragraph -->'),
        ('<!-- wp:html -->', r'<!-- /wp:html -->'),
        ('<!-- wp:heading', r'<!-- /wp:heading -->'),
        ('<!-- wp:table', r'<!-- /wp:table -->'),
        ('<!-- wp:list', r'<!-- /wp:list -->'),
        ('<!-- wp:code', r'<!-- /wp:code -->'),
        ('<!-- wp:preformatted', r'<!-- /wp:preformatted -->'),
        ('<!-- wp:separator', r'<!-- /wp:separator -->'),
        ('<!-- wp:quote -->', r'<!-- /wp:quote -->'),
    ]

    for start_pattern, end_pattern in block_endings:
        if remaining.startswith(start_pattern):
            end_match = re.search(end_pattern, remaining)
            if end_match:
                return nth_block_start + end_match.end()

    return nth_block_start


# =============================================================================
# Classic HTML Functions
# =============================================================================

def _find_classic_shoutouts(content: str) -> List[dict]:
    """Find all shoutouts in Classic HTML content.

    Args:
        content: Post content (Classic HTML)

    Returns:
        List of dicts with 'match', 'start', 'end', 'inner' keys
    """
    shoutouts = []

    for match in CLASSIC_SHOUTOUT_PATTERN.finditer(content):
        inner_content = match.group(1)
        if _has_sponsored_link(inner_content):
            shoutouts.append({
                'match': match.group(0),
                'start': match.start(),
                'end': match.end(),
                'inner': inner_content,
            })

    return shoutouts


def _find_classic_content_blocks(content: str) -> List[Tuple[int, int]]:
    """Find all Classic HTML content blocks with their positions.

    Args:
        content: Post content

    Returns:
        List of (start, end) tuples sorted by start position
    """
    blocks = []

    for tag in CLASSIC_CONTENT_TAGS:
        if tag == 'hr':
            # Self-closing tag
            for match in re.finditer(r'<hr\s*/?>', content, re.IGNORECASE):
                blocks.append((match.start(), match.end()))
        else:
            # Opening/closing tag pairs
            pattern = re.compile(
                rf'<{tag}[^>]*>[\s\S]*?</{tag}>',
                re.IGNORECASE
            )
            for match in pattern.finditer(content):
                # Skip blockquotes with sponsored links (those are shoutouts)
                if tag == 'blockquote' or (tag == 'p' and '<blockquote' in match.group(0)):
                    continue
                blocks.append((match.start(), match.end()))

    # Sort by start position
    blocks.sort(key=lambda x: x[0])

    # Remove overlapping blocks (keep outer blocks)
    filtered = []
    for start, end in blocks:
        # Check if this block is inside any existing block
        is_nested = False
        for f_start, f_end in filtered:
            if start > f_start and end < f_end:
                is_nested = True
                break
        if not is_nested:
            # Remove any existing blocks that are inside this one
            filtered = [(s, e) for s, e in filtered if not (s > start and e < end)]
            filtered.append((start, end))

    filtered.sort(key=lambda x: x[0])
    return filtered


def _count_classic_blocks_before(content: str, position: int) -> int:
    """Count Classic HTML content blocks before a character position.

    Args:
        content: Post content
        position: Character position

    Returns:
        Number of blocks before position
    """
    blocks = _find_classic_content_blocks(content)
    count = 0
    for start, end in blocks:
        if end <= position:
            count += 1
        else:
            break
    return count


def _get_total_classic_blocks(content: str) -> int:
    """Get total Classic HTML content blocks.

    Args:
        content: Post content

    Returns:
        Total block count
    """
    return len(_find_classic_content_blocks(content))


def _find_classic_insertion_point(content: str, position: int) -> int:
    """Find insertion point after Nth Classic HTML block.

    Args:
        content: Post content
        position: Block number to insert after

    Returns:
        Character position for insertion
    """
    blocks = _find_classic_content_blocks(content)

    if position <= 0 or position > len(blocks):
        raise ValueError(f"Invalid position {position}. Must be 1-{len(blocks)}")

    # Return end of the Nth block
    return blocks[position - 1][1]


# =============================================================================
# Unified Functions (dispatch based on format)
# =============================================================================

def _find_shoutouts(content: str) -> List[dict]:
    """Find all shoutouts in content (auto-detect format).

    Args:
        content: Post content

    Returns:
        List of shoutout dicts
    """
    if _is_gutenberg(content):
        return _find_gutenberg_shoutouts(content)
    return _find_classic_shoutouts(content)


def _count_blocks_before(content: str, position: int) -> int:
    """Count content blocks before a position (auto-detect format).

    Args:
        content: Post content
        position: Character position

    Returns:
        Block count
    """
    if _is_gutenberg(content):
        return _count_gutenberg_blocks_before(content, position)
    return _count_classic_blocks_before(content, position)


def _get_total_blocks(content: str) -> int:
    """Get total content blocks (auto-detect format).

    Args:
        content: Post content

    Returns:
        Total block count
    """
    if _is_gutenberg(content):
        return _get_total_gutenberg_blocks(content)
    return _get_total_classic_blocks(content)


def _find_insertion_point(content: str, position: int) -> int:
    """Find insertion point after Nth block (auto-detect format).

    Args:
        content: Post content
        position: Block number

    Returns:
        Character position
    """
    if _is_gutenberg(content):
        return _find_gutenberg_insertion_point(content, position)
    return _find_classic_insertion_point(content, position)


def _get_shoutout_template(content: str) -> str:
    """Get appropriate shoutout template (auto-detect format).

    Args:
        content: Post content

    Returns:
        Template string with {text} placeholder
    """
    if _is_gutenberg(content):
        return GUTENBERG_SHOUTOUT_TEMPLATE
    return CLASSIC_SHOUTOUT_TEMPLATE


def _calculate_shoutout_positions(content: str) -> List[dict]:
    """Calculate positions for all shoutouts.

    Args:
        content: Post content

    Returns:
        List of shoutout dicts with 'position' added
    """
    shoutouts = _find_shoutouts(content)

    for shoutout in shoutouts:
        shoutout['position'] = _count_blocks_before(content, shoutout['start'])

    return shoutouts


def _shoutout_rows(content: str) -> List[dict]:
    rows = []
    for idx, shoutout in enumerate(_calculate_shoutout_positions(content)):
        rows.append({
            "index": idx + 1,
            "position": shoutout['position'],
            "preview": _extract_preview(shoutout['inner']),
            "full_html": shoutout['match'],
        })
    return rows


def _list_sponsored_posts() -> List[dict]:
    posts = _run_wordpress_json([
        "posts",
        "list",
        "--limit",
        str(SPONSORED_POST_SCAN_LIMIT),
        "--filter",
        f"tags:eq:{SPONSORED_TAG_ID}",
        "--properties",
        "id,slug,title,date,link",
    ])
    if not isinstance(posts, list):
        typer.echo("Error: WordPress posts list did not return an array", err=True)
        raise typer.Exit(1)
    return posts


def _list_shoutouts_for_sponsor(sponsor: str) -> List[dict]:
    try:
        domains = _resolve_sponsor_domains(sponsor)
    except ValueError as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1)

    rows = []
    for post in _list_sponsored_posts():
        post_id = post.get("id")
        content = _get_post_content(int(post_id))
        for row in _shoutout_rows(content):
            if _html_matches_domains(row["full_html"], domains):
                rows.append({
                    "post_id": post_id,
                    "slug": post.get("slug"),
                    "title": post.get("title"),
                    "date": post.get("date"),
                    "link": post.get("link"),
                    **row,
                })
    return rows


# =============================================================================
# Helper Functions
# =============================================================================

def _process_links(html: str) -> str:
    """Add rel="noreferrer noopener sponsored" to all <a> tags.

    Args:
        html: HTML content

    Returns:
        HTML with sponsored rel attributes on all links
    """
    def add_sponsored_rel(match):
        tag = match.group(0)

        rel_match = re.search(r'rel="([^"]*)"', tag)

        if rel_match:
            rel_value = rel_match.group(1)
            if 'sponsored' not in rel_value:
                new_rel = f'{rel_value} sponsored'.strip()
                if 'noreferrer' not in new_rel:
                    new_rel = f'noreferrer noopener {new_rel}'
                tag = tag.replace(f'rel="{rel_value}"', f'rel="{new_rel}"')
        else:
            tag = tag[:-1] + ' rel="noreferrer noopener sponsored">'

        return tag

    return re.sub(r'<a\s[^>]*>', add_sponsored_rel, html)


def _validate_insertion_position(content: str, position: int, existing_shoutouts: List[dict]) -> None:
    """Validate that a shoutout can be inserted at the given position.

    Args:
        content: Post content
        position: Proposed insertion position
        existing_shoutouts: List of existing shoutouts with positions

    Raises:
        typer.Exit: If position is invalid
    """
    total_blocks = _get_total_blocks(content)

    if position < 1:
        typer.echo("Error: Position must be at least 1", err=True)
        raise typer.Exit(1)

    if position > total_blocks:
        typer.echo(f"Error: Position {position} exceeds total content blocks ({total_blocks})", err=True)
        raise typer.Exit(1)

    # Check for adjacent shoutouts (minimum 1 block gap)
    for shoutout in existing_shoutouts:
        existing_pos = shoutout['position']
        if abs(position - existing_pos) < 2:
            typer.echo(
                f"Error: Position {position} is too close to existing shoutout at position {existing_pos}. "
                f"Minimum 1 content block gap required.",
                err=True
            )
            raise typer.Exit(1)


def _extract_preview(shoutout_html: str, max_length: int = 80) -> str:
    """Extract preview text from shoutout HTML.

    Args:
        shoutout_html: Full shoutout HTML
        max_length: Maximum preview length

    Returns:
        Plain text preview
    """
    text = re.sub(r'<[^>]+>', '', shoutout_html)
    text = re.sub(r'<!--[^>]+-->', '', text)
    text = ' '.join(text.split())

    if len(text) > max_length:
        return text[:max_length] + "..."
    return text


# =============================================================================
# Commands
# =============================================================================

@app.command("list")
def list_shoutouts(
    post: Optional[str] = typer.Argument(None, help="WordPress post ID or slug"),
    sponsor: Optional[str] = typer.Option(None, "--sponsor", help="Sponsor name from ATABlogger config/sponsors.json"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum number of results"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Filter: field:op:value (e.g., name:eq:MyItem, status:contains:active)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
):
    """List all shoutouts in a WordPress post.

    Works with both Classic Editor and Gutenberg posts.

    Examples:
        ata-blog shoutouts list 12345
        ata-blog shoutouts list my-post-slug --table
        ata-blog shoutouts list 12345 --filter position:gt:2
    """
    if sponsor is not None:
        if post is not None:
            typer.echo("Error: provide either a post or --sponsor, not both", err=True)
            raise typer.Exit(1)
        output_data = _list_shoutouts_for_sponsor(sponsor)
        output_data = apply_filters(output_data, filter)

        if limit is not None:
            output_data = output_data[:limit]

        prop_list = None
        if properties:
            prop_list = [p.strip() for p in properties.split(",")]
            output_data = [{k: v for k, v in item.items() if k in prop_list} for item in output_data]

        if table:
            columns = prop_list if properties else ["post_id", "slug", "position", "preview"]
            headers = [c.replace("_", " ").title() for c in columns]
            print_table(output_data, columns, headers)
        else:
            print_json(output_data)
        return

    if post is None:
        typer.echo("Error: post is required unless --sponsor is provided", err=True)
        raise typer.Exit(1)

    post_id = _resolve_post_id(post)
    content = _get_post_content(post_id)

    format_type = "Gutenberg" if _is_gutenberg(content) else "Classic"
    total_blocks = _get_total_blocks(content)

    output_data = _shoutout_rows(content)

    output_data = apply_filters(output_data, filter)

    if limit is not None:
        output_data = output_data[:limit]

    if properties:
        prop_list = [p.strip() for p in properties.split(",")]
        output_data = [{k: v for k, v in item.items() if k in prop_list} for item in output_data]

    # Show format info
    typer.echo(f"Post format: {format_type} ({total_blocks} content blocks)", err=True)

    if table:
        columns = prop_list if properties else ["index", "position", "preview"]
        headers = [c.replace("_", " ").title() for c in columns]
        print_table(output_data, columns, headers)
    else:
        print_json(output_data)


@app.command("get")
def get_shoutout(
    post: str = typer.Argument(..., help="WordPress post ID or slug"),
    position: int = typer.Option(..., "--position", "-p", help="Position of the shoutout to get"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
):
    """Get a specific shoutout by position.

    Examples:
        ata-blog shoutouts get 12345 --position 2
        ata-blog shoutouts get my-post-slug -p 4 --json
    """
    post_id = _resolve_post_id(post)
    content = _get_post_content(post_id)

    shoutouts = _calculate_shoutout_positions(content)

    target = None
    for shoutout in shoutouts:
        if shoutout['position'] == position:
            target = shoutout
            break

    if not target:
        typer.echo(f"No shoutout found at position {position}", err=True)
        available = [s['position'] for s in shoutouts]
        if available:
            typer.echo(f"Available positions: {available}", err=True)
        else:
            typer.echo("This post has no shoutouts", err=True)
        raise typer.Exit(1)

    output_data = {
        "position": target['position'],
        "preview": _extract_preview(target['inner']),
        "full_html": target['match'],
    }

    if json_output or not table:
        print_json(output_data)
    else:
        print_table([output_data], ["position", "preview", "full_html"], ["Position", "Preview", "Full HTML"])


@app.command("add")
def add_shoutout(
    post: str = typer.Argument(..., help="WordPress post ID or slug"),
    position: int = typer.Option(1, "--position", "-p", help="Insert after content block N (default: 1)"),
    text: str = typer.Option(..., "--text", help="Shoutout HTML content"),
):
    """Add a shoutout after a specific content block position.

    The text will have rel="noreferrer noopener sponsored" automatically added
    to all <a> tags. Works with both Classic Editor and Gutenberg posts.

    Examples:
        ata-blog shoutouts add 12345 --position 3 --text '<a href="https://example.com">Check this out!</a>'
        ata-blog shoutouts add my-post-slug -p 4 --text 'Sponsored by <a href="https://sponsor.com">Sponsor</a>'
    """
    post_id = _resolve_post_id(post)
    content = _get_post_content(post_id)

    format_type = "Gutenberg" if _is_gutenberg(content) else "Classic"
    existing_shoutouts = _calculate_shoutout_positions(content)

    _validate_insertion_position(content, position, existing_shoutouts)

    processed_text = _process_links(text)

    template = _get_shoutout_template(content)
    shoutout_html = template.format(text=processed_text)

    insertion_point = _find_insertion_point(content, position)

    new_content = content[:insertion_point] + "\n\n" + shoutout_html + "\n\n" + content[insertion_point:]

    _update_post_content(post_id, new_content)

    typer.echo(f"Shoutout added to {format_type} post {post_id} after position {position}")


@app.command("remove")
def remove_shoutout(
    post: str = typer.Argument(..., help="WordPress post ID or slug"),
    position: int = typer.Option(..., "--position", "-p", help="Position of the shoutout to remove"),
):
    """Remove a shoutout at a specific position.

    Works with both Classic Editor and Gutenberg posts.

    Examples:
        ata-blog shoutouts remove 12345 --position 2
        ata-blog shoutouts remove my-post-slug -p 4
    """
    post_id = _resolve_post_id(post)
    content = _get_post_content(post_id)

    format_type = "Gutenberg" if _is_gutenberg(content) else "Classic"
    shoutouts = _calculate_shoutout_positions(content)

    target = None
    for shoutout in shoutouts:
        if shoutout['position'] == position:
            target = shoutout
            break

    if not target:
        typer.echo(f"No shoutout found at position {position}", err=True)
        available = [s['position'] for s in shoutouts]
        if available:
            typer.echo(f"Available positions: {available}", err=True)
        else:
            typer.echo("This post has no shoutouts", err=True)
        raise typer.Exit(1)

    start = target['start']
    end = target['end']

    # Clean up surrounding whitespace
    while start > 0 and content[start - 1] in '\n\r':
        start -= 1
    while end < len(content) and content[end] in '\n\r':
        end += 1

    new_content = content[:start] + content[end:]

    _update_post_content(post_id, new_content)

    typer.echo(f"Shoutout removed from {format_type} post {post_id} at position {position}")
