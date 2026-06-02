"""Utilities for converting HTML content to WordPress Block Editor (Gutenberg) format.

This module provides functionality to convert standard HTML to WordPress Block Editor
(Gutenberg) format, wrapping HTML elements in WordPress block comments.

Module: wordpress_cli.utils.blocks
"""

from __future__ import annotations

import html as html_module
import re


def convert_html_to_blocks(html_content: str) -> str:
    """
    Convert standard HTML to WordPress Block Editor (Gutenberg) format.

    This function wraps HTML elements in WordPress block comments so that
    content appears as proper Gutenberg blocks instead of classic editor content.

    Supported conversions:
    - Code blocks -> wp:code
    - Headings (h1-h6) -> wp:heading
    - Unordered lists -> wp:list
    - Ordered lists -> wp:list (ordered)
    - Blockquotes -> wp:quote
    - Paragraphs -> wp:paragraph

    Args:
        html_content: Standard HTML content to convert

    Returns:
        HTML content wrapped in WordPress block comments
    """
    # Convert code blocks to WordPress block format FIRST (before other conversions)
    # Pattern: <pre class="codehilite"><code class="language-LANG">CODE</code></pre>
    def replace_code_block(match):
        lang = match.group(1) or 'plaintext'
        code = match.group(2)
        # Unescape HTML entities in code
        code = html_module.unescape(code)
        # Re-escape for HTML display
        code = html_module.escape(code)
        return f'\n<!-- wp:code {{"language":"{lang}"}} -->\n<pre class="wp-block-code"><code lang="{lang}" class="language-{lang}">{code}</code></pre>\n<!-- /wp:code -->\n'

    html_content = re.sub(
        r'<pre class="codehilite"><code class="language-([^"]*)">(.*?)</code></pre>',
        replace_code_block,
        html_content,
        flags=re.DOTALL
    )

    # Convert headings to WordPress heading blocks
    for level in range(1, 7):
        def replace_heading(match):
            content = match.group(1)
            return f'\n<!-- wp:heading {{"level":{level}}} -->\n<h{level} class="wp-block-heading">{content}</h{level}>\n<!-- /wp:heading -->\n'

        html_content = re.sub(f'<h{level}>(.*?)</h{level}>', replace_heading, html_content)

    # Convert unordered lists to WordPress list blocks
    def replace_ul(match):
        list_content = match.group(1)
        return f'\n<!-- wp:list -->\n<ul class="wp-block-list">{list_content}</ul>\n<!-- /wp:list -->\n'

    html_content = re.sub(r'<ul>(.*?)</ul>', replace_ul, html_content, flags=re.DOTALL)

    # Convert ordered lists to WordPress list blocks
    def replace_ol(match):
        list_content = match.group(1)
        return f'\n<!-- wp:list {{"ordered":true}} -->\n<ol>{list_content}</ol>\n<!-- /wp:list -->\n'

    html_content = re.sub(r'<ol>(.*?)</ol>', replace_ol, html_content, flags=re.DOTALL)

    # Convert blockquotes to WordPress quote blocks
    def replace_quote(match):
        content = match.group(1)
        return f'\n<!-- wp:quote -->\n<blockquote class="wp-block-quote">{content}</blockquote>\n<!-- /wp:quote -->\n'

    html_content = re.sub(r'<blockquote>(.*?)</blockquote>', replace_quote, html_content, flags=re.DOTALL)

    # Convert regular paragraphs to WordPress paragraph blocks LAST
    def replace_paragraph(match):
        content = match.group(1)
        # Skip if this paragraph is already inside a block
        if '<!-- wp:' in content or '<!-- /wp:' in content:
            return match.group(0)
        return f'\n<!-- wp:paragraph -->\n<p>{content}</p>\n<!-- /wp:paragraph -->\n'

    html_content = re.sub(r'<p>(.*?)</p>', replace_paragraph, html_content, flags=re.DOTALL)

    return html_content
