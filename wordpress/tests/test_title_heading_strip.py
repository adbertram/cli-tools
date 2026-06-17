"""Tests for stripping a duplicated title <h1> from converted post bodies.

WordPress renders the Title field as the page H1; DOCX/Markdown conversion also
emits the title as a leading <h1>, which would show the title twice. The guard
removes that leading heading only when it matches the title.
"""
from wordpress_cli.commands.posts import _strip_duplicate_title_heading


TITLE = "The Death of Security Questions: Why Identity Proofing Wins"


def test_strips_leading_h1_matching_title():
    content = f"<h1>{TITLE}</h1>\n<p>For years, organizations...</p>"
    result = _strip_duplicate_title_heading(content, TITLE)
    assert result == "<p>For years, organizations...</p>"


def test_match_ignores_entities_whitespace_and_attrs():
    # Title field is plain; the body H1 has attrs + an HTML entity + extra spaces.
    # Body H1 has attrs, an &amp; entity, an &#8217; apostrophe, and a double space;
    # the title field is the plain decoded form. Normalization must make them match.
    content = '<h1 class="x">Tom&#8217;s Guide &amp;  More</h1>\n<p>Body.</p>'
    result = _strip_duplicate_title_heading(content, "Tom’s Guide & More")
    assert result == "<p>Body.</p>"


def test_leaves_non_matching_leading_h1():
    content = "<h1>A Totally Different Heading</h1>\n<p>Body.</p>"
    result = _strip_duplicate_title_heading(content, TITLE)
    assert result == content


def test_leaves_content_without_leading_h1():
    content = "<p>Intro paragraph.</p>\n<h2>Section</h2>"
    assert _strip_duplicate_title_heading(content, TITLE) == content


def test_none_or_empty_inputs_are_safe():
    assert _strip_duplicate_title_heading("", TITLE) == ""
    assert _strip_duplicate_title_heading("<h1>x</h1>", None) == "<h1>x</h1>"


def test_only_strips_one_leading_heading():
    # A second h2 immediately after must remain.
    content = f"<h1>{TITLE}</h1>\n<h2>{TITLE}</h2>\n<p>Body.</p>"
    result = _strip_duplicate_title_heading(content, TITLE)
    assert result == f"<h2>{TITLE}</h2>\n<p>Body.</p>"
