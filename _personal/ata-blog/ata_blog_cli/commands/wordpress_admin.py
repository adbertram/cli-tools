"""WordPress admin commands for ATA Blog CLI."""
import json
import re
import subprocess
from html.parser import HTMLParser
from typing import Any, List, Optional
from urllib.parse import urljoin

import requests
import typer
from cli_tools_shared.output import command
from cli_tools_shared.config import get_runtime_profile_resolution

SECRET_MANAGER = "/Users/adam/Dropbox/GitRepos/cli-tools/_repo/_secret-manager/secrets.sh"
# Canonical cli-tools secret names. These are the same names that
# ata_blog_cli.commands.raptive uses to drive the same adamtheautomator.com
# wp-admin login. Do not invent per-module aliases for these credentials.
SECRET_USERNAME = "wordpress-username"
SECRET_PASSWORD = "ata-blog-adbertram-password"
WP_ADMIN_BASE_URL = "https://adamtheautomator.com/wp-admin/"
# The wp-admin login endpoint is public site structure, not a credential, so it
# is derived from the site origin instead of stored in the secret manager.
WP_LOGIN_URL = urljoin(WP_ADMIN_BASE_URL, "/wp-login.php")
REDIRECTION_PAGE_SIZE = 200
REDIRECTION_ADMIN_URL = urljoin(WP_ADMIN_BASE_URL, "tools.php?page=redirection.php")
REDIRECTION_API_URL = urljoin(WP_ADMIN_BASE_URL, "/wp-json/redirection/v1/redirect")
PERMALINK_DEBUG_URL = urljoin(
    WP_ADMIN_BASE_URL,
    "tools.php?page=permalink-manager&section=debug",
)
PERMALINK_EDITOR_URL = urljoin(
    WP_ADMIN_BASE_URL,
    "tools.php?page=permalink-manager&section=uri_editor&subsection=post",
)
WP_REST_PAGE_SIZE = 100
WP_REST_BASE_URL = urljoin(WP_ADMIN_BASE_URL, "/wp-json/wp/v2/")


class WPAdminAjaxError(RuntimeError):
    """Raised when a WordPress admin-ajax plugin operation returns success=false."""

    def __init__(self, action: str, payload: dict):
        self.action = action
        self.payload = payload
        super().__init__(f"admin-ajax {action} failed: {payload}")


class WPAdminServiceUnavailable(RuntimeError):
    """Classify wp-admin HTTP 503s without retrying a possible mutation."""

    def __init__(
        self,
        *,
        stage: str,
        url: str,
        mutation_sent: bool,
        plugin_path: Optional[str] = None,
    ) -> None:
        self.stage = stage
        self.url = url
        self.mutation_sent = mutation_sent
        self.plugin_path = plugin_path
        target = f" for plugin {plugin_path}" if plugin_path else ""
        if mutation_sent:
            guidance = (
                "The plugin-action POST was sent, so the mutation outcome is unknown. "
                "Do not automatically retry or retry in the same run. First perform an uncached target "
                "readback and stop if the requested state is already reached. Only when the state is "
                "unchanged, wp-admin is healthy, and the action is still valid may a new operator-approved "
                "invocation run."
            )
            code = "WP_ADMIN_503_MUTATION_OUTCOME_UNKNOWN"
        else:
            guidance = (
                "The plugin-action POST was not sent by this invocation. Do not retry until wp-admin is "
                "healthy and a fresh target preflight still proves the action is required."
            )
            code = "WP_ADMIN_503_PRE_MUTATION"
        super().__init__(f"{code}: HTTP 503 during {stage}{target} at {url}. {guidance}")


def _raise_for_wp_admin_status(
    response: requests.Response,
    *,
    stage: str,
    mutation_sent: bool = False,
    plugin_path: Optional[str] = None,
) -> None:
    """Raise a stage-aware error for 503; preserve normal requests errors otherwise."""
    if response.status_code == 503:
        raise WPAdminServiceUnavailable(
            stage=stage,
            url=response.url,
            mutation_sent=mutation_sent,
            plugin_path=plugin_path,
        )
    response.raise_for_status()


COMMAND_CREDENTIALS = {
    "security-scan": ["custom"],
    "health-report": ["custom"],
    "cache": ["custom"],
    "cache clear-all": ["custom"],
    "redirects": ["custom"],
    "redirects export": ["custom"],
    "relationships": ["custom"],
    "relationships export": ["custom"],
    "plugins": ["custom"],
    "themes": ["custom"],
    "file-push": ["no_auth"],
    "plugins list": ["custom"],
    "plugins get": ["custom"],
    "plugins activate": ["custom"],
    "plugins deactivate": ["custom"],
    "plugins delete": ["custom"],
    "plugins install": ["custom"],
    "plugins upgrade": ["custom"],
}

app = typer.Typer(help="Manage WordPress admin operations", no_args_is_help=True)
cache_app = typer.Typer(help="Manage WordPress/WP Engine caches", no_args_is_help=True)
redirects_app = typer.Typer(help="Export WordPress redirect rules", no_args_is_help=True)
relationships_app = typer.Typer(
    help="Export WordPress post relationships and entity profiles",
    no_args_is_help=True,
)
plugins_app = typer.Typer(help="Manage WordPress plugins", no_args_is_help=True)
themes_app = typer.Typer(help="Manage WordPress themes", no_args_is_help=True)
app.add_typer(cache_app, name="cache")
app.add_typer(redirects_app, name="redirects")
app.add_typer(relationships_app, name="relationships")
app.add_typer(plugins_app, name="plugins")
app.add_typer(themes_app, name="themes")


def _wordpress_profile_args() -> list[str]:
    """Return delegated wordpress profile arguments for the active runtime profile."""
    profile_name, _profile_auth_type = get_runtime_profile_resolution()
    return ["--profile", profile_name] if profile_name else []


def _run_wordpress(args: List[str], *, include_profile: bool = True) -> None:
    """Run a wordpress admin command with inherited stdio for interactive flows."""
    command = ["wordpress", "admin"]
    if include_profile:
        command.extend(_wordpress_profile_args())
    command.extend(args)
    result = subprocess.run(command, text=True)
    raise typer.Exit(result.returncode)


def _run_wordpress_json(args: List[str]) -> dict:
    """Run a wordpress admin command and parse a JSON object response."""
    command = ["wordpress", "admin", *_wordpress_profile_args(), *args]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise RuntimeError(f"wordpress {' '.join(args)} failed: {message}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"wordpress {' '.join(args)} returned non-JSON output: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"wordpress {' '.join(args)} returned {type(payload).__name__}, expected object")
    return payload


def _get_secret(name: str) -> str:
    """Read a wp-admin secret from the cli-tools secret manager without logging it."""
    result = subprocess.run([SECRET_MANAGER, "get", name], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"Could not read required secret '{name}' from the cli-tools secret manager "
            f"(exit {result.returncode}): {result.stderr.strip()}"
        )
    value = result.stdout.strip()
    if not value:
        raise RuntimeError(f"Secret '{name}' is empty in the cli-tools secret manager")
    return value


def _wp_admin_session() -> requests.Session:
    """Log into wp-admin and return an authenticated requests session."""
    login_url = WP_LOGIN_URL
    username = _get_secret(SECRET_USERNAME)
    password = _get_secret(SECRET_PASSWORD)
    session = requests.Session()
    session.headers.update({"User-Agent": "ATA-Blog-CLI/wordpress-admin"})
    login_page = session.get(login_url, timeout=30)
    _raise_for_wp_admin_status(login_page, stage="wp-admin login page")
    response = session.post(
        login_url,
        data={
            "log": username,
            "pwd": password,
            "wp-submit": "Log In",
            "redirect_to": urljoin(WP_ADMIN_BASE_URL, "plugins.php?plugin_status=upgrade"),
            "testcookie": "1",
        },
        timeout=30,
        allow_redirects=True,
    )
    _raise_for_wp_admin_status(response, stage="wp-admin login redirect")
    if "wp-login.php" in response.url:
        raise RuntimeError("wp-admin login did not stick; redirected back to wp-login.php")
    return session


def _extract_updates_nonce(plugins_page_html: str) -> str:
    """Extract WordPress core's plugin-update AJAX nonce from plugins.php."""
    for pattern in (
        r'"ajax_nonce"\s*:\s*"([^"]+)"',
        r"'ajax_nonce'\s*:\s*'([^']+)'",
    ):
        match = re.search(pattern, plugins_page_html)
        if match:
            return match.group(1)
    raise RuntimeError("Could not find WordPress plugin-update AJAX nonce on plugins.php")


def _plugin_file_from_rest_path(plugin_path: str) -> str:
    """Convert REST plugin path to wp-admin plugin file path."""
    if plugin_path.endswith(".php"):
        return plugin_path
    return f"{plugin_path}.php"


def _slug_from_plugin_path(plugin_path: str) -> str:
    """Return the plugin directory slug from a REST plugin path."""
    slug = plugin_path.split("/", 1)[0].strip()
    if not slug:
        raise RuntimeError(f"Could not determine plugin slug from {plugin_path!r}")
    return slug


def _force_wp_plugin_update_check(session: requests.Session) -> None:
    """Ask WordPress admin to refresh plugin update transients before updater AJAX."""
    response = session.get(urljoin(WP_ADMIN_BASE_URL, "update-core.php?force-check=1"), timeout=60)
    _raise_for_wp_admin_status(response, stage="plugin update preflight force-check")
    if "wp-login.php" in response.url:
        raise RuntimeError("update-core.php force-check request was redirected to wp-login.php after login")


def _run_plugin_wp_admin_ajax_action(
    plugin_path: str,
    action: str,
    plugin_status: str,
    timeout: int = 300,
    *,
    force_update_check: bool = False,
) -> dict:
    """Run a WordPress core authenticated admin-ajax plugin action."""
    session = _wp_admin_session()
    if force_update_check:
        _force_wp_plugin_update_check(session)
    plugins_page = session.get(urljoin(WP_ADMIN_BASE_URL, f"plugins.php?plugin_status={plugin_status}"), timeout=30)
    _raise_for_wp_admin_status(
        plugins_page,
        stage="plugin action preflight page",
        plugin_path=plugin_path,
    )
    if "wp-login.php" in plugins_page.url:
        raise RuntimeError("plugins.php request was redirected to wp-login.php after login")
    nonce = _extract_updates_nonce(plugins_page.text)
    plugin_file = _plugin_file_from_rest_path(plugin_path)
    response = session.post(
        urljoin(WP_ADMIN_BASE_URL, "admin-ajax.php"),
        data={
            "action": action,
            "_ajax_nonce": nonce,
            "plugin": plugin_file,
            "slug": _slug_from_plugin_path(plugin_path),
        },
        timeout=timeout,
    )
    _raise_for_wp_admin_status(
        response,
        stage=f"admin-ajax {action} POST",
        mutation_sent=True,
        plugin_path=plugin_path,
    )
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"admin-ajax {action} returned non-JSON output: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"admin-ajax {action} returned non-object JSON")
    if payload.get("success") is not True:
        raise WPAdminAjaxError(action, payload)
    return payload


def _upgrade_plugin_via_wp_admin_ajax(plugin_path: str) -> dict:
    """Run WordPress core's authenticated admin-ajax plugin updater."""
    return _run_plugin_wp_admin_ajax_action(plugin_path, "update-plugin", "upgrade", force_update_check=True)


def _ajax_error_message(payload: dict) -> str:
    """Return WordPress admin-ajax error text from a plugin operation payload."""
    data = payload.get("data")
    if isinstance(data, dict):
        message = data.get("errorMessage")
        if isinstance(message, str):
            return message
    return ""


def _delete_plugin_via_wp_admin_ajax(plugin_path: str) -> dict:
    """Run WordPress core's authenticated admin-ajax plugin deleter."""
    return _run_plugin_wp_admin_ajax_action(plugin_path, "delete-plugin", "inactive")


def _extract_wp_api_nonce(admin_page_html: str) -> str:
    """Extract the REST API nonce from an authenticated wp-admin page."""
    match = re.search(r'wpApiSettings\s*=\s*(\{.*?\});', admin_page_html, flags=re.S)
    if match:
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            payload = {}
        nonce = payload.get("nonce")
        if isinstance(nonce, str) and nonce:
            return nonce

    match = re.search(r'"nonce"\s*:\s*"([^"]+)"', admin_page_html)
    if match:
        return match.group(1)

    raise RuntimeError("Could not extract WordPress REST API nonce from wp-admin page")


class _NamedTextareaParser(HTMLParser):
    """Collect named textarea contents from a wp-admin HTML document."""

    def __init__(self) -> None:
        super().__init__()
        self.values: dict[str, str] = {}
        self._name: Optional[str] = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag != "textarea":
            return
        if self._name is not None:
            raise RuntimeError("Permalink Manager debug page contains nested textareas")
        name = dict(attrs).get("name")
        self._name = name
        self._parts = []

    def handle_data(self, data: str) -> None:
        if self._name is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "textarea" or self._name is None:
            return
        if self._name in self.values:
            raise RuntimeError(
                f"Permalink Manager debug page has duplicate textarea {self._name!r}"
            )
        self.values[self._name] = "".join(self._parts)
        self._name = None
        self._parts = []


class _PermalinkEditorParser(HTMLParser):
    """Collect Permalink Manager URI rows and reported totals."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[dict[str, str]] = []
        self.total_texts: list[str] = []
        self._row: Optional[dict[str, str]] = None
        self._total_parts: Optional[list[str]] = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "tr":
            if self._row is not None:
                raise RuntimeError("Permalink Manager URI editor contains nested rows")
            self._row = {}
            return
        if tag == "span" and "displaying-num" in classes:
            if self._total_parts is not None:
                raise RuntimeError("Permalink Manager URI editor contains nested totals")
            self._total_parts = []
            return
        if tag == "input" and "custom_uri" in classes:
            self._set_row_field("rule_id", attributes.get("data-element-id"))
            self._set_row_field("source", attributes.get("value"))
            return
        if tag == "a" and "post_permalink" in classes:
            self._set_row_field("target", attributes.get("href"))

    def handle_data(self, data: str) -> None:
        if self._total_parts is not None:
            self._total_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "span" and self._total_parts is not None:
            self.total_texts.append("".join(self._total_parts).strip())
            self._total_parts = None
            return
        if tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None

    def _set_row_field(self, name: str, value: Optional[str]) -> None:
        if self._row is None:
            raise RuntimeError(
                f"Permalink Manager URI editor has malformed {name} outside a table row"
            )
        if name in self._row or value is None:
            raise RuntimeError(f"Permalink Manager URI editor has malformed {name}")
        self._row[name] = value


def _require_redirect_string(value: Any, *, field: str, source: str) -> str:
    """Return a required non-empty string from a redirect source record."""
    if not isinstance(value, str) or not value:
        raise RuntimeError(f"{source} record is malformed: {field} must be a non-empty string")
    return value


def _read_only_get(
    session: requests.Session,
    url: str,
    *,
    stage: str,
    **kwargs: Any,
) -> requests.Response:
    """Issue one authenticated GET and reject errors or lost login state."""
    response = session.get(url, **kwargs)
    _raise_for_wp_admin_status(response, stage=stage)
    if "wp-login.php" in response.url:
        raise RuntimeError(f"{stage} was redirected to wp-login.php")
    return response


def _read_redirection_page(
    session: requests.Session,
    *,
    nonce: str,
    page: int,
) -> tuple[list[dict[str, Any]], int]:
    """Read and validate one Redirection REST page."""
    response = _read_only_get(
        session,
        REDIRECTION_API_URL,
        stage=f"read-only Redirection export page {page}",
        headers={"X-WP-Nonce": nonce, "Accept": "application/json"},
        params={
            "orderby": "id",
            "direction": "asc",
            "per_page": REDIRECTION_PAGE_SIZE,
            "page": page,
        },
        timeout=30,
    )
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"Redirection page {page} returned malformed JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"Redirection page {page} is malformed: expected an object")
    items = payload.get("items")
    total = payload.get("total")
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise RuntimeError(f"Redirection page {page} is malformed: items must be objects")
    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise RuntimeError(f"Redirection page {page} is malformed: total must be a non-negative integer")
    return items, total


def _normalize_redirection_record(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize one Redirection plugin rule without discarding redirect semantics."""
    rule_id = item.get("id")
    if isinstance(rule_id, bool) or not isinstance(rule_id, (int, str)) or str(rule_id) == "":
        raise RuntimeError("Redirection record is malformed: id must be present")
    enabled = item.get("enabled")
    regex = item.get("regex")
    status = item.get("action_code")
    if not isinstance(enabled, bool):
        raise RuntimeError("Redirection record is malformed: enabled must be a boolean")
    if not isinstance(regex, bool):
        raise RuntimeError("Redirection record is malformed: regex must be a boolean")
    if isinstance(status, bool) or not isinstance(status, int):
        raise RuntimeError("Redirection record is malformed: action_code must be an integer")

    match_data = item.get("match_data")
    if not isinstance(match_data, dict) or not isinstance(match_data.get("source"), dict):
        raise RuntimeError("Redirection record is malformed: match_data.source is required")
    source_options = match_data["source"]
    flag_case = source_options.get("flag_case")
    flag_regex = source_options.get("flag_regex")
    if not isinstance(flag_case, bool) or not isinstance(flag_regex, bool):
        raise RuntimeError("Redirection record is malformed: case and regex flags must be booleans")
    if flag_regex != regex:
        raise RuntimeError("Redirection record is malformed: regex flags disagree")

    action_data = item.get("action_data")
    if not isinstance(action_data, dict):
        raise RuntimeError("Redirection record is malformed: action_data must be an object")
    return {
        "source_plugin": "redirection",
        "rule_id": str(rule_id),
        "enabled": enabled,
        "match_mode": "regex" if regex else "plain",
        "match_type": _require_redirect_string(
            item.get("match_type"), field="match_type", source="Redirection"
        ),
        "http_status": status,
        "source": _require_redirect_string(item.get("url"), field="url", source="Redirection"),
        "target": _require_redirect_string(
            action_data.get("url"), field="action_data.url", source="Redirection"
        ),
        "query_mode": _require_redirect_string(
            source_options.get("flag_query"), field="match_data.source.flag_query", source="Redirection"
        ),
        "case_sensitive": not flag_case,
    }


def _export_redirection_records(session: requests.Session) -> tuple[list[dict[str, Any]], int]:
    """Export every Redirection rule and prove the source remains available."""
    admin_page = _read_only_get(
        session,
        REDIRECTION_ADMIN_URL,
        stage="read-only Redirection admin page",
        timeout=30,
    )
    nonce = _extract_wp_api_nonce(admin_page.text)

    items, reported = _read_redirection_page(session, nonce=nonce, page=0)
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    page = 0
    while True:
        for item in items:
            record = _normalize_redirection_record(item)
            rule_id = record["rule_id"]
            if rule_id in seen_ids:
                raise RuntimeError(f"Redirection duplicate rule ID {rule_id}")
            seen_ids.add(rule_id)
            records.append(record)
        if len(records) >= reported:
            break
        page += 1
        items, page_total = _read_redirection_page(session, nonce=nonce, page=page)
        if page_total != reported:
            raise RuntimeError(
                f"Redirection count mismatch: page 0 reported {reported}, page {page} reported {page_total}"
            )
        if not items:
            raise RuntimeError(
                f"Redirection count mismatch: reported {reported}, exported {len(records)}"
            )

    if len(records) != reported:
        raise RuntimeError(f"Redirection count mismatch: reported {reported}, exported {len(records)}")
    try:
        _final_items, final_total = _read_redirection_page(session, nonce=nonce, page=0)
    except Exception as exc:
        raise RuntimeError(f"Redirection source unavailable after export: {exc}") from exc
    if final_total != reported:
        raise RuntimeError(
            f"Redirection count mismatch after export: started at {reported}, ended at {final_total}"
        )
    return records, reported


def _parse_permalink_settings(html: str) -> tuple[int, str]:
    """Read redirect status and query handling from Permalink Manager debug data."""
    parser = _NamedTextareaParser()
    parser.feed(html)
    parser.close()
    settings = parser.values.get("debug-data[settings]")
    if settings is None:
        raise RuntimeError("Permalink Manager source is malformed: settings debug data is missing")

    def setting(name: str) -> int:
        matches = re.findall(
            rf"^\s*\[{re.escape(name)}\]\s*=>\s*(.*?)\s*$",
            settings,
            flags=re.M,
        )
        if len(matches) != 1 or not matches[0].isdigit():
            raise RuntimeError(f"Permalink Manager source is malformed: setting {name!r} is invalid")
        return int(matches[0])

    status = setting("redirect")
    copy_query = setting("copy_query_redirect")
    if copy_query not in (0, 1):
        raise RuntimeError(
            "Permalink Manager source is malformed: copy_query_redirect must be 0 or 1"
        )
    return status, "pass" if copy_query == 1 else "ignore"


def _read_permalink_editor_page(
    session: requests.Session,
    *,
    page: int,
) -> tuple[list[dict[str, str]], int]:
    """Read and validate one Permalink Manager URI-editor page."""
    response = _read_only_get(
        session,
        PERMALINK_EDITOR_URL,
        stage=f"read-only Permalink Manager URI editor page {page}",
        params={"orderby": "ID", "order": "asc", "paged": page},
        timeout=30,
    )
    parser = _PermalinkEditorParser()
    parser.feed(response.text)
    parser.close()
    totals = []
    for text in parser.total_texts:
        match = re.fullmatch(r"\s*([\d,]+)\s+items?\s*", text)
        if not match:
            raise RuntimeError("Permalink Manager URI editor has a malformed reported count")
        totals.append(int(match.group(1).replace(",", "")))
    if not totals or len(set(totals)) != 1:
        raise RuntimeError("Permalink Manager URI editor has a malformed or inconsistent reported count")
    for row in parser.rows:
        if set(row) != {"rule_id", "source", "target"}:
            raise RuntimeError("Permalink Manager URI editor contains a malformed record")
        for field, value in row.items():
            _require_redirect_string(value, field=field, source="Permalink Manager")
    return parser.rows, totals[0]


def _read_permalink_settings(session: requests.Session) -> tuple[int, str]:
    """Read Permalink Manager redirect settings from its debug page."""
    response = _read_only_get(
        session,
        PERMALINK_DEBUG_URL,
        stage="read-only Permalink Manager debug page",
        timeout=30,
    )
    return _parse_permalink_settings(response.text)


def _export_permalink_records(session: requests.Session) -> tuple[list[dict[str, Any]], int]:
    """Export every Permalink Manager URI mapping and prove source stability."""
    status, query_mode = _read_permalink_settings(session)
    rows, reported = _read_permalink_editor_page(session, page=1)
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    page = 1
    while True:
        for row in rows:
            rule_id = row["rule_id"]
            if rule_id in seen_ids:
                raise RuntimeError(f"Permalink Manager duplicate rule ID {rule_id}")
            seen_ids.add(rule_id)
            records.append(
                {
                    "source_plugin": "permalink-manager",
                    "rule_id": rule_id,
                    "enabled": True,
                    "match_mode": "permalink_override",
                    "match_type": "url",
                    "http_status": status,
                    "source": row["source"],
                    "target": row["target"],
                    "query_mode": query_mode,
                    "case_sensitive": False,
                }
            )
        if len(records) >= reported:
            break
        page += 1
        rows, page_total = _read_permalink_editor_page(session, page=page)
        if page_total != reported:
            raise RuntimeError(
                "Permalink Manager count mismatch: "
                f"page 1 reported {reported}, page {page} reported {page_total}"
            )
        if not rows:
            raise RuntimeError(
                f"Permalink Manager count mismatch: reported {reported}, exported {len(records)}"
            )

    if len(records) != reported:
        raise RuntimeError(
            f"Permalink Manager count mismatch: reported {reported}, exported {len(records)}"
        )
    try:
        final_settings = _read_permalink_settings(session)
        _final_rows, final_total = _read_permalink_editor_page(session, page=1)
    except Exception as exc:
        raise RuntimeError(f"Permalink Manager source unavailable after export: {exc}") from exc
    if final_settings != (status, query_mode) or final_total != reported:
        raise RuntimeError("Permalink Manager source changed during export")
    return records, reported


def _build_redirect_export(
    session: Optional[requests.Session] = None,
) -> dict[str, Any]:
    """Build one complete normalized export from both active redirect plugins."""
    active_session = session or _wp_admin_session()
    redirection_records, redirection_total = _export_redirection_records(active_session)
    permalink_records, permalink_total = _export_permalink_records(active_session)
    return {
        "schema_version": 1,
        "counts": {
            "redirection": {
                "reported": redirection_total,
                "exported": len(redirection_records),
            },
            "permalink_manager": {
                "reported": permalink_total,
                "exported": len(permalink_records),
            },
            "total": len(redirection_records) + len(permalink_records),
        },
        "records": [*redirection_records, *permalink_records],
    }


def _wp_rest_pagination_header(
    response: requests.Response,
    *,
    header: str,
    resource: str,
    page: int,
) -> int:
    """Read one required non-negative WordPress REST pagination header."""
    value = response.headers.get(header)
    if not isinstance(value, str) or not value.isdigit():
        raise RuntimeError(
            f"WordPress REST shape drift for {resource} page {page}: "
            f"{header} must be a non-negative integer"
        )
    return int(value)


def _read_wp_rest_collection_page(
    session: requests.Session,
    *,
    resource: str,
    fields: tuple[str, ...],
    page: int,
    params: Optional[dict[str, Any]] = None,
) -> tuple[list[dict[str, Any]], int, int]:
    """Read one strictly shaped WordPress REST collection page."""
    endpoint = f"/wp-json/wp/v2/{resource}"
    request_params: dict[str, Any] = {
        "_fields": ",".join(fields),
        "context": "view",
        "orderby": "id",
        "order": "asc",
        "page": page,
        "per_page": WP_REST_PAGE_SIZE,
    }
    request_params.update(params or {})
    response = _read_only_get(
        session,
        urljoin(WP_REST_BASE_URL, resource),
        stage=f"read-only WordPress REST {resource} page {page}",
        headers={"Accept": "application/json"},
        params=request_params,
        timeout=30,
    )
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(
            f"WordPress REST shape drift for {resource} page {page}: malformed JSON: {exc}"
        ) from exc
    if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
        raise RuntimeError(
            f"WordPress REST shape drift for {resource} page {page}: expected an array of objects"
        )
    total = _wp_rest_pagination_header(
        response,
        header="X-WP-Total",
        resource=resource,
        page=page,
    )
    page_count = _wp_rest_pagination_header(
        response,
        header="X-WP-TotalPages",
        resource=resource,
        page=page,
    )
    expected_page_count = (total + WP_REST_PAGE_SIZE - 1) // WP_REST_PAGE_SIZE
    if page_count != expected_page_count:
        raise RuntimeError(
            f"WordPress REST pagination metadata mismatch for {resource} page {page}: "
            f"reported {total} records across {page_count} pages, expected {expected_page_count} pages"
        )
    expected_records = (
        0
        if total == 0
        else min(WP_REST_PAGE_SIZE, total - ((page - 1) * WP_REST_PAGE_SIZE))
    )
    if expected_records < 0 or len(payload) != expected_records:
        raise RuntimeError(
            f"WordPress REST partial pagination for {resource} page {page}: "
            f"expected {expected_records} records, received {len(payload)}"
        )
    return payload, total, page_count


def _export_wp_rest_collection(
    session: requests.Session,
    *,
    resource: str,
    fields: tuple[str, ...],
    params: Optional[dict[str, Any]] = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Export one bounded collection and prove its first page remains stable."""
    first_page, reported, page_count = _read_wp_rest_collection_page(
        session,
        resource=resource,
        fields=fields,
        page=1,
        params=params,
    )
    records = list(first_page)
    for page in range(2, page_count + 1):
        page_records, page_total, current_page_count = _read_wp_rest_collection_page(
            session,
            resource=resource,
            fields=fields,
            page=page,
            params=params,
        )
        if page_total != reported or current_page_count != page_count:
            raise RuntimeError(
                f"WordPress REST pagination metadata changed during {resource} export"
            )
        records.extend(page_records)
    if len(records) != reported:
        raise RuntimeError(
            f"WordPress REST count mismatch for {resource}: "
            f"reported {reported}, exported {len(records)}"
        )
    replay, replay_total, replay_page_count = _read_wp_rest_collection_page(
        session,
        resource=resource,
        fields=fields,
        page=1,
        params=params,
    )
    if replay != first_page or replay_total != reported or replay_page_count != page_count:
        raise RuntimeError(f"WordPress REST {resource} source changed during export")
    return records, {
        "resource": resource,
        "endpoint": f"/wp-json/wp/v2/{resource}",
        "page_size": WP_REST_PAGE_SIZE,
        "page_count": page_count,
        "reported_count": reported,
        "exported_count": len(records),
        "stability_check": "page_1_replay",
    }


def _require_relationship_shape(
    record: dict[str, Any],
    *,
    resource: str,
    fields: tuple[str, ...],
) -> None:
    """Reject missing or unexpected fields from a narrowed REST response."""
    expected = set(fields)
    actual = set(record)
    if actual != expected:
        raise RuntimeError(
            f"WordPress REST shape drift for {resource}: "
            f"expected fields {sorted(expected)}, got {sorted(actual)}"
        )


def _require_relationship_id(value: Any, *, resource: str, field: str) -> int:
    """Return a required positive WordPress entity ID."""
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RuntimeError(f"{resource} record {field} must be a positive integer")
    return value


def _require_relationship_string(
    value: Any,
    *,
    resource: str,
    field: str,
    allow_empty: bool = False,
) -> str:
    """Return a required WordPress REST string without substituting a fallback."""
    if not isinstance(value, str) or (not allow_empty and not value):
        qualifier = "a string" if allow_empty else "a non-empty string"
        raise RuntimeError(f"{resource} record {field} must be {qualifier}")
    return value


def _ordered_relationship_ids(value: Any, *, resource: str, field: str) -> list[int]:
    """Validate an ID array and deduplicate it without changing source order."""
    if not isinstance(value, list):
        raise RuntimeError(f"{resource} record {field} must be an array")
    result: list[int] = []
    seen: set[int] = set()
    for item in value:
        entity_id = _require_relationship_id(item, resource=resource, field=field)
        if entity_id not in seen:
            seen.add(entity_id)
            result.append(entity_id)
    return result


def _normalize_relationship_post(record: dict[str, Any]) -> dict[str, Any]:
    """Normalize one published post relationship record."""
    fields = ("id", "slug", "author", "categories", "tags", "status", "modified")
    _require_relationship_shape(record, resource="posts", fields=fields)
    wp_id = _require_relationship_id(record["id"], resource="posts", field="id")
    status = _require_relationship_string(record["status"], resource="posts", field="status")
    if status != "publish":
        raise RuntimeError(f"WordPress REST returned non-published post {wp_id}: status={status}")
    return {
        "wp_id": wp_id,
        "slug": _require_relationship_string(record["slug"], resource="posts", field="slug"),
        "author_id": _require_relationship_id(
            record["author"], resource="posts", field="author"
        ),
        "category_ids": _ordered_relationship_ids(
            record["categories"], resource="posts", field="categories"
        ),
        "tag_ids": _ordered_relationship_ids(record["tags"], resource="posts", field="tags"),
        "status": status,
        "modified": _require_relationship_string(
            record["modified"], resource="posts", field="modified"
        ),
    }


def _normalize_relationship_author(record: dict[str, Any]) -> dict[str, Any]:
    """Normalize one complete referenced author profile."""
    fields = ("id", "slug", "name", "description", "url", "link", "avatar_urls")
    _require_relationship_shape(record, resource="users", fields=fields)
    avatar_urls = record["avatar_urls"]
    if (
        not isinstance(avatar_urls, dict)
        or not avatar_urls
        or any(
            not isinstance(size, str)
            or not size
            or not isinstance(url, str)
            or not url
            for size, url in avatar_urls.items()
        )
    ):
        raise RuntimeError("users record avatar_urls must be a non-empty string map")
    return {
        "author_id": _require_relationship_id(record["id"], resource="users", field="id"),
        "slug": _require_relationship_string(record["slug"], resource="users", field="slug"),
        "name": _require_relationship_string(record["name"], resource="users", field="name"),
        "description": _require_relationship_string(
            record["description"], resource="users", field="description", allow_empty=True
        ),
        "url": _require_relationship_string(
            record["url"], resource="users", field="url", allow_empty=True
        ),
        "link": _require_relationship_string(record["link"], resource="users", field="link"),
        "avatar_urls": dict(avatar_urls),
    }


def _normalize_relationship_term(
    record: dict[str, Any],
    *,
    resource: str,
    id_field: str,
) -> dict[str, Any]:
    """Normalize one complete category or tag profile."""
    fields = ("id", "slug", "name", "description")
    _require_relationship_shape(record, resource=resource, fields=fields)
    return {
        id_field: _require_relationship_id(record["id"], resource=resource, field="id"),
        "slug": _require_relationship_string(record["slug"], resource=resource, field="slug"),
        "name": _require_relationship_string(record["name"], resource=resource, field="name"),
        "description": _require_relationship_string(
            record["description"], resource=resource, field="description", allow_empty=True
        ),
    }


def _index_relationship_records(
    records: list[dict[str, Any]],
    *,
    id_field: str,
) -> dict[int, dict[str, Any]]:
    """Index normalized records while rejecting duplicate IDs or slugs."""
    indexed: dict[int, dict[str, Any]] = {}
    slugs: set[str] = set()
    for record in records:
        entity_id = record[id_field]
        slug = record["slug"]
        if entity_id in indexed:
            raise RuntimeError(f"duplicate {id_field} {entity_id}")
        if slug in slugs:
            raise RuntimeError(f"duplicate slug {slug} in {id_field} records")
        indexed[entity_id] = record
        slugs.add(slug)
    return indexed


def _missing_relationship_ids(
    referenced: set[int],
    available: set[int],
    *,
    entity: str,
) -> None:
    """Fail when a post references an entity absent from its complete export."""
    missing = sorted(referenced - available)
    if missing:
        values = ",".join(str(value) for value in missing)
        raise RuntimeError(f"missing referenced {entity} IDs: {values}")


def _build_relationship_export(
    session: Optional[requests.Session] = None,
) -> dict[str, Any]:
    """Build a strict read-only post relationship and entity-profile export."""
    active_session = session or _wp_admin_session()
    post_fields = ("id", "slug", "author", "categories", "tags", "status", "modified")
    raw_posts, posts_metadata = _export_wp_rest_collection(
        active_session,
        resource="posts",
        fields=post_fields,
        params={"status": "publish"},
    )
    posts = [_normalize_relationship_post(record) for record in raw_posts]
    _index_relationship_records(posts, id_field="wp_id")

    referenced_author_ids = {post["author_id"] for post in posts}
    referenced_category_ids = {
        category_id for post in posts for category_id in post["category_ids"]
    }
    referenced_tag_ids = {tag_id for post in posts for tag_id in post["tag_ids"]}

    author_fields = ("id", "slug", "name", "description", "url", "link", "avatar_urls")
    raw_authors, authors_metadata = _export_wp_rest_collection(
        active_session,
        resource="users",
        fields=author_fields,
        params={"include": ",".join(str(value) for value in sorted(referenced_author_ids))},
    )
    authors = [_normalize_relationship_author(record) for record in raw_authors]
    author_index = _index_relationship_records(authors, id_field="author_id")
    unexpected_authors = sorted(set(author_index) - referenced_author_ids)
    if unexpected_authors:
        raise RuntimeError(
            "WordPress REST users include filter returned unreferenced author IDs: "
            + ",".join(str(value) for value in unexpected_authors)
        )

    term_fields = ("id", "slug", "name", "description")
    raw_categories, categories_metadata = _export_wp_rest_collection(
        active_session,
        resource="categories",
        fields=term_fields,
        params={"hide_empty": "false"},
    )
    categories = [
        _normalize_relationship_term(record, resource="categories", id_field="category_id")
        for record in raw_categories
    ]
    category_index = _index_relationship_records(categories, id_field="category_id")

    raw_tags, tags_metadata = _export_wp_rest_collection(
        active_session,
        resource="tags",
        fields=term_fields,
        params={"hide_empty": "false"},
    )
    tags = [
        _normalize_relationship_term(record, resource="tags", id_field="tag_id")
        for record in raw_tags
    ]
    tag_index = _index_relationship_records(tags, id_field="tag_id")

    _missing_relationship_ids(
        referenced_author_ids,
        set(author_index),
        entity="author",
    )
    _missing_relationship_ids(
        referenced_category_ids,
        set(category_index),
        entity="category",
    )
    _missing_relationship_ids(referenced_tag_ids, set(tag_index), entity="tag")

    return {
        "schema_version": 1,
        "producer": {
            "tool": "ata-blog",
            "command": "ata-blog wordpress-admin relationships export",
            "source": "WordPress REST API",
            "api_namespace": "wp/v2",
            "resources": {
                "posts": posts_metadata,
                "authors": authors_metadata,
                "categories": categories_metadata,
                "tags": tags_metadata,
            },
        },
        "counts": {
            "posts": len(posts),
            "authors": len(authors),
            "categories": len(categories),
            "tags": len(tags),
            "posts_without_tags": sum(not post["tag_ids"] for post in posts),
            "referenced_author_ids": len(referenced_author_ids),
            "referenced_category_ids": len(referenced_category_ids),
            "referenced_tag_ids": len(referenced_tag_ids),
        },
        "posts": posts,
        "authors": authors,
        "categories": categories,
        "tags": tags,
    }


def _wp_admin_upgrade_plugin_files() -> set[str]:
    """Return plugin files listed on wp-admin's upgrade-filtered plugins screen."""
    session = _wp_admin_session()
    _force_wp_plugin_update_check(session)
    plugins_page = session.get(urljoin(WP_ADMIN_BASE_URL, "plugins.php?plugin_status=upgrade"), timeout=30)
    plugins_page.raise_for_status()
    if "wp-login.php" in plugins_page.url:
        raise RuntimeError("plugins.php upgrade view request was redirected to wp-login.php after login")
    return set(re.findall(r'<tr[^>]+class="[^"]*plugin-update-tr[^"]*"[^>]+data-plugin="([^"]+)"', plugins_page.text))


def _annotate_plugin_update_contradictions(report: dict) -> dict:
    """Mark health-report plugin updates that WordPress admin does not offer to update."""
    plugins = report.get("plugins")
    if not isinstance(plugins, dict):
        return report
    updates_available = plugins.get("updates_available")
    if not isinstance(updates_available, list) or not updates_available:
        return report

    upgrade_files = _wp_admin_upgrade_plugin_files()
    stale_updates = []
    confirmed_updates = []
    for plugin in updates_available:
        if not isinstance(plugin, dict):
            confirmed_updates.append(plugin)
            continue
        plugin_path = plugin.get("plugin")
        if not isinstance(plugin_path, str):
            confirmed_updates.append(plugin)
            continue
        plugin_file = _plugin_file_from_rest_path(plugin_path)
        if plugin_file in upgrade_files:
            confirmed_updates.append(plugin)
            continue
        stale_plugin = dict(plugin)
        stale_plugin["update_status"] = "stale_update_state"
        stale_plugin["update_state_reason"] = (
            "WordPress.org reports a newer version, but wp-admin's refreshed plugin update screen "
            "does not offer this plugin for update. Treat as stale/contradictory until WordPress "
            "update transients and REST readback agree."
        )
        stale_updates.append(stale_plugin)

    if not stale_updates:
        return report

    plugins["updates_available"] = confirmed_updates
    plugins["updates_available_count"] = len(confirmed_updates)
    plugins["stale_update_state"] = stale_updates
    plugins["stale_update_state_count"] = len(stale_updates)

    items = plugins.get("items")
    if isinstance(items, list):
        by_plugin = {item.get("plugin"): item for item in stale_updates if isinstance(item, dict)}
        for index, item in enumerate(items):
            if isinstance(item, dict) and item.get("plugin") in by_plugin:
                items[index] = by_plugin[item.get("plugin")]
    return report


def _clear_wpengine_all_caches() -> dict:
    """Clear all WP Engine environment caches through the authenticated cache plugin REST endpoint."""
    session = _wp_admin_session()
    caching_page = session.get(urljoin(WP_ADMIN_BASE_URL, "admin.php?page=wpengine-common&tab=caching"), timeout=30)
    caching_page.raise_for_status()
    if "wp-login.php" in caching_page.url:
        raise RuntimeError("WP Engine caching page request was redirected to wp-login.php after login")

    path_match = re.search(r'"clear_all_caches_path"\s*:\s*"([^"]+)"', caching_page.text)
    if not path_match:
        raise RuntimeError("Could not find WP Engine clear-all-caches REST path on caching page")

    rest_url = "https://adamtheautomator.com/wp-json/" + path_match.group(1)
    response = session.post(
        rest_url,
        headers={"X-WP-Nonce": _extract_wp_api_nonce(caching_page.text), "Accept": "application/json"},
        timeout=60,
    )
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"WP Engine cache clear returned non-JSON output: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("WP Engine cache clear returned non-object JSON")
    if payload.get("success") is not True:
        raise RuntimeError(f"WP Engine cache clear failed: {payload}")
    return payload


def _get_plugin_for_mutation(plugin: str) -> dict:
    """Read a plugin record before a wp-admin mutation."""
    record = _run_wordpress_json([
        "plugins",
        "get",
        plugin,
        "--properties",
        "plugin,name,version,status,update_status,latest_version",
    ])
    if not record.get("plugin"):
        raise RuntimeError("wordpress plugins get did not return a plugin path")
    return record


def _upgrade_plugin_and_verify(plugin: str) -> dict:
    """Upgrade a plugin through wp-admin/admin-ajax and verify REST readback."""
    before = _get_plugin_for_mutation(plugin)
    plugin_path = str(before["plugin"])
    if before.get("update_status") != "available":
        raise RuntimeError(f"Plugin {plugin} does not have an available update")
    latest_version = before.get("latest_version")
    if not latest_version:
        raise RuntimeError(f"Plugin {plugin} does not have a known latest version")

    try:
        ajax_payload = _upgrade_plugin_via_wp_admin_ajax(plugin_path)
    except WPAdminAjaxError as exc:
        if _ajax_error_message(exc.payload).casefold() != "the plugin is at the latest version.":
            raise
        after_latest_error = _get_plugin_for_mutation(plugin_path)
        if after_latest_error.get("version") == latest_version and after_latest_error.get("update_status") == "current":
            return {
                "before": before,
                "after": after_latest_error,
                "wp_admin_ajax": exc.payload,
                "note": "wp-admin reported the plugin was already latest; REST readback verified current state after refresh",
            }
        raise RuntimeError(
            f"WordPress update state contradiction for {plugin_path}: REST/health readback reports "
            f"installed {after_latest_error.get('version')}, latest {after_latest_error.get('latest_version')}, "
            f"status {after_latest_error.get('update_status')}, but wp-admin admin-ajax reported "
            "'The plugin is at the latest version.' The ATA CLI refreshed WordPress update checks before "
            "the updater call; rerun health-report and treat this plugin as stale/contradictory until "
            "WordPress update transient/readback agree."
        ) from exc
    after = _get_plugin_for_mutation(plugin_path)
    if after.get("version") != latest_version or after.get("update_status") != "current":
        raise RuntimeError(
            f"Plugin {plugin_path} update did not verify: installed {after.get('version')}, "
            f"latest {after.get('latest_version')}, status {after.get('update_status')}"
        )
    return {"before": before, "after": after, "wp_admin_ajax": ajax_payload}


def _delete_plugin_and_verify(plugin: str) -> dict:
    """Delete an inactive plugin through wp-admin/admin-ajax and verify absence."""
    before = _get_plugin_for_mutation(plugin)
    plugin_path = str(before["plugin"])
    if before.get("status") != "inactive":
        raise RuntimeError(f"Plugin {plugin_path} is {before.get('status')}; deactivate it before deleting")

    ajax_payload = _delete_plugin_via_wp_admin_ajax(plugin_path)
    get_result = subprocess.run(
        ["wordpress", "admin", *_wordpress_profile_args(), "plugins", "get", plugin_path],
        capture_output=True,
        text=True,
    )
    if get_result.returncode == 0:
        raise RuntimeError(f"Plugin {plugin_path} delete did not verify absent")
    not_found_text = f"{get_result.stderr}\n{get_result.stdout}"
    if "not found" not in not_found_text.lower() and "not installed" not in not_found_text.lower():
        raise RuntimeError(f"Plugin {plugin_path} delete verification failed: {not_found_text.strip()}")
    return {"before": before, "deleted": True, "wp_admin_ajax": ajax_payload}


@app.command("security-scan")
@command
def security_scan(
    active_only: bool = typer.Option(False, "--active-only", help="Scan only active plugins plus all themes"),
    table: bool = typer.Option(False, "--table", "-t", help="Display affected components as a table"),
) -> None:
    """Scan installed plugins and themes for known vulnerabilities."""
    args = ["security-scan"]
    if active_only:
        args.append("--active-only")
    if table:
        args.append("--table")
    _run_wordpress(args)


@app.command("health-report")
@command
def health_report(
    table: bool = typer.Option(False, "--table", "-t", help="Display summary as a table"),
) -> None:
    """Emit a structured WordPress maintenance health report."""
    if table:
        _run_wordpress(["health-report", "--table"])
        return
    try:
        result = _run_wordpress_json(["health-report"])
        result = _annotate_plugin_update_contradictions(result)
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    typer.echo(json.dumps(result, indent=2))
    raise typer.Exit(0)


@cache_app.command("clear-all")
@command
def cache_clear_all() -> None:
    """Clear all WP Engine environment caches through wp-admin."""
    try:
        result = _clear_wpengine_all_caches()
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    typer.echo(json.dumps(result, indent=2))
    raise typer.Exit(0)


@redirects_app.command("export")
@command
def redirects_export() -> None:
    """Export complete normalized Redirection and Permalink Manager records."""
    try:
        result = _build_redirect_export()
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    typer.echo(json.dumps(result, indent=2))
    raise typer.Exit(0)


@relationships_app.command("export")
@command
def relationships_export() -> None:
    """Export published post relationships and complete entity profiles."""
    try:
        result = _build_relationship_export()
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    typer.echo(json.dumps(result, indent=2))
    raise typer.Exit(0)


@plugins_app.command("list")
@command
def plugins_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table instead of JSON"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum plugins to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Forwarded filter expressions for wordpress admin"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status (active, inactive)"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
) -> None:
    """List installed WordPress plugins as JSON by default."""
    args = ["plugins", "list"]
    if table:
        args.append("--table")
    if limit is not None:
        args.extend(["--limit", str(limit)])
    if filter:
        for value in filter:
            args.extend(["--filter", value])
    if status:
        args.extend(["--status", status])
    if properties:
        args.extend(["--properties", properties])
    _run_wordpress(args)


@plugins_app.command("get")
@command
def plugins_get(
    plugin: str = typer.Argument(..., help="Plugin path, slug, textdomain, or exact name from plugins list"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
) -> None:
    """Get details for a specific WordPress plugin."""
    args = ["plugins", "get", plugin]
    if table:
        args.append("--table")
    if properties:
        args.extend(["--properties", properties])
    _run_wordpress(args)


@plugins_app.command("activate")
@command
def plugins_activate(plugin: str = typer.Argument(..., help="Plugin identifier")) -> None:
    """Activate a WordPress plugin."""
    _run_wordpress(["plugins", "activate", plugin])


@plugins_app.command("deactivate")
@command
def plugins_deactivate(plugin: str = typer.Argument(..., help="Plugin identifier")) -> None:
    """Deactivate a WordPress plugin."""
    _run_wordpress(["plugins", "deactivate", plugin])


@plugins_app.command("delete")
@command
def plugins_delete(plugin: str = typer.Argument(..., help="Plugin identifier")) -> None:
    """Delete an inactive WordPress plugin through wp-admin's native AJAX deleter and verify absence."""
    try:
        result = _delete_plugin_and_verify(plugin)
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    typer.echo(json.dumps(result, indent=2))
    raise typer.Exit(0)


@plugins_app.command("install")
@command
def plugins_install(
    slug: str = typer.Argument(..., help="Plugin slug from wordpress.org"),
    activate: bool = typer.Option(False, "--activate", "-a", help="Activate after installation"),
) -> None:
    """Install a plugin from wordpress.org."""
    args = ["plugins", "install", slug]
    if activate:
        args.append("--activate")
    _run_wordpress(args)


@plugins_app.command("upgrade")
@command
def plugins_upgrade(plugin: str = typer.Argument(..., help="Plugin identifier")) -> None:
    """Upgrade a plugin through wp-admin's native AJAX updater and verify readback."""
    try:
        result = _upgrade_plugin_and_verify(plugin)
    except Exception as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)
    typer.echo(json.dumps(result, indent=2))
    raise typer.Exit(0)


@themes_app.command("list")
@command
def themes_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: Optional[int] = typer.Option(None, "--limit", "-l", help="Maximum themes to return"),
    filter: Optional[List[str]] = typer.Option(None, "--filter", "-f", help="Forwarded filter expressions for wordpress admin"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
) -> None:
    """List installed WordPress themes."""
    args = ["themes", "list"]
    if table:
        args.append("--table")
    if limit is not None:
        args.extend(["--limit", str(limit)])
    if filter:
        for value in filter:
            args.extend(["--filter", value])
    if status:
        args.extend(["--status", status])
    if properties:
        args.extend(["--properties", properties])
    _run_wordpress(args)


@themes_app.command("get")
@command
def themes_get(
    theme: str = typer.Argument(..., help="Theme stylesheet, textdomain, or exact name from themes list"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    properties: Optional[str] = typer.Option(None, "--properties", "-p", help="Comma-separated fields to display"),
) -> None:
    """Get details for a specific WordPress theme."""
    args = ["themes", "get", theme]
    if table:
        args.append("--table")
    if properties:
        args.extend(["--properties", properties])
    _run_wordpress(args)


@themes_app.command("file-push")
@command
def themes_file_push(
    theme: str = typer.Argument(..., help="Theme directory name under wp-content/themes"),
    local_file: str = typer.Argument(..., help="Local file to upload"),
    remote_file: str = typer.Argument(..., help="Relative destination path inside the theme"),
    remote_root: str = typer.Option(..., "--remote-root", help="Absolute remote WordPress root path"),
    host: str = typer.Option(..., "--host", help="SSH host"),
    user: Optional[str] = typer.Option(None, "--user", help="SSH user"),
    port: int = typer.Option(22, "--port", help="SSH port"),
    identity_file: Optional[str] = typer.Option(None, "--identity-file", help="SSH identity file"),
    backup: bool = typer.Option(False, "--backup", help="Back up the existing remote file before overwrite"),
    yes: bool = typer.Option(False, "--yes", help="Upload and overwrite the remote file"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show readback without uploading"),
) -> None:
    """Push a local file to a remote WordPress theme through SSH/SFTP."""
    args = [
        "themes",
        "file-push",
        theme,
        local_file,
        remote_file,
        "--remote-root",
        remote_root,
        "--host",
        host,
        "--port",
        str(port),
    ]
    if user:
        args.extend(["--user", user])
    if identity_file:
        args.extend(["--identity-file", identity_file])
    if backup:
        args.append("--backup")
    if yes:
        args.append("--yes")
    if dry_run:
        args.append("--dry-run")
    _run_wordpress(args, include_profile=False)
