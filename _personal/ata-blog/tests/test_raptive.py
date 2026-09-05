"""Tests for the browser-driven Raptive ad-control command.

State is controlled through the wp-admin editor via playwright-cli and verified
against the rendered live page's <body> classes. These tests mock the
playwright-cli and curl/wordpress boundaries and assert the pure logic:
ref resolution by accessible-name label (exact match), missing-label failure,
checked-state detection, live-page read-back verification, and status parsing.
"""
from __future__ import annotations

import pytest

from ata_blog_cli.commands import raptive


# --- snapshot fixtures --------------------------------------------------------

EDITOR_SNAPSHOT = """\
- generic [ref=e1]:
  - button "Save" [ref=e65] [cursor=pointer]
  - heading "Raptive Ads" [level=2] [ref=e180]
  - 'button "Toggle panel: Raptive Ads" [expanded] [ref=e188] [cursor=pointer]'
  - generic [ref=e196]: Disable all ads
  - checkbox "Disable all ads" [checked] [ref=e198] [cursor=pointer]
  - generic [ref=e201]: Disable content ads
  - checkbox "Disable content ads" [checked] [ref=e203] [cursor=pointer]
  - generic [ref=e206]: Disable auto-insert video players
  - checkbox "Disable auto-insert video players" [ref=e208] [cursor=pointer]
  - textbox "Re-enable ads on" [ref=e213]
  - checkbox "Disable Video Metadata Disable adding metadata to video player on this post" [ref=e218]
  - checkbox "Disable ads when previewing post Disable all ads when previewing a post or customizing a theme in WordPress Admin" [ref=e224]
"""

EDITOR_SNAPSHOT_PREVIEW_ENABLE_OVERRIDE = """\
- generic [ref=e1]:
  - button "Save" [ref=e65] [cursor=pointer]
  - heading "Raptive Ads" [level=2] [ref=e180]
  - 'button "Toggle panel: Raptive Ads" [expanded] [ref=e188] [cursor=pointer]'
  - checkbox "Disable all ads" [checked] [ref=e198] [cursor=pointer]
  - checkbox "Disable content ads" [checked] [ref=e203] [cursor=pointer]
  - checkbox "Disable auto-insert video players" [ref=e208] [cursor=pointer]
  - checkbox "Enable ads when previewing post Enable all ads when previewing a post or customizing a theme in WordPress Admin" [checked] [ref=e224]
"""

LOGIN_SNAPSHOT = """\
- generic [ref=e1]:
  - textbox "Username or Email Address" [active] [ref=e8]
  - textbox "Password" [ref=e12]
  - button "Log In" [ref=e18] [cursor=pointer]
"""

WP_ADMIN_SNAPSHOT = """\
- generic [ref=e1]:
  - heading "Dashboard" [level=1] [ref=e2]
  - button "Screen Options" [ref=e3]
  - link "Log Out" [ref=e4]
"""

NON_LOGIN_NON_ADMIN_SNAPSHOT = """\
- generic [ref=e1]:
  - heading "Maintenance" [level=1] [ref=e2]
"""


# --- ref resolution -----------------------------------------------------------


def test_resolve_ref_extracts_last_ref_on_line():
    """Ref is the last ref=eNNN token, robust to a leading [active] flag."""
    assert raptive._resolve_ref("textbox", "Username or Email Address", LOGIN_SNAPSHOT) == "e8"
    assert raptive._resolve_ref("button", "Log In", LOGIN_SNAPSHOT) == "e18"


def test_resolve_ref_exact_match_not_substring():
    """'Disable all ads' must NOT match the longer preview-checkbox name."""
    # The exact short checkbox is e198; the preview checkbox (which contains the
    # phrase 'Disable all ads' inside its long name) is e224 and must be ignored.
    assert raptive._resolve_ref("checkbox", "Disable all ads", EDITOR_SNAPSHOT) == "e198"
    assert raptive._resolve_ref("checkbox", "Disable content ads", EDITOR_SNAPSHOT) == "e203"
    assert (
        raptive._resolve_ref("checkbox", "Disable auto-insert video players", EDITOR_SNAPSHOT)
        == "e208"
    )
    assert (
        raptive._resolve_ref(
            "checkbox",
            "Disable ads when previewing post Disable all ads when previewing a post or customizing a theme in WordPress Admin",
            EDITOR_SNAPSHOT,
        )
        == "e224"
    )


def test_resolve_ref_missing_label_raises():
    with pytest.raises(raptive.RaptiveRefError) as exc:
        raptive._resolve_ref("checkbox", "Disable nonexistent ads", EDITOR_SNAPSHOT)
    assert "Disable nonexistent ads" in str(exc.value)


def test_checkbox_is_checked_detection():
    assert raptive._checkbox_is_checked("Disable all ads", EDITOR_SNAPSHOT) is True
    assert raptive._checkbox_is_checked("Disable auto-insert video players", EDITOR_SNAPSHOT) is False
    assert (
        raptive._checkbox_is_checked(
            "Disable ads when previewing post Disable all ads when previewing a post or customizing a theme in WordPress Admin",
            EDITOR_SNAPSHOT,
        )
        is False
    )


def test_checkbox_is_checked_missing_raises():
    with pytest.raises(raptive.RaptiveRefError):
        raptive._checkbox_is_checked("Disable nonexistent ads", EDITOR_SNAPSHOT)


def test_preview_meta_fields_are_named():
    assert raptive.RAPTIVE_META_FIELDS["preview"] == "adthrive_ads_disable_admin_ads"
    assert (
        raptive.RAPTIVE_META_FIELDS["preview_enable_override"]
        == "adthrive_ads_enable_admin_ads"
    )


def test_preview_disable_label_means_checked_is_disabled():
    assert raptive._logical_checkbox_is_disabled("preview", EDITOR_SNAPSHOT) is False


def test_preview_enable_override_label_inverts_checked_state():
    assert (
        raptive._logical_checkbox_is_disabled(
            "preview", EDITOR_SNAPSHOT_PREVIEW_ENABLE_OVERRIDE
        )
        is False
    )
    unchecked = EDITOR_SNAPSHOT_PREVIEW_ENABLE_OVERRIDE.replace(" [checked] [ref=e224]", " [ref=e224]")
    assert raptive._logical_checkbox_is_disabled("preview", unchecked) is True


def test_set_checkbox_states_unchecks_preview_enable_override_to_disable(monkeypatch):
    calls = []

    def fake_run_playwright(args):
        calls.append(args)
        return ""

    monkeypatch.setattr(raptive, "_snapshot_text", lambda: EDITOR_SNAPSHOT_PREVIEW_ENABLE_OVERRIDE)
    monkeypatch.setattr(raptive, "_run_playwright", fake_run_playwright)

    raptive._set_checkbox_states({"preview": True})

    assert ["uncheck", "e224"] in calls


def test_resolve_save_ref_supports_save_button():
    assert raptive._resolve_save_ref("post", EDITOR_SNAPSHOT) == "e65"


def test_resolve_save_ref_supports_update_button():
    snapshot = EDITOR_SNAPSHOT.replace('button "Save" [ref=e65]', 'button "Update" [ref=e47]')
    assert raptive._resolve_save_ref("page", snapshot) == "e47"


def test_resolve_save_ref_supports_save_draft_button():
    snapshot = EDITOR_SNAPSHOT.replace('button "Save" [ref=e65]', 'button "Save draft" [ref=e47]')
    assert raptive._resolve_save_ref("page", snapshot) == "e47"


# --- login submit navigation timeout -----------------------------------------


CLICK_NAVIGATION_TIMEOUT = (
    "TimeoutError: locator.click: Timeout 5000ms exceeded. "
    "click action done - waiting for scheduled navigations to finish"
)


def test_login_returns_when_wp_admin_session_already_exists(monkeypatch):
    calls = []

    def fake_run_playwright(args):
        calls.append(args)
        return ""

    def fail_get_secret(name):
        raise AssertionError(f"unexpected secret lookup: {name}")

    monkeypatch.setattr(raptive, "_get_secret", fail_get_secret)
    monkeypatch.setattr(raptive, "_run_playwright", fake_run_playwright)
    monkeypatch.setattr(raptive, "_snapshot_text", lambda: WP_ADMIN_SNAPSHOT)

    raptive._login("https://adamtheautomator.com/wp-login.php")

    assert calls == [["open", "https://adamtheautomator.com/wp-login.php"]]


def test_login_raises_when_form_and_wp_admin_context_are_absent(monkeypatch):
    monkeypatch.setattr(raptive, "_run_playwright", lambda args: "")
    monkeypatch.setattr(raptive, "_snapshot_text", lambda: NON_LOGIN_NON_ADMIN_SNAPSHOT)

    with pytest.raises(raptive.RaptiveBrowserError) as exc:
        raptive._login("https://adamtheautomator.com/wp-login.php")

    assert "wp-login form was not visible" in str(exc.value)
    assert "authenticated wp-admin context" in str(exc.value)


def test_login_click_navigation_timeout_waits_until_form_clears(monkeypatch):
    calls = []
    snapshots = iter(
        [
            LOGIN_SNAPSHOT,
            LOGIN_SNAPSHOT,
            '- generic [ref=e1]:\n  - heading "Dashboard" [level=1] [ref=e2]',
        ]
    )

    def fake_run_playwright(args):
        calls.append(args)
        if args[0] == "fill" and "--submit" in args:
            raise raptive.RaptiveBrowserError(
                "TimeoutError: locator.press: Timeout 5000ms exceeded. "
                "press action done - waiting for scheduled navigations to finish"
            )
        return ""

    monkeypatch.setattr(raptive, "_get_secret", lambda name: f"{name}-value")
    monkeypatch.setattr(raptive, "_run_playwright", fake_run_playwright)
    monkeypatch.setattr(raptive, "_snapshot_text", lambda: next(snapshots))
    monkeypatch.setattr(raptive.time, "sleep", lambda *_: None)

    raptive._login("https://adamtheautomator.com/wp-login.php")

    assert ["fill", "e12", "ata-blog-adbertram-password-value", "--submit"] in calls


def test_login_click_navigation_timeout_raises_when_form_persists(monkeypatch):
    snapshots = iter([LOGIN_SNAPSHOT, LOGIN_SNAPSHOT, LOGIN_SNAPSHOT, LOGIN_SNAPSHOT])

    def fake_run_playwright(args):
        if args[0] == "fill" and "--submit" in args:
            raise raptive.RaptiveBrowserError(CLICK_NAVIGATION_TIMEOUT)
        return ""

    monkeypatch.setattr(raptive, "_LOGIN_POLL_ATTEMPTS", 2)
    monkeypatch.setattr(raptive, "_get_secret", lambda name: f"{name}-value")
    monkeypatch.setattr(raptive, "_run_playwright", fake_run_playwright)
    monkeypatch.setattr(raptive, "_snapshot_text", lambda: next(snapshots))
    monkeypatch.setattr(raptive.time, "sleep", lambda *_: None)

    with pytest.raises(raptive.RaptiveBrowserError) as exc:
        raptive._login("https://adamtheautomator.com/wp-login.php")

    assert "wp-login form remained visible" in str(exc.value)
    assert "waiting for scheduled navigations to finish" in str(exc.value)


def test_login_resolves_password_ref_after_filling_username(monkeypatch):
    calls = []
    refreshed_password_snapshot = LOGIN_SNAPSHOT.replace(
        'textbox "Password" [ref=e12]',
        'textbox "Password" [ref=e31]',
    )
    snapshots = iter([LOGIN_SNAPSHOT, refreshed_password_snapshot])

    def fake_run_playwright(args):
        calls.append(args)
        return ""

    monkeypatch.setattr(raptive, "_get_secret", lambda name: f"{name}-value")
    monkeypatch.setattr(raptive, "_run_playwright", fake_run_playwright)
    monkeypatch.setattr(raptive, "_snapshot_text", lambda: next(snapshots))
    monkeypatch.setattr(raptive.time, "sleep", lambda *_: None)

    raptive._login("https://adamtheautomator.com/wp-login.php")

    assert ["fill", "e31", "ata-blog-adbertram-password-value", "--submit"] in calls
    assert ["fill", "e12", "ata-blog-adbertram-password-value", "--submit"] not in calls


def test_login_click_non_navigation_timeout_still_raises(monkeypatch):
    def fake_run_playwright(args):
        if args[0] == "fill" and "--submit" in args:
            raise raptive.RaptiveBrowserError("TimeoutError: locator.press before action")
        return ""

    monkeypatch.setattr(raptive, "_get_secret", lambda name: f"{name}-value")
    monkeypatch.setattr(raptive, "_run_playwright", fake_run_playwright)
    monkeypatch.setattr(raptive, "_snapshot_text", lambda: LOGIN_SNAPSHOT)

    with pytest.raises(raptive.RaptiveBrowserError) as exc:
        raptive._login("https://adamtheautomator.com/wp-login.php")

    assert "before action" in str(exc.value)


def test_click_ref_ignores_playwright_response_render_error(monkeypatch):
    calls = []

    def fake_run_playwright(args):
        calls.append(args)
        raise raptive.RaptiveBrowserError(
            "playwright-cli click e18 failed (exit 1): ### Error\n"
            "TypeError: Cannot read properties of undefined (reading 'url')"
        )

    monkeypatch.setattr(raptive, "_run_playwright", fake_run_playwright)

    raptive._click_ref("e18")

    assert calls == [["click", "e18"]]


def test_close_browser_closes_dedicated_session(monkeypatch):
    calls = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, capture_output, text):
        calls.append(cmd)
        return Result()

    monkeypatch.setattr(raptive.subprocess, "run", fake_run)

    raptive._close_browser()

    assert calls == [["playwright-cli", f"-s={raptive.PLAYWRIGHT_SESSION}", "close"]]


def test_click_ref_reraises_regular_click_failure(monkeypatch):
    monkeypatch.setattr(
        raptive,
        "_run_playwright",
        lambda args: (_ for _ in ()).throw(raptive.RaptiveBrowserError("element is detached")),
    )

    with pytest.raises(raptive.RaptiveBrowserError) as exc:
        raptive._click_ref("e18")

    assert "element is detached" in str(exc.value)


def test_ensure_panel_expanded_continues_after_click_response_render_error(monkeypatch):
    collapsed = EDITOR_SNAPSHOT.replace(
        '\'button "Toggle panel: Raptive Ads" [expanded] [ref=e188] [cursor=pointer]\'',
        '\'button "Toggle panel: Raptive Ads" [ref=e188] [cursor=pointer]\'',
    )
    calls = []

    def fake_run_playwright(args):
        calls.append(args)
        raise raptive.RaptiveBrowserError(
            "playwright-cli click e188 failed (exit 1): ### Error\n"
            "TypeError: Cannot read properties of undefined (reading 'url')"
        )

    monkeypatch.setattr(raptive, "_run_playwright", fake_run_playwright)
    monkeypatch.setattr(raptive, "_snapshot_text", lambda: EDITOR_SNAPSHOT)
    monkeypatch.setattr(raptive.time, "sleep", lambda *_: None)

    assert raptive._ensure_panel_expanded(collapsed) == EDITOR_SNAPSHOT
    assert calls == [["click", "e188"]]


def test_save_and_confirm_continues_after_click_response_render_error(monkeypatch):
    snapshots = iter(
        [
            EDITOR_SNAPSHOT,
            '- generic [ref=e1]:\n  - text "Page updated."\n',
        ]
    )

    def fake_run_playwright(args):
        raise raptive.RaptiveBrowserError(
            "playwright-cli click e65 failed (exit 1): ### Error\n"
            "TypeError: Cannot read properties of undefined (reading 'url')"
        )

    monkeypatch.setattr(raptive, "_run_playwright", fake_run_playwright)
    monkeypatch.setattr(raptive, "_snapshot_text", lambda: next(snapshots))
    monkeypatch.setattr(raptive.time, "sleep", lambda *_: None)

    raptive._save_and_confirm("page")


# --- playwright-cli output parsing -------------------------------------------


def test_playwright_session_is_short_and_not_default():
    assert raptive.PLAYWRIGHT_SESSION.startswith("atar")
    assert raptive.PLAYWRIGHT_SESSION != "default"
    assert len(raptive.PLAYWRIGHT_SESSION) == 12


def test_run_playwright_uses_dedicated_session(monkeypatch):
    import subprocess

    commands = []

    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(raptive.subprocess, "run", fake_run)
    monkeypatch.setattr(raptive, "PLAYWRIGHT_SESSION", "atar123")

    assert raptive._run_playwright(["snapshot"]) == "ok"
    assert commands == [["playwright-cli", "-s=atar123", "snapshot"]]


def test_snapshot_file_from_json_output():
    assert raptive._snapshot_file_from_output('{"file": ".playwright-cli/page.yml"}') == (
        ".playwright-cli/page.yml"
    )


def test_snapshot_file_from_markdown_output():
    output = """\
### Page
- Page URL: https://adamtheautomator.com/wp-login.php
### Snapshot
- [Snapshot](.playwright-cli/page-2026-06-18.yml)
"""
    assert raptive._snapshot_file_from_output(output) == ".playwright-cli/page-2026-06-18.yml"


def test_page_url_from_markdown_output():
    output = """\
### Page
- Page URL: https://adamtheautomator.com/wp-admin/post.php?post=27009&action=edit
"""
    assert raptive._page_url_from_output(output) == (
        "https://adamtheautomator.com/wp-admin/post.php?post=27009&action=edit"
    )


# --- target resolution --------------------------------------------------------


def test_resolve_targets_default_all():
    assert raptive._resolve_targets(False, False, False, disabled=True) == {
        "all": True,
        "content": True,
        "video": True,
    }


def test_resolve_targets_content_only():
    assert raptive._resolve_targets(True, False, False, disabled=True) == {"content": True}


def test_resolve_targets_video_only_enable():
    assert raptive._resolve_targets(False, True, False, disabled=False) == {"video": False}


def test_resolve_targets_preview_only_disable():
    assert raptive._resolve_targets(False, False, True, disabled=True) == {"preview": True}


def test_resolve_targets_conflicting_flags_raises():
    import typer
    with pytest.raises(typer.BadParameter):
        raptive._resolve_targets(True, True, False, disabled=True)


# --- resource targeting -------------------------------------------------------


def test_normalize_resource_type_accepts_post_and_page():
    assert raptive._normalize_resource_type("post") == "post"
    assert raptive._normalize_resource_type(" Page ") == "page"


def test_normalize_resource_type_rejects_invalid():
    import typer
    with pytest.raises(typer.BadParameter):
        raptive._normalize_resource_type("attachment")


def test_resource_command_maps_posts_and_pages():
    assert raptive._resource_command("post") == "posts"
    assert raptive._resource_command("page") == "pages"
    assert raptive._resource_id_key("post") == "post_id"
    assert raptive._resource_id_key("page") == "page_id"


def test_site_origin_and_login_url_from_resource_link():
    origin = raptive._site_origin_from_link("https://adamtheautomator.com/?page_id=27009")
    assert origin == "https://adamtheautomator.com"
    assert raptive._login_url(origin) == "https://adamtheautomator.com/wp-login.php"


# --- live-page read-back verification -----------------------------------------


def _patch_body_classes(monkeypatch, classes):
    monkeypatch.setattr(raptive, "_fetch_body_classes", lambda *args: list(classes))


def test_verify_state_passes_when_classes_present(monkeypatch):
    _patch_body_classes(
        monkeypatch,
        ["wp-singular", "adthrive-disable-all", "adthrive-disable-content", "adthrive-disable-video"],
    )
    classes = raptive._verify_live_state(
        "post",
        26980,
        "https://x/p/",
        {"all": True, "content": True, "video": True},
    )
    assert "adthrive-disable-all" in classes


def test_verify_state_raises_when_expected_class_absent(monkeypatch):
    _patch_body_classes(monkeypatch, ["wp-singular", "adthrive-disable-content"])
    with pytest.raises(raptive.RaptiveVerificationError) as exc:
        raptive._verify_live_state(
            "post",
            26980,
            "https://x/p/",
            {"all": True, "content": True, "video": True},
        )
    assert "adthrive-disable-all" in str(exc.value)


def test_verify_state_enable_raises_when_class_still_present(monkeypatch):
    _patch_body_classes(monkeypatch, ["wp-singular", "adthrive-disable-all"])
    with pytest.raises(raptive.RaptiveVerificationError) as exc:
        raptive._verify_live_state(
            "post",
            26980,
            "https://x/p/",
            {"all": False, "content": False, "video": False},
        )
    assert "adthrive-disable-all" in str(exc.value)


def test_verify_state_enable_passes_when_classes_gone(monkeypatch):
    _patch_body_classes(monkeypatch, ["wp-singular", "single-post"])
    classes = raptive._verify_live_state(
        "post",
        26980,
        "https://x/p/",
        {"all": False, "content": False, "video": False},
    )
    assert "adthrive-disable-all" not in classes


def test_preview_target_requires_editor_verification():
    assert raptive._requires_editor_verification({"preview": True}) is True
    assert raptive._requires_editor_verification({"all": True, "video": True}) is False


def test_live_body_class_verification_is_only_for_public_post_targets():
    assert (
        raptive._uses_live_body_class_verification(
            "post",
            {"all": True, "content": True, "video": True},
        )
        is True
    )
    assert (
        raptive._uses_live_body_class_verification(
            "page",
            {"all": True, "content": True, "video": True},
        )
        is False
    )
    assert raptive._uses_live_body_class_verification("post", {"preview": True}) is False


# --- editor read-back verification -------------------------------------------


def test_verify_editor_state_passes(monkeypatch):
    monkeypatch.setattr(
        raptive,
        "_current_editor_disabled_state",
        lambda: {"all": True, "content": True, "video": False},
    )
    state = raptive._verify_editor_state({"all": True, "content": True})
    assert state["all"] is True


def test_verify_editor_state_raises_on_mismatch(monkeypatch):
    monkeypatch.setattr(
        raptive,
        "_current_editor_disabled_state",
        lambda: {"all": False, "content": True, "video": False},
    )
    with pytest.raises(raptive.RaptiveVerificationError) as exc:
        raptive._verify_editor_state({"all": True})
    assert "all checkbox expected disabled" in str(exc.value)


# --- status parsing -----------------------------------------------------------


def test_live_status_all_disabled(monkeypatch):
    _patch_body_classes(
        monkeypatch,
        ["adthrive-disable-all", "adthrive-disable-content", "adthrive-disable-video"],
    )
    s = raptive._live_status("post", 26980, "https://x/p/")
    assert s["status"] == "ALL_ADS_DISABLED"
    assert s["resource_type"] == "post"
    assert s["resource_id"] == 26980
    assert s["post_id"] == 26980
    assert s["verification_method"] == "live_body_classes"
    assert s["all_ads_disabled"] and s["content_ads_disabled"] and s["video_disabled"]


def test_live_status_enabled(monkeypatch):
    _patch_body_classes(monkeypatch, ["wp-singular", "single-post"])
    s = raptive._live_status("post", 26980, "https://x/p/")
    assert s["status"] == "ADS_ENABLED"
    assert not s["all_ads_disabled"]


def test_live_status_partial(monkeypatch):
    _patch_body_classes(monkeypatch, ["adthrive-disable-content"])
    s = raptive._live_status("page", 27009, "https://x/?page_id=27009")
    assert s["status"].startswith("PARTIAL_DISABLED")
    assert s["page_id"] == 27009
    assert "content" in s["status"]


# --- fetch_body_classes parsing -----------------------------------------------


def test_fetch_body_classes_parses_body_tag(monkeypatch):
    import subprocess

    html = (
        '<html><head></head>'
        '<body data-rsssl=1 class="wp-singular postid-26980 '
        'adthrive-disable-all adthrive-disable-content adthrive-disable-video">'
        '</body></html>'
    )

    def fake_run(cmd, **kwargs):
        if cmd[0] == "wordpress":
            import json as _json
            return subprocess.CompletedProcess(
                cmd, 0, stdout=_json.dumps({"id": 26980, "link": "https://x/p/"}), stderr=""
            )
        if cmd[0] == "curl":
            return subprocess.CompletedProcess(cmd, 0, stdout=html, stderr="")
        raise AssertionError(f"unexpected: {cmd}")

    monkeypatch.setattr(raptive.subprocess, "run", fake_run)
    classes = raptive._fetch_body_classes("post", 26980, "https://x/p/")
    assert "adthrive-disable-all" in classes
    assert "postid-26980" in classes


def test_fetch_body_classes_raises_without_body(monkeypatch):
    import subprocess

    def fake_run(cmd, **kwargs):
        if cmd[0] == "wordpress":
            import json as _json
            return subprocess.CompletedProcess(
                cmd, 0, stdout=_json.dumps({"id": 1, "link": "https://x/p/"}), stderr=""
            )
        return subprocess.CompletedProcess(cmd, 0, stdout="<html>no body</html>", stderr="")

    monkeypatch.setattr(raptive.subprocess, "run", fake_run)
    monkeypatch.setattr(raptive.time, "sleep", lambda *_: None)
    with pytest.raises(raptive.RaptiveVerificationError):
        raptive._fetch_body_classes("page", 1, "https://x/?page_id=1")


def test_get_resource_record_uses_pages_for_page(monkeypatch):
    import json
    import subprocess

    commands = []

    def fake_run(cmd, **kwargs):
        commands.append(cmd)
        return subprocess.CompletedProcess(
            cmd,
            0,
            stdout=json.dumps({"id": 27009, "status": "draft", "link": "https://x/?page_id=27009"}),
            stderr="",
        )

    monkeypatch.setattr(raptive.subprocess, "run", fake_run)
    record = raptive._get_resource_record("page", 27009)
    assert record["id"] == 27009
    assert commands == [["wordpress", "--no-cache", "pages", "get", "27009"]]
