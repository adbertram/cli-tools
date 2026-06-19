"""Synthetic tests for LastPass `lpass show` header-line parsing.

`lpass show <id>` prints a leading "Group/Name [id: <id>]" (or "Name [id: <id>]")
header before the real "Key: Value" fields. That header contains ': ' inside the
"[id: ...]" segment, so a naive Key: Value split mangled it into a bogus
"<name> [id" key. These tests pin that the header is structured into
id/full_path/name/group instead, that real fields (including multiline Notes)
still parse intact, and that no bogus "...[id" key survives.

No live lpass calls: _run_command is replaced with a fake returning a
subprocess.CompletedProcess, matching the pattern in test_item_masking.py and
test_multiple_matches.py.
"""
import subprocess

from lastpass_cli.client import LastpassClient


def _client_with_show_output(output: str, expected_args=None) -> LastpassClient:
    client = LastpassClient.__new__(LastpassClient)

    def fake_run_command(args, **kwargs):
        if expected_args is not None:
            assert args == expected_args
        return subprocess.CompletedProcess(args, 0, output, "")

    client._run_command = fake_run_command
    return client


def _bogus_id_keys(item) -> list:
    """Return any keys that look like the mangled '<name> [id' header bug."""
    return [key for key in item if "[id" in key]


def test_get_item_single_match_bare_name_header_has_no_bogus_id_key():
    # First line is a bare "Name [id: <id>]" header (the reproduction case from
    # `lastpass items get 7600439653866760487`).
    client = _client_with_show_output(
        "\n".join(
            [
                "google.com [id: 7600439653866760487]",
                "URL: https://google.com",
                "Username: synthetic-user@example.invalid",
                "Password: synthetic-password-value",
            ]
        ),
        ["show", "7600439653866760487"],
    )

    item = client.get_item("7600439653866760487")

    # The bug: a "google.com [id" key alongside the real fields. It must be gone.
    assert _bogus_id_keys(item) == []
    assert "google.com [id" not in item

    # Header is structured, not dropped into a junk key.
    assert item["id"] == "7600439653866760487"
    assert item["name"] == "google.com"
    assert item["group"] == ""
    assert item["full_path"] == "google.com"

    # Real fields still parse. URL is non-sensitive; Username/Password are masked
    # by default (show_password=False) but the KEYS must exist and be correct.
    assert item["URL"] == "https://google.com"
    assert "Username" in item
    assert "Password" in item


def test_get_item_group_name_header_variant_is_structured_the_same_way():
    # "Group/Name [id: <id>]" header variant.
    client = _client_with_show_output(
        "\n".join(
            [
                "Email/google.com [id: 8969039733861907751]",
                "URL: https://mail.google.com",
                "Username: synthetic-user@example.invalid",
                "Password: synthetic-password-value",
            ]
        ),
        ["show", "8969039733861907751"],
    )

    item = client.get_item("8969039733861907751")

    assert _bogus_id_keys(item) == []
    assert "google.com [id" not in item
    assert "Email/google.com [id" not in item

    assert item["id"] == "8969039733861907751"
    assert item["name"] == "google.com"
    assert item["group"] == "Email"
    assert item["full_path"] == "Email/google.com"

    assert item["URL"] == "https://mail.google.com"


def test_get_item_with_header_reveals_real_fields_when_show_password_true():
    # With show_password=True the real values flow through unmasked, proving the
    # header handling does not disturb downstream field parsing/masking.
    client = _client_with_show_output(
        "\n".join(
            [
                "google.com [id: 7600439653866760487]",
                "URL: https://google.com",
                "Username: synthetic-user@example.invalid",
                "Password: synthetic-password-value",
            ]
        ),
        ["show", "7600439653866760487"],
    )

    item = client.get_item("7600439653866760487", show_password=True)

    assert _bogus_id_keys(item) == []
    assert item["id"] == "7600439653866760487"
    assert item["URL"] == "https://google.com"
    assert item["Username"] == "synthetic-user@example.invalid"
    assert item["Password"] == "synthetic-password-value"


def test_show_header_does_not_break_multiline_notes_or_normal_fields():
    # Regression: a multiline Notes value (continuation lines) and a normal
    # single-line field must still parse intact after the header is consumed.
    notes_value = "first notes line\nsecond notes line\nthird notes line"
    client = _client_with_show_output(
        "\n".join(
            [
                "Work/Server Box [id: 1234567890123456789]",
                "URL: https://server.example.invalid",
                "Username: synthetic-user@example.invalid",
                "Password: synthetic-password-value",
                f"Notes: {notes_value}",
            ]
        ),
        ["show", "1234567890123456789"],
    )

    item = client.get_item("1234567890123456789", show_password=True)

    assert _bogus_id_keys(item) == []
    # Header structured correctly with a group containing a space in the name.
    assert item["id"] == "1234567890123456789"
    assert item["group"] == "Work"
    assert item["name"] == "Server Box"
    assert item["full_path"] == "Work/Server Box"

    # Normal field unchanged.
    assert item["URL"] == "https://server.example.invalid"
    # Multiline Notes preserved exactly across continuation lines.
    assert item["Notes"] == notes_value


def test_show_field_value_resembling_id_header_is_not_corrupted():
    # Only the LEADING line gets header treatment. A later field whose VALUE
    # happens to contain "[id: ...]"-like text must parse as a normal field and
    # keep its value intact.
    client = _client_with_show_output(
        "\n".join(
            [
                "google.com [id: 7600439653866760487]",
                "URL: https://google.com",
                "Username: synthetic-user@example.invalid",
                "Notes: see entry foo [id: 9999999999999999999] for details",
            ]
        ),
        ["show", "7600439653866760487"],
    )

    item = client.get_item("7600439653866760487", show_password=True)

    # The leading header parsed into the real id, not the value-embedded one.
    assert item["id"] == "7600439653866760487"
    # The Notes field kept its full literal value, including the bracketed text.
    assert item["Notes"] == "see entry foo [id: 9999999999999999999] for details"
    # No bogus mangled key was produced from either line.
    assert _bogus_id_keys(item) == []
