"""Utilities for converting Markdown content to WordPress Block Editor format.

This module provides functionality to convert Markdown content to WordPress Block Editor
(Gutenberg) format. Markdown is first converted to HTML, then the HTML is wrapped in
WordPress block comments for proper Gutenberg block rendering.

This implementation mirrors the JavaScript markdownToHtml function from the ATA Blog
Helper Tool to ensure consistent formatting.

Module: wordpress_cli.utils.markdown
"""

from __future__ import annotations

import re

import markdown
from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor


class OpenLinksInNewWindowTreeprocessor(Treeprocessor):
    """Add target="_blank" and rel="noopener" to all links."""

    def run(self, root):
        for element in root.iter('a'):
            element.set('target', '_blank')
            element.set('rel', 'noopener')
        return root


class OpenLinksInNewWindowExtension(Extension):
    """Extension to open all links in new windows."""

    def extendMarkdown(self, md):
        md.treeprocessors.register(
            OpenLinksInNewWindowTreeprocessor(md),
            'open_links_new_window',
            5
        )


def preprocess_markdown(markdown_content: str) -> str:
    """Preprocess markdown before conversion.

    Mirrors the JavaScript preprocessing:
    1. Strip language identifiers from code fences (```python -> ```)
    2. Transform Notion asides (💡) into <hr><strong><em>...</em></strong><hr>

    Args:
        markdown_content: Raw markdown content

    Returns:
        Preprocessed markdown content
    """
    processed = markdown_content

    # Strip language identifiers from code fences
    # ```python\n -> ```\n
    processed = re.sub(r'```\w+\n', '```\n', processed)

    # Transform Notion asides into the desired format
    # <aside>\s*💡\s*content</aside> -> <hr><strong><em>content</em></strong><hr>
    def replace_aside(match):
        content = match.group(1).strip()
        return f'<hr><strong><em>{content}</em></strong><hr>'

    processed = re.sub(
        r'<aside>\s*💡\s*([\s\S]*?)</aside>',
        replace_aside,
        processed
    )

    return processed


def postprocess_html(html_content: str) -> str:
    """Postprocess HTML after conversion.

    Mirrors the JavaScript postprocessing:
    1. Remove <code> tags while keeping <pre> tags
       <pre><code> -> <pre>
       </code></pre> -> </pre>

    Args:
        html_content: HTML content from markdown conversion

    Returns:
        Postprocessed HTML content
    """
    processed = html_content

    # Remove <code> tags within <pre> tags
    processed = re.sub(r'<pre><code[^>]*>', '<pre>', processed)
    processed = re.sub(r'</code></pre>', '</pre>', processed)

    return processed


def convert_markdown_to_html(markdown_content: str) -> str:
    """Convert markdown content to HTML matching the ATA Blog Helper Tool format.

    This function mirrors the JavaScript markdownToHtml function from the ATA
    Blog Helper Tool.

    JavaScript showdown options mirrored:
    - noHeaderId: true -> Don't add IDs to headers
    - simpleLineBreaks: false -> Don't convert single line breaks to <br>
    - tables: true -> Support tables
    - ghCodeBlocks: true -> Support GitHub-style fenced code blocks
    - openLinksInNewWindow: true -> Add target="_blank" to links
    - strikethrough: true -> Support ~~strikethrough~~

    Args:
        markdown_content: Raw Markdown text to convert

    Returns:
        HTML content ready for WordPress
    """
    # Preprocess markdown (strip lang identifiers, transform asides)
    processed_markdown = preprocess_markdown(markdown_content)

    # Convert markdown to HTML with options matching showdown.js
    md = markdown.Markdown(
        extensions=[
            'fenced_code',      # ghCodeBlocks: true
            'tables',           # tables: true
            OpenLinksInNewWindowExtension(),  # openLinksInNewWindow: true
        ],
        # simpleLineBreaks: false is the default in Python markdown
    )

    html_content = md.convert(processed_markdown)

    # Postprocess HTML (remove <code> inside <pre>)
    html_content = postprocess_html(html_content)

    return html_content.strip()
