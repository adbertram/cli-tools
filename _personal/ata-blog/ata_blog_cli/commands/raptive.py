"""Raptive (AdThrive) ad-control commands for ATA Blog CLI.

Manage Raptive ad settings on adamtheautomator.com posts and pages by driving the
wp-admin block-editor "Raptive Ads" meta box through the ``playwright-cli``
browser binary. State is verified against the saved editor controls for pages
and admin-preview settings, against rendered body classes for public posts, and
never via the REST API.

WHY BROWSER, NOT REST
---------------------
The AdThrive post-meta keys (``adthrive_ads_disable``,
``adthrive_ads_disable_content_ads``, ``adthrive_ads_disable_auto_insert_videos``)
are NOT registered with ``show_in_rest`` on this site, and XML-RPC is blocked
(HTTP 403) with no wpcom proxy. A REST ``POST /wp/v2/posts/{id}`` with a ``meta``
body returns HTTP 200 but silently drops those keys -- the value never persists.
The only mechanism that actually toggles ads is the wp-admin editor meta box, so
this command logs in, checks/unchecks the meta-box checkboxes, saves, and then
reads back public post ad state from the rendered post's ``<body>`` class list.
Pages and drafts are verified from the saved editor checkbox state because the
ATA theme does not emit Raptive disable body classes on pages.

CREDENTIALS
-----------
wp-admin credentials come from the cli-tools secret manager (NOT .env, NOT
LastPass). Secret names:
- ``wordpress-username``
- ``ata-blog-adbertram-password``

The wp-admin login and editor URLs are derived from the WordPress resource link
returned by the ``wordpress`` CLI.

FAIL-FAST
---------
One execution path, no fallbacks. If login fails, a checkbox label cannot be
resolved from the live snapshot, the save is not confirmed, or the live-page
read-back does not match the intended state, the command raises and exits
non-zero with an actionable message.
"""
from __future__ import annotations

import json
import re
import secrets
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

import typer
from cli_tools_shared.output import command

from cli_tools_shared.output import print_json, print_table, print_success, print_info, print_error


class RaptiveBrowserError(Exception):
    """A step in the wp-admin browser flow failed (login, navigation, save)."""


class RaptiveRefError(Exception):
    """A required control could not be resolved from the live editor snapshot."""


class RaptiveVerificationError(Exception):
    """The live-page read-back did not match the intended ad state."""


COMMAND_CREDENTIALS = {
    "disable": ["custom"],
    "enable": ["custom"],
    "status": ["custom"],
    "fields": ["custom"],
}

app = typer.Typer(help="Manage Raptive (AdThrive) ad settings on posts and pages")


# --- Data: single source of truth for controllable ad types ------------------
#
# Each logical ad type maps to its REST meta key (informational), its wp-admin
# editor checkbox accessible-name label, and, when available, the <body> class
# the live page carries when that ad type is disabled. Adding a new controllable
# type is a data change here, not a code change.
RAPTIVE_PREVIEW_DISABLE_LABEL = (
    "Disable ads when previewing post Disable all ads when previewing a post "
    "or customizing a theme in WordPress Admin"
)
RAPTIVE_PREVIEW_ENABLE_LABEL = (
    "Enable ads when previewing post Enable all ads when previewing a post "
    "or customizing a theme in WordPress Admin"
)

RAPTIVE_META_FIELDS = {
    "all": "adthrive_ads_disable",
    "content": "adthrive_ads_disable_content_ads",
    "video": "adthrive_ads_disable_auto_insert_videos",
    "metadata": "adthrive_ads_disable_metadata",
    "preview": "adthrive_ads_disable_admin_ads",
    "preview_enable_override": "adthrive_ads_enable_admin_ads",
    "re_enable": "adthrive_ads_re_enable_ads_on",
}

# Logical type -> exact editor checkbox accessible name.
RAPTIVE_CHECKBOX_LABELS = {
    "all": "Disable all ads",
    "content": "Disable content ads",
    "video": "Disable auto-insert video players",
    "preview": RAPTIVE_PREVIEW_DISABLE_LABEL,
    "preview_enable_override": RAPTIVE_PREVIEW_ENABLE_LABEL,
}

# Logical target -> alternate checkbox logical keys that express the same target.
# Raptive flips the preview/admin field when the sitewide setting is already on:
# checked "Enable ads..." means preview ads are enabled, not disabled.
RAPTIVE_CHECKBOX_ALTERNATES = {
    "preview": ("preview_enable_override",),
}

RAPTIVE_CHECKED_MEANS_DISABLED = {
    "all": True,
    "content": True,
    "video": True,
    "preview": True,
    "preview_enable_override": False,
}

RAPTIVE_TARGET_TYPES = ("all", "content", "video", "preview")

# Logical type -> live-page <body> class present when that type is disabled.
RAPTIVE_BODY_CLASSES = {
    "all": "adthrive-disable-all",
    "content": "adthrive-disable-content",
    "video": "adthrive-disable-video",
}

RE_ENABLE_TEXTBOX_LABEL = "Re-enable ads on"
RAPTIVE_PANEL_TOGGLE_LABEL = "Toggle panel: Raptive Ads"
SAVE_BUTTON_LABELS = {
    "post": ("Save", "Update", "Save draft"),
    "page": ("Save", "Update", "Save draft"),
}
SAVE_CONFIRMATION_TEXTS = {
    "post": ("Post updated.", "Post saved.", "Draft saved."),
    "page": ("Page updated.", "Page saved.", "Draft saved."),
}

SECRET_USERNAME = "wordpress-username"
SECRET_PASSWORD = "ata-blog-adbertram-password"

SECRET_MANAGER = "/Users/adam/Dropbox/GitRepos/cli-tools/_repo/_secret-manager/secrets.sh"
# Keep this short: playwright-cli embeds the session name in a macOS socket path.
PLAYWRIGHT_SESSION = f"atar{secrets.token_hex(4)}"

# How long to wait/poll after navigation and after save.
_NAV_SETTLE_SECONDS = 3
_LOGIN_POLL_ATTEMPTS = 12
_LOGIN_POLL_SECONDS = 2
_SAVE_POLL_ATTEMPTS = 6
_SAVE_POLL_SECONDS = 2


# --- Generic browser / shell primitives --------------------------------------


def _run_playwright(args: List[str]) -> str:
    """Run a playwright-cli command, return stdout, raise on non-zero exit."""
    cmd = ["playwright-cli", f"-s={PLAYWRIGHT_SESSION}"] + args
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RaptiveBrowserError(
            f"playwright-cli {' '.join(args[:2])} failed "
            f"(exit {result.returncode}): {result.stderr.strip() or result.stdout.strip()}"
        )
    return result.stdout


def _get_secret(name: str) -> str:
    """Read a secret value from the cli-tools secret manager (never logged)."""
    result = subprocess.run(
        [SECRET_MANAGER, "get", name], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RaptiveBrowserError(
            f"Could not read required secret '{name}' from the cli-tools secret "
            f"manager (exit {result.returncode}): {result.stderr.strip()}. Store it "
            f"with: {SECRET_MANAGER} set {name}"
        )
    value = result.stdout.strip()
    if not value:
        raise RaptiveBrowserError(
            f"Secret '{name}' is empty in the cli-tools secret manager."
        )
    return value


def _snapshot_text() -> str:
    """Capture a page snapshot and return the snapshot YAML file's text content.

    playwright-cli `snapshot` prints a freshly written YAML accessibility tree
    path. Refs change every snapshot, so the caller must always parse the latest
    text.
    """
    stdout = _run_playwright(["snapshot"])
    snapshot_file = _snapshot_file_from_output(stdout)
    path = Path(snapshot_file)
    if not path.exists():
        raise RaptiveBrowserError(f"snapshot file does not exist: {snapshot_file}")
    return path.read_text()


def _snapshot_file_from_output(stdout: str) -> str:
    """Extract the snapshot YAML path from current or legacy playwright-cli output."""
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        snapshot_file = payload.get("file")
        if snapshot_file:
            return str(snapshot_file)
        raise RaptiveBrowserError(f"page snapshot response missing 'file': {payload!r}")

    match = re.search(r"\[Snapshot\]\(([^)]+)\)", stdout)
    if match:
        return match.group(1)
    raise RaptiveBrowserError(
        f"page snapshot output did not include a snapshot file path: {stdout!r}"
    )


def _page_url_from_output(stdout: str) -> str:
    """Extract the landed page URL from current or legacy playwright-cli output."""
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        return str(payload.get("url", ""))

    match = re.search(r"^\s*-\s*Page URL:\s*(.+)$", stdout, re.MULTILINE)
    if match:
        return match.group(1).strip()
    return ""


def _resolve_ref(role: str, label: str, snapshot_text: str) -> str:
    """Resolve an element's session ref by its role + exact accessible name.

    Snapshot lines look like:
        - checkbox "Disable all ads" [checked] [ref=e198] [cursor=pointer]
        - textbox "Username or Email Address" [active] [ref=e8]
        - button "Log In" [ref=e18] [cursor=pointer]

    The accessible name is matched EXACTLY (anchored on the closing quote) so
    "Disable all ads" does not also match the longer preview-checkbox name. The
    ref is the LAST `ref=eNNN` token on the matching line, which is robust to
    flag tokens (`[active]`, `[checked]`) appearing before the ref.
    """
    # Exact role + quoted name, anchored on the closing quote.
    line_pattern = re.compile(
        r'^\s*-\s*' + re.escape(role) + r'\s+"' + re.escape(label) + r'"(?:\s|\[|$)'
    )
    ref_pattern = re.compile(r'ref=(e\d+)')
    for line in snapshot_text.splitlines():
        if line_pattern.search(line):
            refs = ref_pattern.findall(line)
            if not refs:
                raise RaptiveRefError(
                    f'Found {role} "{label}" in snapshot but it carries no [ref=eNNN]: {line.strip()!r}'
                )
            return refs[-1]
    raise RaptiveRefError(
        f'Could not resolve a {role} named "{label}" in the live editor snapshot. '
        f"The wp-admin Raptive Ads UI may have changed."
    )


def _checkbox_is_checked(label: str, snapshot_text: str) -> bool:
    """Return True if the named checkbox line carries the [checked] flag."""
    line_pattern = re.compile(
        r'^\s*-\s*checkbox\s+"' + re.escape(label) + r'"(?:\s|\[|$)'
    )
    for line in snapshot_text.splitlines():
        if line_pattern.search(line):
            return "[checked]" in line
    raise RaptiveRefError(
        f'Could not find checkbox "{label}" in the live editor snapshot.'
    )


def _checkbox_keys_for_target(logical_type: str) -> tuple[str, ...]:
    """Return checkbox logical keys that can satisfy a target logical type."""
    return (logical_type, *RAPTIVE_CHECKBOX_ALTERNATES.get(logical_type, ()))


def _resolve_checkbox_ref(logical_type: str, snapshot_text: str) -> tuple[str, str, str]:
    """Resolve the checkbox key, label, and ref for a target logical type."""
    attempted = []
    for checkbox_key in _checkbox_keys_for_target(logical_type):
        label = RAPTIVE_CHECKBOX_LABELS[checkbox_key]
        attempted.append(label)
        try:
            ref = _resolve_ref("checkbox", label, snapshot_text)
        except RaptiveRefError:
            continue
        return checkbox_key, label, ref
    raise RaptiveRefError(
        f"Could not resolve a Raptive checkbox for logical target '{logical_type}'. "
        f"Tried: {', '.join(attempted)}."
    )


def _checkbox_disabled_value(checkbox_key: str, checked: bool) -> bool:
    """Translate a raw checked state into the logical 'ads disabled' state."""
    if RAPTIVE_CHECKED_MEANS_DISABLED[checkbox_key]:
        return checked
    return not checked


def _target_wanted_checked_state(checkbox_key: str, want_disabled: bool) -> bool:
    """Translate a desired disabled state into the raw checkbox state to set."""
    if RAPTIVE_CHECKED_MEANS_DISABLED[checkbox_key]:
        return want_disabled
    return not want_disabled


def _logical_checkbox_is_disabled(logical_type: str, snapshot_text: str) -> bool:
    """Return the logical disabled state for a target checkbox."""
    checkbox_key, label, _ = _resolve_checkbox_ref(logical_type, snapshot_text)
    checked = _checkbox_is_checked(label, snapshot_text)
    return _checkbox_disabled_value(checkbox_key, checked)


def _is_click_navigation_timeout(message: str) -> bool:
    """Return True for a playwright-cli action timeout after the action completed."""
    return (
        "TimeoutError:" in message
        and "action done" in message
        and "waiting for scheduled navigations to finish" in message
    )


def _is_click_response_render_error(message: str) -> bool:
    """Return True when playwright-cli clicked but failed formatting the response."""
    return "TypeError: Cannot read properties of undefined (reading 'url')" in message


def _click_ref(ref: str) -> None:
    """Click a snapshot ref, tolerating only playwright-cli's post-click render bug."""
    try:
        _run_playwright(["click", ref])
    except RaptiveBrowserError as exc:
        if _is_click_response_render_error(str(exc)):
            return
        raise


def _login_form_visible(snapshot_text: str) -> bool:
    """Return True when the wp-login username/password form is still visible."""
    return (
        "Username or Email Address" in snapshot_text
        and "Password" in snapshot_text
        and "Log In" in snapshot_text
    )


def _wp_admin_context_visible(snapshot_text: str) -> bool:
    """Return True when the snapshot proves an authenticated wp-admin page."""
    return any(
        marker in snapshot_text
        for marker in (
            'heading "Dashboard"',
            'link "Dashboard"',
            'menuitem "Dashboard"',
            'button "Screen Options"',
            'button "Help"',
            'heading "Raptive Ads"',
            'button "Toggle panel: Raptive Ads"',
            "Log Out",
        )
    )


def _wait_for_login_form_to_clear(original_error: str) -> None:
    """Poll after a submit-click navigation timeout until wp-login is gone."""
    for _ in range(_LOGIN_POLL_ATTEMPTS):
        time.sleep(_LOGIN_POLL_SECONDS)
        snapshot_after_click = _snapshot_text()
        if not _login_form_visible(snapshot_after_click):
            return
    raise RaptiveBrowserError(
        "Login submit click completed, but the wp-login form remained visible "
        f"after {_LOGIN_POLL_ATTEMPTS * _LOGIN_POLL_SECONDS} seconds. "
        f"Original playwright-cli click error: {original_error}"
    )


# --- Browser flow steps -------------------------------------------------------


def _login(login_url: str) -> None:
    """Log into wp-admin using secret-manager credentials. Fail-fast."""
    _run_playwright(["open", login_url])
    snapshot = _snapshot_text()
    if not _login_form_visible(snapshot):
        if _wp_admin_context_visible(snapshot):
            return
        raise RaptiveBrowserError(
            "wp-login form was not visible after opening the login URL, and the "
            "snapshot did not show an authenticated wp-admin context."
        )

    username = _get_secret(SECRET_USERNAME)
    password = _get_secret(SECRET_PASSWORD)
    user_ref = _resolve_ref("textbox", "Username or Email Address", snapshot)

    _run_playwright(["fill", user_ref, username])
    snapshot = _snapshot_text()
    pass_ref = _resolve_ref("textbox", "Password", snapshot)
    try:
        _run_playwright(["fill", pass_ref, password, "--submit"])
    except RaptiveBrowserError as exc:
        if not (
            _is_click_navigation_timeout(str(exc))
            or _is_click_response_render_error(str(exc))
        ):
            raise
        _wait_for_login_form_to_clear(str(exc))
    time.sleep(_NAV_SETTLE_SECONDS)


def _open_editor(resource_type: str, resource_id: int, site_origin: str) -> None:
    """Navigate to the editor and confirm we are not bounced to login."""
    url = f"{site_origin}/wp-admin/post.php?post={resource_id}&action=edit"
    stdout = _run_playwright(["goto", url])
    landed = _page_url_from_output(stdout)
    if "wp-login.php" in landed:
        raise RaptiveBrowserError(
            f"Editor navigation for {resource_type} {resource_id} was redirected to the login page "
            f"({landed}). wp-admin login did not stick."
        )
    time.sleep(_NAV_SETTLE_SECONDS)


def _ensure_panel_expanded(snapshot_text: str) -> str:
    """Expand the Raptive Ads panel if collapsed; return a current snapshot.

    The toggle button carries [expanded] when open. If it does not, click it and
    re-snapshot so checkbox refs are present.
    """
    toggle_line_checked = False
    for line in snapshot_text.splitlines():
        if f'"{RAPTIVE_PANEL_TOGGLE_LABEL}"' in line and "button" in line:
            toggle_line_checked = True
            if "[expanded]" in line:
                return snapshot_text
            ref = re.findall(r"ref=(e\d+)", line)
            if not ref:
                raise RaptiveRefError(
                    f'Raptive panel toggle has no ref: {line.strip()!r}'
                )
            _click_ref(ref[-1])
            time.sleep(1)
            return _snapshot_text()
    if not toggle_line_checked:
        raise RaptiveRefError(
            "Could not find the 'Raptive Ads' panel toggle in the editor snapshot. "
            "The wp-admin Raptive meta box may be missing or renamed."
        )
    return snapshot_text


def _set_checkbox_states(targets: Dict[str, bool]) -> None:
    """Drive checkboxes to desired states.

    targets maps logical type ('all'/'content'/'video'/'preview') to the desired
    disabled state. Resolves a fresh ref per box from the current snapshot and
    only acts when the live state differs.
    """
    snapshot = _snapshot_text()
    snapshot = _ensure_panel_expanded(snapshot)
    for logical_type, want_disabled in targets.items():
        checkbox_key, label, ref = _resolve_checkbox_ref(logical_type, snapshot)
        is_checked = _checkbox_is_checked(label, snapshot)
        want_checked = _target_wanted_checked_state(checkbox_key, want_disabled)
        if want_checked and not is_checked:
            _run_playwright(["check", ref])
        elif not want_checked and is_checked:
            _run_playwright(["uncheck", ref])


def _set_re_enable_date(date_str: str) -> None:
    """Fill the 'Re-enable ads on' date textbox."""
    snapshot = _snapshot_text()
    ref = _resolve_ref("textbox", RE_ENABLE_TEXTBOX_LABEL, snapshot)
    _run_playwright(["fill", ref, date_str])


def _resolve_save_ref(resource_type: str, snapshot_text: str) -> str:
    """Resolve the current editor save/update button for this resource type."""
    labels = SAVE_BUTTON_LABELS[resource_type]
    for label in labels:
        try:
            return _resolve_ref("button", label, snapshot_text)
        except RaptiveRefError:
            continue
    raise RaptiveRefError(
        f"Could not resolve a save/update button named one of {', '.join(labels)} "
        "in the live editor snapshot."
    )


def _save_and_confirm(resource_type: str) -> None:
    """Click Save and confirm the editor shows the expected update status."""
    snapshot = _snapshot_text()
    save_ref = _resolve_save_ref(resource_type, snapshot)
    _click_ref(save_ref)
    confirmation_texts = SAVE_CONFIRMATION_TEXTS[resource_type]
    for _ in range(_SAVE_POLL_ATTEMPTS):
        time.sleep(_SAVE_POLL_SECONDS)
        snapshot = _snapshot_text()
        if any(text in snapshot for text in confirmation_texts):
            return
    raise RaptiveBrowserError(
        f"Save was clicked but the editor never showed one of {confirmation_texts}. "
        f"The {resource_type} may not have been saved."
    )


def _close_browser() -> None:
    """Best-effort browser close. Never raises (cleanup on all paths)."""
    subprocess.run(
        ["playwright-cli", f"-s={PLAYWRIGHT_SESSION}", "close"],
        capture_output=True,
        text=True,
    )


# --- Live-page read-back ------------------------------------------------------


def _normalize_resource_type(resource_type: str) -> str:
    """Return the normalized WordPress resource type."""
    normalized = resource_type.lower().strip()
    if normalized not in {"post", "page"}:
        raise typer.BadParameter("--type must be either 'post' or 'page'")
    return normalized


def _resource_command(resource_type: str) -> str:
    """Return the wordpress CLI command group for a resource type."""
    return "pages" if resource_type == "page" else "posts"


def _resource_id_key(resource_type: str) -> str:
    """Return the legacy-compatible ID key for JSON output."""
    return "page_id" if resource_type == "page" else "post_id"


def _get_resource_record(resource_type: str, resource_id: int) -> dict:
    """Resolve a WordPress post/page record via the wordpress CLI."""
    command = _resource_command(resource_type)
    result = subprocess.run(
        ["wordpress", "--no-cache", command, "get", str(resource_id)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RaptiveVerificationError(
            f"Could not resolve {resource_type} {resource_id}: {result.stderr.strip()}"
        )
    try:
        record = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RaptiveVerificationError(
            f"wordpress CLI returned non-JSON resolving {resource_type} {resource_id}: {exc}"
        )
    if not isinstance(record, dict):
        raise RaptiveVerificationError(
            f"wordpress CLI returned invalid {resource_type} {resource_id} payload."
        )
    return record


def _resource_permalink(resource_type: str, resource_id: int, record: dict) -> str:
    """Return the resource permalink from a wordpress CLI record."""
    link = record.get("link")
    if not link:
        raise RaptiveVerificationError(f"{resource_type.title()} {resource_id} has no 'link' field.")
    return link


def _site_origin_from_link(link: str) -> str:
    """Return the scheme + host origin for wp-admin URLs."""
    parsed = urlparse(link)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RaptiveVerificationError(f"Could not derive site origin from link: {link!r}")
    return f"{parsed.scheme}://{parsed.netloc}"


def _login_url(site_origin: str) -> str:
    """Return the canonical wp-admin login URL."""
    return f"{site_origin}/wp-login.php"


def _resource_is_public(record: dict) -> bool:
    """Return whether body-class verification is available without editor auth."""
    return record.get("status") == "publish"


def _fetch_body_classes(resource_type: str, resource_id: int, link: str) -> List[str]:
    """Fetch the live page and return the <body> tag's class tokens.

    Uses a cache-buster query and retries briefly to ride out edge caching, but
    never masks a genuine failure.
    """
    body_pattern = re.compile(r"<body[^>]*\bclass=\"([^\"]*)\"", re.IGNORECASE)
    last_error = None
    for attempt in range(3):
        buster = f"{int(time.time())}{attempt}"
        sep = "&" if "?" in link else "?"
        url = f"{link}{sep}atacb={buster}"
        result = subprocess.run(
            ["curl", "-sL", url], capture_output=True, text=True
        )
        if result.returncode != 0:
            last_error = result.stderr.strip()
            time.sleep(2)
            continue
        match = body_pattern.search(result.stdout)
        if match:
            return match.group(1).split()
        last_error = "no <body class=...> found in fetched HTML"
        time.sleep(2)
    raise RaptiveVerificationError(
        f"Could not read <body> classes from the live page for {resource_type} {resource_id}: {last_error}"
    )


def _verify_live_state(
    resource_type: str,
    resource_id: int,
    link: str,
    expected_disabled: Dict[str, bool],
) -> List[str]:
    """Assert the live-page body classes match intent. Return the live classes.

    expected_disabled maps logical type -> True (class must be PRESENT) or
    False (class must be ABSENT). Raises RaptiveVerificationError on mismatch.
    """
    classes = _fetch_body_classes(resource_type, resource_id, link)
    present = set(classes)
    mismatches = []
    for logical_type, should_be_disabled in expected_disabled.items():
        body_class = RAPTIVE_BODY_CLASSES.get(logical_type)
        if body_class is None:
            continue
        is_present = body_class in present
        if should_be_disabled and not is_present:
            mismatches.append(f"{body_class} expected PRESENT but absent")
        if not should_be_disabled and is_present:
            mismatches.append(f"{body_class} expected ABSENT but present")
    if mismatches:
        raise RaptiveVerificationError(
            f"Live-page read-back for {resource_type} {resource_id} did not match intent: "
            f"{'; '.join(mismatches)}. Body classes: {sorted(present)}"
        )
    return classes


def _requires_editor_verification(targets: Dict[str, bool]) -> bool:
    """Return True when a target has no live-page body-class read-back signal."""
    return any(logical_type not in RAPTIVE_BODY_CLASSES for logical_type in targets)


def _uses_live_body_class_verification(resource_type: str, targets: Dict[str, bool]) -> bool:
    """Return True when live body classes are the authoritative read-back."""
    return resource_type == "post" and not _requires_editor_verification(targets)


def _current_editor_disabled_state() -> Dict[str, bool]:
    """Read the current Raptive checkbox state from the open editor."""
    snapshot = _snapshot_text()
    snapshot = _ensure_panel_expanded(snapshot)
    return {
        logical_type: _logical_checkbox_is_disabled(logical_type, snapshot)
        for logical_type in RAPTIVE_TARGET_TYPES
    }


def _verify_editor_state(expected_disabled: Dict[str, bool]) -> Dict[str, bool]:
    """Assert the saved editor checkbox state matches intent."""
    state = _current_editor_disabled_state()
    mismatches = []
    for logical_type, should_be_disabled in expected_disabled.items():
        is_disabled = state[logical_type]
        if should_be_disabled and not is_disabled:
            mismatches.append(f"{logical_type} checkbox expected disabled but enabled")
        if not should_be_disabled and is_disabled:
            mismatches.append(f"{logical_type} checkbox expected enabled but disabled")
    if mismatches:
        raise RaptiveVerificationError(
            f"Editor checkbox read-back did not match intent: {'; '.join(mismatches)}."
        )
    return state


def _status_label(all_disabled: bool, content_disabled: bool, video_disabled: bool) -> str:
    """Return the human status label for disabled ad types."""

    if all_disabled and content_disabled and video_disabled:
        return "ALL_ADS_DISABLED"
    if all_disabled or content_disabled or video_disabled:
        disabled_types = [
            name
            for name, disabled in (
                ("all", all_disabled),
                ("content", content_disabled),
                ("video", video_disabled),
            )
            if disabled
        ]
        return f"PARTIAL_DISABLED ({', '.join(disabled_types)})"
    return "ADS_ENABLED"


def _status_payload(
    resource_type: str,
    resource_id: int,
    *,
    all_disabled: bool,
    content_disabled: bool,
    video_disabled: bool,
    verification_method: str,
    body_classes: Optional[List[str]] = None,
    preview_ads_disabled: Optional[bool] = None,
) -> dict:
    """Build the public status payload."""
    status = _status_label(all_disabled, content_disabled, video_disabled)
    payload = {
        "resource_type": resource_type,
        "resource_id": resource_id,
        _resource_id_key(resource_type): resource_id,
        "all_ads_disabled": all_disabled,
        "content_ads_disabled": content_disabled,
        "video_disabled": video_disabled,
        "status": status,
        "verification_method": verification_method,
    }
    if preview_ads_disabled is not None:
        payload["preview_ads_disabled"] = preview_ads_disabled
    if body_classes is not None:
        payload["body_classes"] = sorted(c for c in body_classes if c.startswith("adthrive-"))
    return payload


def _live_status(resource_type: str, resource_id: int, link: str) -> dict:
    """Derive ad status for a public resource from live-page <body> classes."""
    classes = set(_fetch_body_classes(resource_type, resource_id, link))
    all_disabled = RAPTIVE_BODY_CLASSES["all"] in classes
    content_disabled = RAPTIVE_BODY_CLASSES["content"] in classes
    video_disabled = RAPTIVE_BODY_CLASSES["video"] in classes
    return {
        **_status_payload(
            resource_type,
            resource_id,
            all_disabled=all_disabled,
            content_disabled=content_disabled,
            video_disabled=video_disabled,
            verification_method="live_body_classes",
            body_classes=list(classes),
        ),
    }


def _editor_status(resource_type: str, resource_id: int) -> dict:
    """Derive ad status from the open editor checkbox state."""
    state = _current_editor_disabled_state()
    return _status_payload(
        resource_type,
        resource_id,
        all_disabled=state["all"],
        content_disabled=state["content"],
        video_disabled=state["video"],
        preview_ads_disabled=state["preview"],
        verification_method="editor_checkboxes",
    )


# --- Shared targeting logic ---------------------------------------------------


def _resolve_targets(content_only: bool, video_only: bool, preview_only: bool, disabled: bool) -> Dict[str, bool]:
    """Map disable/enable flags to a {logical_type: want_disabled} target dict.

    `disabled` is the desired meaning of the selected boxes: True for `disable`,
    False for `enable`. For the default (no flag), the public ad controls are
    targeted. Preview/admin ads are explicit because Raptive stores that as a
    separate admin-preview setting, not a public body-class ad setting.
    """
    selected = [content_only, video_only, preview_only]
    if sum(1 for item in selected if item) > 1:
        raise typer.BadParameter("cannot combine --content-only, --video-only, and --preview-only")
    if content_only:
        return {"content": disabled}
    if video_only:
        return {"video": disabled}
    if preview_only:
        return {"preview": disabled}
    return {"all": disabled, "content": disabled, "video": disabled}


# --- Commands -----------------------------------------------------------------


@app.command("disable")
@command
def ads_disable(
    resource_id: int = typer.Argument(..., help="WordPress post/page ID"),
    all_ads: bool = typer.Option(True, "--all/--no-all", help="Disable ALL ads (default)"),
    content_only: bool = typer.Option(False, "--content-only", "-c", help="Disable only content ads"),
    video_only: bool = typer.Option(False, "--video-only", "-v", help="Disable only video auto-insert"),
    preview_only: bool = typer.Option(False, "--preview-only", help="Disable only ads shown while previewing in WordPress admin"),
    re_enable_days: Optional[int] = typer.Option(None, "--re-enable-days", "-d", help="Auto re-enable after N days"),
    re_enable_date: Optional[str] = typer.Option(None, "--re-enable-date", help="Auto re-enable on date (YYYY-MM-DD)"),
    resource_type: str = typer.Option("post", "--type", help="WordPress resource type: post or page"),
):
    """
    Disable Raptive ads on a WordPress post or page via the wp-admin editor.

    Drives the live "Raptive Ads" meta box (login -> check boxes -> save) and
    verifies public posts against rendered body classes and pages against the
    saved editor checkbox state.

    Examples:
        ata-blog raptive disable 12345                    # Disable all ads
        ata-blog raptive disable 27009 --type page        # Disable all ads on a page
        ata-blog raptive disable 12345 --content-only     # Disable content ads only
        ata-blog raptive disable 12345 --video-only       # Disable video players only
        ata-blog raptive disable 27009 --type page --preview-only  # Disable preview ads only
        ata-blog raptive disable 12345 --re-enable-date 2026-02-01
    """
    resource_type = _normalize_resource_type(resource_type)
    targets = _resolve_targets(content_only, video_only, preview_only, disabled=True)
    ad_type = _describe_targets(targets)
    record = _get_resource_record(resource_type, resource_id)
    link = _resource_permalink(resource_type, resource_id, record)
    site_origin = _site_origin_from_link(link)

    re_enable_str = None
    if re_enable_days is not None and re_enable_date is not None:
        raise typer.BadParameter("cannot combine --re-enable-days and --re-enable-date")
    if re_enable_days is not None:
        from datetime import datetime, timedelta
        re_enable_str = (datetime.now() + timedelta(days=re_enable_days)).strftime("%Y-%m-%d")
    elif re_enable_date is not None:
        from datetime import datetime
        try:
            datetime.strptime(re_enable_date, "%Y-%m-%d")
        except ValueError:
            print_error(f"Invalid date format: {re_enable_date}. Use YYYY-MM-DD.")
            raise typer.Exit(1)
        re_enable_str = re_enable_date

    print_info(f"Disabling {ad_type} on {resource_type} {resource_id} via wp-admin editor...")
    try:
        _login(_login_url(site_origin))
        _open_editor(resource_type, resource_id, site_origin)
        _set_checkbox_states(targets)
        if re_enable_str:
            _set_re_enable_date(re_enable_str)
        _save_and_confirm(resource_type)
        classes = []
        editor_state = None
        verification_method = "live_body_classes"
        if _resource_is_public(record) and _uses_live_body_class_verification(resource_type, targets):
            classes = _verify_live_state(resource_type, resource_id, link, targets)
        else:
            editor_state = _verify_editor_state(targets)
            verification_method = "editor_checkboxes"
    except (RaptiveBrowserError, RaptiveRefError, RaptiveVerificationError) as exc:
        print_error(f"Failed to disable ads on {resource_type} {resource_id}: {exc}")
        raise typer.Exit(1)
    finally:
        _close_browser()

    print_success(f"Disabled {ad_type} on {resource_type} {resource_id} (verified by {verification_method})")
    if re_enable_str:
        print_info(f"Ads will auto re-enable on: {re_enable_str}")
    result = {
        "resource_type": resource_type,
        "resource_id": resource_id,
        _resource_id_key(resource_type): resource_id,
        "action": "disable",
        "ad_type": ad_type,
        "targets": targets,
        "re_enable_date": re_enable_str,
        "verification_method": verification_method,
    }
    if classes:
        result["body_classes"] = sorted(c for c in classes if c.startswith("adthrive-"))
    if editor_state is not None:
        result["editor_checkboxes"] = editor_state
    print_json(result)


@app.command("enable")
@command
def ads_enable(
    resource_id: int = typer.Argument(..., help="WordPress post/page ID"),
    all_ads: bool = typer.Option(True, "--all/--no-all", help="Enable ALL ads (default)"),
    content_only: bool = typer.Option(False, "--content-only", "-c", help="Enable only content ads"),
    video_only: bool = typer.Option(False, "--video-only", "-v", help="Enable only video auto-insert"),
    preview_only: bool = typer.Option(False, "--preview-only", help="Enable only ads shown while previewing in WordPress admin"),
    resource_type: str = typer.Option("post", "--type", help="WordPress resource type: post or page"),
):
    """
    Re-enable Raptive ads on a WordPress post or page via the wp-admin editor.

    Unchecks the meta-box disable flags. Public posts are verified against
    rendered body classes; pages are verified against saved editor checkboxes.

    Examples:
        ata-blog raptive enable 12345                  # Enable all ads
        ata-blog raptive enable 27009 --type page      # Enable all ads on a page
        ata-blog raptive enable 12345 --content-only  # Enable content ads only
        ata-blog raptive enable 12345 --video-only    # Enable video players only
        ata-blog raptive enable 27009 --type page --preview-only  # Enable preview ads only
    """
    resource_type = _normalize_resource_type(resource_type)
    targets = _resolve_targets(content_only, video_only, preview_only, disabled=False)
    ad_type = _describe_targets(targets)
    record = _get_resource_record(resource_type, resource_id)
    link = _resource_permalink(resource_type, resource_id, record)
    site_origin = _site_origin_from_link(link)

    print_info(f"Enabling {ad_type} on {resource_type} {resource_id} via wp-admin editor...")
    try:
        _login(_login_url(site_origin))
        _open_editor(resource_type, resource_id, site_origin)
        _set_checkbox_states(targets)
        _save_and_confirm(resource_type)
        classes = []
        editor_state = None
        verification_method = "live_body_classes"
        if _resource_is_public(record) and _uses_live_body_class_verification(resource_type, targets):
            classes = _verify_live_state(resource_type, resource_id, link, targets)
        else:
            editor_state = _verify_editor_state(targets)
            verification_method = "editor_checkboxes"
    except (RaptiveBrowserError, RaptiveRefError, RaptiveVerificationError) as exc:
        print_error(f"Failed to enable ads on {resource_type} {resource_id}: {exc}")
        raise typer.Exit(1)
    finally:
        _close_browser()

    print_success(f"Enabled {ad_type} on {resource_type} {resource_id} (verified by {verification_method})")
    result = {
        "resource_type": resource_type,
        "resource_id": resource_id,
        _resource_id_key(resource_type): resource_id,
        "action": "enable",
        "ad_type": ad_type,
        "targets": targets,
        "verification_method": verification_method,
    }
    if classes:
        result["body_classes"] = sorted(c for c in classes if c.startswith("adthrive-"))
    if editor_state is not None:
        result["editor_checkboxes"] = editor_state
    print_json(result)


@app.command("status")
@command
def ads_status(
    resource_id: int = typer.Argument(..., help="WordPress post/page ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    resource_type: str = typer.Option("post", "--type", help="WordPress resource type: post or page"),
):
    """
    Check Raptive ad status for a WordPress post or page.

    Reads rendered <body> classes for public posts. Pages, drafts, and settings
    without body-class signals are checked in the wp-admin editor.

    Examples:
        ata-blog raptive status 12345
        ata-blog raptive status 27009 --type page
        ata-blog raptive status 12345 --table
    """
    resource_type = _normalize_resource_type(resource_type)
    try:
        record = _get_resource_record(resource_type, resource_id)
        link = _resource_permalink(resource_type, resource_id, record)
        public_targets = {"all": True, "content": True, "video": True}
        if _resource_is_public(record) and _uses_live_body_class_verification(resource_type, public_targets):
            status_info = _live_status(resource_type, resource_id, link)
        else:
            site_origin = _site_origin_from_link(link)
            try:
                _login(_login_url(site_origin))
                _open_editor(resource_type, resource_id, site_origin)
                status_info = _editor_status(resource_type, resource_id)
            finally:
                _close_browser()
    except (RaptiveBrowserError, RaptiveRefError, RaptiveVerificationError) as exc:
        print_error(f"Failed to read ad status for {resource_type} {resource_id}: {exc}")
        raise typer.Exit(1)

    if table:
        rows = [
            {"setting": "Resource Type", "value": status_info["resource_type"]},
            {"setting": "Resource ID", "value": str(status_info["resource_id"])},
            {"setting": "Status", "value": status_info["status"]},
            {"setting": "All Ads Disabled", "value": "Yes" if status_info["all_ads_disabled"] else "No"},
            {"setting": "Content Ads Disabled", "value": "Yes" if status_info["content_ads_disabled"] else "No"},
            {"setting": "Video Disabled", "value": "Yes" if status_info["video_disabled"] else "No"},
            {"setting": "Verification", "value": status_info["verification_method"]},
        ]
        if "preview_ads_disabled" in status_info:
            rows.insert(
                -1,
                {
                    "setting": "Preview Ads Disabled",
                    "value": "Yes" if status_info["preview_ads_disabled"] else "No",
                },
            )
        print_table(rows, ["setting", "value"], ["Setting", "Value"])
    else:
        print_json(status_info)


@app.command("fields")
@command
def list_fields():
    """
    List the controllable Raptive ad types and their editor / body-class mapping.
    """
    fields = []
    for logical_type, meta_key in RAPTIVE_META_FIELDS.items():
        fields.append({
            "field": logical_type,
            "meta_key": meta_key,
            "checkbox": RAPTIVE_CHECKBOX_LABELS.get(logical_type, ""),
            "body_class": RAPTIVE_BODY_CLASSES.get(logical_type, ""),
        })
    print_table(
        fields,
        ["field", "meta_key", "checkbox", "body_class"],
        ["Field", "Meta Key", "Editor Checkbox", "Body Class"],
    )


def _describe_targets(targets: Dict[str, bool]) -> str:
    """Human label for a target set."""
    keys = set(targets.keys())
    if keys == {"all", "content", "video"}:
        return "all ads (display, content, and video)"
    if keys == {"all", "content", "video", "preview"}:
        return "all ads (display, content, video, and preview)"
    if keys == {"content"}:
        return "content ads"
    if keys == {"video"}:
        return "video auto-insert"
    if keys == {"preview"}:
        return "preview ads"
    return ", ".join(sorted(keys))
