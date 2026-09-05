"""Tests for the site-wide shoutout commands.

The theme prints one ACF options record (`site_ad_settings`) above every post
body. These tests mock the SSH/wp-cli boundary and assert the pure logic: PHP
script composition, partial updates, readback verification, and the cache flush.
"""
from __future__ import annotations

import base64
import json

import pytest
import typer

from ata_blog_cli.commands import site_shoutout


STORED = {
    "text": "Audit AD with <a href=\"https://specopssoft.com/x\">Specops</a>.",
    "display": True,
    "border": False,
    "logo": 27000,
    "link": "https://specopssoft.com/x?utm_content=display",
    "logo_url": "https://adamtheautomator.com/wp-content/uploads/logo.png",
}


class FakeWp:
    """Record every wp-cli invocation and answer with canned JSON."""

    def __init__(self, stored=None):
        self.stored = dict(stored if stored is not None else STORED)
        self.calls = []

    def __call__(self, wp_command, script=None):
        self.calls.append((wp_command, script))
        if script is None:
            return "Success: Page cache flushed.\nSuccess: The cache was flushed.\n"

        if site_shoutout.UPDATES_TOKEN in script:
            raise AssertionError("update payload token was not replaced")

        marker = "$updates = json_decode(base64_decode('"
        if marker not in script:
            return json.dumps(self.stored)

        encoded = script.split(marker, 1)[1].split("'", 1)[0]
        updates = json.loads(base64.b64decode(encoded).decode("utf-8"))
        before = dict(self.stored)
        self.stored.update(updates)
        return json.dumps({"before": before, "after": dict(self.stored)})


@pytest.fixture
def wp(monkeypatch):
    fake = FakeWp()
    monkeypatch.setattr(site_shoutout, "_run_wp", fake)
    return fake


# --- PHP script composition ---------------------------------------------------

def test_read_script_opens_php_and_targets_the_site_ad_field(wp):
    site_shoutout._read_site_ad()

    _wp_command, script = wp.calls[0]
    assert script.startswith("<?php")
    assert f"$name = '{site_shoutout.SITE_AD_FIELD}';" in script
    assert site_shoutout.FIELD_TOKEN not in script


def test_read_uses_wp_eval_file_over_stdin(wp):
    site_shoutout._read_site_ad()

    assert wp.calls[0][0] == "wp eval-file -"


def test_read_returns_the_stored_record(wp):
    assert site_shoutout._read_site_ad() == STORED


def test_write_script_carries_a_base64_update_payload(wp):
    site_shoutout._write_site_ad({"text": "New text"})

    _wp_command, script = wp.calls[0]
    marker = "$updates = json_decode(base64_decode('"
    encoded = script.split(marker, 1)[1].split("'", 1)[0]
    assert json.loads(base64.b64decode(encoded).decode("utf-8")) == {"text": "New text"}


def test_write_payload_survives_quotes_and_braces_in_text(wp):
    text = "Use {braces}, 'single', \"double\" and <a href=\"x\">link</a>"
    result = site_shoutout._write_site_ad({"text": text})

    assert result["after"]["text"] == text


def test_field_argument_overrides_the_target_record(wp):
    site_shoutout._read_site_ad("header_ad_settings")

    assert "$name = 'header_ad_settings';" in wp.calls[0][1]


# --- partial update semantics -------------------------------------------------

def test_write_leaves_unsupplied_sub_fields_untouched(wp):
    result = site_shoutout._write_site_ad({"border": True})

    assert result["after"]["border"] is True
    assert result["after"]["text"] == STORED["text"]
    assert result["after"]["logo"] == STORED["logo"]
    assert result["after"]["link"] == STORED["link"]


def test_write_returns_the_record_from_before_the_change(wp):
    result = site_shoutout._write_site_ad({"display": False})

    assert result["before"]["display"] is True
    assert result["after"]["display"] is False


# --- set command --------------------------------------------------------------

def test_set_rejects_a_call_with_no_field_options(wp):
    with pytest.raises(typer.Exit) as exit_info:
        site_shoutout.set_site_shoutout(
            text=None, link=None, logo=None, display=None, border=None,
            cache_clear=False, table=False,
        )

    assert exit_info.value.exit_code == 1
    assert wp.calls == []


def test_set_writes_only_the_supplied_options(wp):
    site_shoutout.set_site_shoutout(
        text=None, link=None, logo=31337, display=None, border=None,
        cache_clear=False, table=False,
    )

    assert wp.stored["logo"] == 31337
    assert wp.stored["text"] == STORED["text"]


def test_set_writes_a_false_boolean(wp):
    site_shoutout.set_site_shoutout(
        text=None, link=None, logo=None, display=False, border=None,
        cache_clear=False, table=False,
    )

    assert wp.stored["display"] is False


def test_set_flushes_the_page_cache_by_default(wp):
    site_shoutout.set_site_shoutout(
        text="New text", link=None, logo=None, display=None, border=None,
        cache_clear=True, table=False,
    )

    assert wp.calls[-1][0] == "wp page-cache flush && wp cache flush"


def test_set_skips_the_cache_flush_when_disabled(wp):
    site_shoutout.set_site_shoutout(
        text="New text", link=None, logo=None, display=None, border=None,
        cache_clear=False, table=False,
    )

    assert all(call[0] == "wp eval-file -" for call in wp.calls)


def test_set_fails_when_the_readback_does_not_match(monkeypatch):
    def stubborn(wp_command, script=None):
        if script is None:
            return ""
        return json.dumps({"before": STORED, "after": STORED})

    monkeypatch.setattr(site_shoutout, "_run_wp", stubborn)

    with pytest.raises(typer.Exit) as exit_info:
        site_shoutout.set_site_shoutout(
            text="Never stored", link=None, logo=None, display=None, border=None,
            cache_clear=False, table=False,
        )

    assert exit_info.value.exit_code == 1


def test_set_fails_when_the_cache_flush_fails(monkeypatch):
    fake = FakeWp()

    def flaky(wp_command, script=None):
        if script is None:
            raise RuntimeError("ssh: connection refused")
        return fake(wp_command, script)

    monkeypatch.setattr(site_shoutout, "_run_wp", flaky)

    with pytest.raises(typer.Exit) as exit_info:
        site_shoutout.set_site_shoutout(
            text="New text", link=None, logo=None, display=None, border=None,
            cache_clear=True, table=False,
        )

    assert exit_info.value.exit_code == 1
    assert fake.stored["text"] == "New text"


# --- get command --------------------------------------------------------------

def test_get_prints_the_stored_record(wp, capsys):
    site_shoutout.get_site_shoutout(table=False)

    assert json.loads(capsys.readouterr().out) == STORED


def test_get_exits_non_zero_when_the_read_fails(monkeypatch):
    def broken(wp_command, script=None):
        raise RuntimeError("wp eval-file failed")

    monkeypatch.setattr(site_shoutout, "_run_wp", broken)

    with pytest.raises(typer.Exit) as exit_info:
        site_shoutout.get_site_shoutout(table=False)

    assert exit_info.value.exit_code == 1
