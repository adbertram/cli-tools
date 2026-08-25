"""Regression tests for comment-author parsing under Facebook's aria-labels.

Facebook renders comment aria-labels with a trailing relative-time phrase,
e.g. "Comment by Adam Bertram about an hour ago". The parser previously
stripped only a SINGLE word before "ago", so multi-word qualifiers stayed
glued to the display name: "Adam Bertram about an". That variant author
string broke every downstream exact-name already-replied (hasCommented) check
and risked duplicate public replies.
"""

from facebook_cli.client import FacebookClient


def _parse(aria):
    return FacebookClient._parse_aria_label(aria)


def test_parse_aria_label_strips_about_an_hour_ago_suffix():
    parsed = _parse("Comment by Adam Bertram about an hour ago")
    assert parsed == {"kind": "comment", "author": "Adam Bertram", "parent_author": None}


def test_parse_aria_label_strips_numeric_minutes_ago_suffix():
    parsed = _parse("Comment by Jane Doe 5 minutes ago")
    assert parsed["kind"] == "comment"
    assert parsed["author"] == "Jane Doe"


def test_parse_aria_label_strips_a_few_seconds_ago_suffix():
    parsed = _parse("Comment by Ann Example a few seconds ago")
    assert parsed["kind"] == "comment"
    assert parsed["author"] == "Ann Example"


def test_parse_aria_label_strips_just_now_suffix():
    parsed = _parse("Comment by Mike Mike just now")
    assert parsed["kind"] == "comment"
    assert parsed["author"] == "Mike Mike"


def test_parse_aria_label_strips_edited_and_timestamp_suffix():
    parsed = _parse("Comment by Adam Bertram Edited 12:45 PM")
    assert parsed["kind"] == "comment"
    assert parsed["author"] == "Adam Bertram"


def test_parse_aria_label_strips_compact_digit_unit_suffix():
    parsed = _parse("Comment by Roger Timmons 38m")
    assert parsed["kind"] == "comment"
    assert parsed["author"] == "Roger Timmons"


def test_parse_aria_label_keeps_plain_name_without_time_phrase():
    parsed = _parse("Comment by Bob Smith")
    assert parsed == {"kind": "comment", "author": "Bob Smith", "parent_author": None}


def test_parse_aria_label_does_not_mangle_name_without_any_time_marker():
    # No relative-time marker anywhere: the full string is the display name.
    parsed = _parse("Comment by Yesterday Once More")
    assert parsed["kind"] == "comment"
    assert parsed["author"] == "Yesterday Once More"


def test_parse_aria_label_does_not_mangle_single_word_author():
    parsed = _parse("Comment by Chad")
    assert parsed["author"] == "Chad"


def test_parse_aria_label_keeps_reply_kind_with_time_suffix():
    parsed = _parse(
        "Reply by Adam Bertram to Roger Timmons's comment about an hour ago"
    )
    assert parsed == {
        "kind": "reply",
        "author": "Adam Bertram",
        "parent_author": "Roger Timmons",
    }


def test_strip_relative_time_suffix_helper_direct_cases():
    strip = FacebookClient._strip_relative_time_suffix
    assert strip("Adam Bertram about an hour ago") == "Adam Bertram"
    assert strip("Nick O'Donnell") == "Nick O'Donnell"
    assert strip("LegoFan99") == "LegoFan99"  # trailing digits alone are not time text
    assert strip("Mike Mike just now") == "Mike Mike"
