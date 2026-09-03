"""Unit tests for the emailed-code reader (no network, no Gmail).

The live shape is "<6 digits> is your verification code" from
notifications@trainee.digital (validated 2026-09-03). Only the pure parsing
helpers are tested here; the google-CLI polling paths are exercised live by
`auth login`.
"""

from __future__ import annotations

import pytest

from trainee_digital_cli.email_code import verification_code_from_subject


@pytest.mark.parametrize(
    "subject, expected",
    [
        ("696391 is your verification code", "696391"),
        ("666485 is your verification code", "666485"),
        ("000000 is your verification code", "000000"),
        ("  123456 is your verification code  ", "123456"),
        # Anything that is not an exact live-shaped code mail is not a code.
        ("Welcome to trainee.digital", None),
        ("Re: 123456 is your verification code", None),
        ("12345 is your verification code", None),
        ("1234567 is your verification code", None),
        ("Your verification code is 123456", None),
        ("", None),
        (None, None),
        (123456, None),
    ],
)
def test_verification_code_from_subject(subject, expected):
    assert verification_code_from_subject(subject) == expected
