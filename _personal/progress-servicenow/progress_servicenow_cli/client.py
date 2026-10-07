"""Progress ServiceNow client.

The base implementation is loaded from preserved bytecode. The catalog-item
methods below are maintained as source because the Employee Center catalog can
no longer be reached the way the bytecode implementation assumed:

* ``?id=search&q=<name>`` renders its results inside shadow DOM, so
  ``page.get_by_role("link")`` cannot see a single catalog result. The bytecode
  ``_navigate_to_catalog_form`` scraped those links, swallowed the resulting
  errors, and reported "Could not find catalog item ... in search results".
* The ``Development Cloud Issue`` catalog item that ``list_products`` navigated
  to (``sys_id=c9f3a854dbe5db0408f33a1b7c9619dc``) is retired. The live form
  answers "You are either not authorized or record is not valid.", so the
  Product dropdown never rendered and the product list came back empty.

Both are replaced with the authenticated ``sn_sc`` Service Catalog API, which
returns catalog items, their variables, and each variable's choice list
directly. Every replacement fails loudly and names what it looked for.
"""

import re
from typing import Dict, List, Optional
from urllib.parse import urlsplit

from cli_tools_shared.exceptions import ClientError

from . import catalog_api, parsers
from ._bytecode import load_module_bytecode
from .config import get_config as _get_config


def _browser_automation_contract_marker():
    browser = _get_config().get_browser()
    return browser.get_page, browser.close


load_module_bytecode(__name__, globals())

#: Template registry key whose catalog item owns the shared Product dropdown.
PRODUCT_TEMPLATE_KEY = "other_development_request"

#: Template registry key for the Product field on that catalog item.
PRODUCT_FIELD_KEY = "product"

#: Heading of the modal ServiceNow opens to name a new draft.
DRAFT_MODAL_MARKER = 'dialog "Catalog item save"'

#: Text ServiceNow renders on the catalog form after a draft is stored.
DRAFT_SAVED_MARKER = "Your item has been saved in My Requests."


# ---------------------------------------------------------------------------
# Authentication guard.
#
# progress1.service-now.com authenticates through the Progress Entra tenant. An
# expired session does not produce an error page: ServiceNow 302s to
# ``login.microsoftonline.com``, which returns a perfectly parseable sign-in
# page. Left unguarded, the snapshot parsers happily read that page and report
# its heading ("Enter password") as a ticket description, or find no ticket rows
# and report an empty, successful result.
#
# Every read path in this client funnels through ``_navigate`` and ``_snapshot``,
# so both are guarded here: reaching a non-ServiceNow host, or a ServiceNow
# login page, is a hard failure with a non-zero exit — never an empty result and
# never login-page fields returned as data.
# ---------------------------------------------------------------------------

#: Host that must serve every page this client parses.
SERVICENOW_HOST_SUFFIX = "service-now.com"

#: Identity providers that front ServiceNow for this tenant.
SSO_HOST_PATTERN = re.compile(
    r"(^|\.)(login\.microsoftonline\.com|login\.microsoft\.com|"
    r"login\.windows\.net|secure\.progress\.com)$",
    re.IGNORECASE,
)

#: ServiceNow's own login page, served from the ServiceNow host.
SERVICENOW_LOGIN_QUERY_PATTERN = re.compile(r"(^|&)id=(login|logout)(&|$)", re.IGNORECASE)

#: Headings the Microsoft sign-in page renders. Present in an aria snapshot
#: taken from the SSO page even when the URL check is inconclusive.
SSO_SNAPSHOT_MARKERS = (
    "Sign in to your account",
    'heading "Enter password"',
    'heading "Pick an account"',
    'heading "Approve sign in request"',
    'heading "Verify your identity"',
)

_REAUTH_HINT = (
    "The saved browser session has expired. Refresh it with "
    "'progress-servicenow auth login --force', then retry."
)


def _raise_if_not_servicenow(url: str) -> None:
    """Fail loudly when the browser is not on an authenticated ServiceNow page.

    Raises:
        ClientError: When the current URL belongs to the SSO identity provider,
            to any non-ServiceNow host, or to ServiceNow's own login page.
    """
    parts = urlsplit(url)
    host = parts.netloc.split("@")[-1].split(":")[0]

    if SSO_HOST_PATTERN.search(host):
        raise ClientError(
            f"Not authenticated: ServiceNow redirected to the SSO login page at {host} "
            f"instead of returning ServiceNow data. {_REAUTH_HINT}"
        )
    if not host.endswith(SERVICENOW_HOST_SUFFIX):
        raise ClientError(
            f"Not authenticated: expected a page on {SERVICENOW_HOST_SUFFIX} but the "
            f"browser is on {host or url!r}. {_REAUTH_HINT}"
        )
    if SERVICENOW_LOGIN_QUERY_PATTERN.search(parts.query):
        raise ClientError(
            f"Not authenticated: ServiceNow served its own login page ({url}) instead of "
            f"the requested record. {_REAUTH_HINT}"
        )


def _raise_if_login_snapshot(snapshot: str, url: str) -> None:
    """Fail loudly when a captured page is an SSO sign-in page.

    Raises:
        ClientError: When the accessibility snapshot carries a sign-in page
            marker, so login-page fields can never be parsed as ticket data.
    """
    for marker in SSO_SNAPSHOT_MARKERS:
        if marker in snapshot:
            raise ClientError(
                f"Not authenticated: the page at {url} is the SSO login page (it renders "
                f"{marker!r}), not ServiceNow data. {_REAUTH_HINT}"
            )


_bytecode_navigate = ProgressServicenowClient._navigate
_bytecode_snapshot = ProgressServicenowClient._snapshot


def _guarded_navigate(self, url: str) -> None:
    """Navigate, then refuse to continue if the session bounced to SSO."""
    _bytecode_navigate(self, url)
    _raise_if_not_servicenow(self._svc._get_page().url)


def _guarded_snapshot(self) -> str:
    """Capture a page snapshot only from an authenticated ServiceNow page."""
    page_url = self._svc._get_page().url
    _raise_if_not_servicenow(page_url)
    snapshot = _bytecode_snapshot(self)
    _raise_if_login_snapshot(snapshot, page_url)
    return snapshot


def _catalog_page(self):
    """Return an authenticated ServiceNow page that can call the catalog API."""
    self._ensure_browser()
    page = self._svc._get_page()
    if SERVICENOW_HOST_SUFFIX not in page.url:
        self._navigate(self.config.base_url)
        self._wait(2000)
        page = self._svc._get_page()
    _raise_if_not_servicenow(page.url)
    return page


def _catalog_item_definition(self, sys_id: str) -> Dict:
    """Fetch one live catalog item definition (name, category, variables)."""
    return catalog_api.get_item(_catalog_page(self), sys_id)


def _resolve_catalog_sys_id(self, template_data: Dict) -> str:
    """Resolve a template registry entry to a live catalog item sys_id."""
    sys_id = template_data.get("sys_id")
    if sys_id:
        return str(sys_id)
    name = template_data.get("name")
    if not name:
        raise ClientError(
            "Template entry has neither a sys_id nor a name, so its catalog item "
            "cannot be resolved. Run 'progress-servicenow ticket template refresh'."
        )
    return catalog_api.resolve_item_sys_id(_catalog_page(self), str(name))


def _navigate_to_catalog_form(self, template_data: Optional[Dict] = None,
                              url: Optional[str] = None) -> None:
    """Open a catalog item form in the authenticated browser.

    Exactly one of ``template_data`` or ``url`` must be provided. Template
    entries are resolved through their ``sys_id`` (or, when absent, through an
    exact name match against the live Service Catalog API) and opened directly.
    The Employee Center search page is never scraped: its results live in shadow
    DOM and are invisible to DOM locators.
    """
    if (template_data is None) == (url is None):
        raise ClientError(
            "_navigate_to_catalog_form requires exactly one of template_data or url."
        )

    self._ensure_browser()

    if url is None:
        sys_id = _resolve_catalog_sys_id(self, template_data)
        url = f"?id=sc_cat_item&sys_id={sys_id}"

    if not url.startswith("http"):
        url = f"{self.config.base_url}{url}"

    self._navigate(url)
    self._wait(5000)
    self._dismiss_loading_overlay()
    self._wait(2000)
    self._dismiss_loading_overlay()

    snapshot = self._snapshot()
    if "not authorized or record is not valid" in snapshot:
        raise ClientError(
            f"ServiceNow refused the catalog item form at {url}: the page reports "
            "'You are either not authorized or record is not valid.' The catalog "
            "item is retired or not visible to this account. Run "
            "'progress-servicenow ticket template refresh' to resync the registry."
        )


def _live_product_options(self) -> List[str]:
    """Read the live Product dropdown options from the owning catalog item.

    Raises:
        ClientError: When the template registry, the live catalog item, the
            Product variable, or its choice list is missing. An empty product
            list is never returned as a success.
    """
    from .template_data import load_ticket_template

    catalog_items = load_ticket_template()["catalog_items"]
    entry = catalog_items.get(PRODUCT_TEMPLATE_KEY)
    if entry is None:
        raise ClientError(
            f"Template registry has no {PRODUCT_TEMPLATE_KEY!r} entry, so the Product "
            f"dropdown owner is unknown. Available keys: {', '.join(sorted(catalog_items))}. "
            "Run 'progress-servicenow ticket template refresh'."
        )

    definition = catalog_api.find_field(entry, PRODUCT_FIELD_KEY)
    if definition is None:
        fields = entry.get("fields") or {}
        raise ClientError(
            f"Template {PRODUCT_TEMPLATE_KEY!r} has no {PRODUCT_FIELD_KEY!r} field, so the "
            f"Product dropdown cannot be located. Fields: {', '.join(sorted(fields))}. "
            "Run 'progress-servicenow ticket template refresh'."
        )

    variable_name = definition.get("variable")
    sys_id = _resolve_catalog_sys_id(self, entry)
    item = _catalog_item_definition(self, sys_id)
    for variable in catalog_api.flatten_variables(item.get("variables", [])):
        if variable.get("name") != variable_name:
            continue
        options = catalog_api.variable_options(variable)
        if not options:
            raise ClientError(
                f"The live Product dropdown (variable {variable_name!r} on catalog item "
                f"{sys_id} '{item.get('name')}') returned no choices. The form's option "
                "list did not load or the variable no longer publishes choices."
            )
        return options

    available = ", ".join(
        str(variable.get("name"))
        for variable in catalog_api.flatten_variables(item.get("variables", []))
    )
    raise ClientError(
        f"Catalog item {sys_id} '{item.get('name')}' has no variable named "
        f"{variable_name!r}. Live variables: {available}. "
        "Run 'progress-servicenow ticket template refresh'."
    )


def _list_products(self) -> List[str]:
    """List the live Product dropdown options for the development catalog form."""
    return _live_product_options(self)


def _form_field_ref(snapshot: str, definition: Dict, field_key: str) -> str:
    """Resolve the live form ref for one template field, by its exact label."""
    label = str(definition.get("label") or "").strip()
    parsed = parsers.parse_form_fields(snapshot)
    for candidate in parsed:
        if str(candidate.get("label", "")).strip().lower() == label.lower():
            return str(candidate["ref"])
    found = ", ".join(repr(str(candidate.get("label"))) for candidate in parsed) or "no fields"
    raise ClientError(
        f"Could not find field {field_key!r} (label {label!r}, type "
        f"{definition.get('type')!r}) on the live form. Fields present: {found}."
    )


def _validate_field_value(field_key: str, definition: Dict, value: str) -> None:
    """Reject a value that the live template says the field does not accept."""
    options = definition.get("options")
    if options and value not in options:
        raise ClientError(
            f"Value {value!r} is not a valid option for field {field_key!r} "
            f"(label {definition.get('label')!r}). Valid options: {', '.join(options)}."
        )


# The ESC catalog form binds every variable through Angular with
# ``ng-model-options="{getterSetter: true}"``, so writing the native control (or
# even the Select2 widget) is reverted on the next digest. ServiceNow's own
# GlideForm API on the form scope is the supported writer, and it updates the
# model, the native control, and the Select2/TinyMCE widget together.
_SET_FIELD_JS = """(payload) => {
    const {name, value, kind} = payload;
    const el = document.querySelector('[name="' + name + '"]');
    if (!el) return {ok: false, error: 'no form control named ' + name};
    if (!window.angular) return {ok: false, error: 'Angular is not loaded on this page'};
    const scope = window.angular.element(el).scope();
    if (!scope || typeof scope.getGlideForm !== 'function') {
        return {ok: false, error: 'no GlideForm scope for ' + name};
    }
    const gf = scope.getGlideForm();
    if (!gf || typeof gf.setValue !== 'function') {
        return {ok: false, error: 'GlideForm exposes no setValue for ' + name};
    }
    if (typeof gf.hasField === 'function' && !gf.hasField(name)) {
        return {ok: false, error: 'the live form has no variable named ' + name};
    }

    let target = value;
    if (kind === 'checkbox') {
        target = ['true', 'yes', '1', 'checked'].includes(value.trim().toLowerCase())
            ? 'true' : 'false';
    } else if (kind === 'dropdown' && el.tagName === 'SELECT') {
        const options = Array.from(el.options);
        const match = options.find(o => (o.text || '').trim() === value.trim());
        if (!match) {
            return {ok: false, error: 'option not present on the live form',
                    options: options.map(o => (o.text || '').trim())};
        }
        target = match.value;
    } else if (kind === 'html') {
        target = value.split('\\n').map(line =>
            '<p>' + line.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            + '</p>').join('');
    }

    try {
        gf.setValue(name, target);
    } catch (e) {
        return {ok: false, error: 'GlideForm.setValue failed: ' + String(e)};
    }
    try { scope.$apply(); } catch (e) { /* already inside a digest */ }

    const applied = typeof gf.getValue === 'function' ? gf.getValue(name) : null;
    if (String(applied) !== String(target)) {
        return {ok: false, error: 'GlideForm.setValue did not stick; the form still holds '
                + JSON.stringify(applied)};
    }
    return {ok: true, applied: applied};
}"""


def _apply_field(self, snapshot: str, field_key: str, definition: Dict, value: str) -> None:
    """Fill a single form field according to its live ServiceNow type."""
    field_type = definition.get("type")

    if field_type == "reference":
        ref = _form_field_ref(snapshot, definition, field_key)
        locator = self._resolve_ref(ref)
        locator.fill(value)
        self._wait(1500)
        locator.press("Enter")
        self._wait(1000)
        return

    variable = definition.get("variable")
    if not variable:
        raise ClientError(
            f"Field {field_key!r} has no ServiceNow variable name in the template "
            "registry. Run 'progress-servicenow ticket template refresh'."
        )

    if field_type == "dropdown":
        kind = "dropdown"
    elif field_type == "checkbox":
        kind = "checkbox"
    elif field_type == "textarea" and definition.get("sn_type") == "html":
        kind = "html"
    elif field_type in ("textarea", "text"):
        kind = "value"
    else:
        raise ClientError(
            f"Field {field_key!r} has unsupported template type {field_type!r}. "
            "Run 'progress-servicenow ticket template refresh'."
        )

    result = self._svc._get_page().evaluate(
        _SET_FIELD_JS, {"name": variable, "value": value, "kind": kind}
    )
    if not result.get("ok"):
        detail = result.get("error")
        options = result.get("options")
        if options:
            detail = f"{detail}; live options: {', '.join(options)}"
        raise ClientError(
            f"Could not set field {field_key!r} (variable {variable!r}, label "
            f"{definition.get('label')!r}) to {value!r} on the live form: {detail}"
        )
    self._wait(500)


# ServiceNow's "Save draft" dialog binds its name box to ``c.data.draftName``
# through Angular, so the value must be written to the input and announced with
# an ``input`` event rather than typed through an accessibility ref.
_SET_DRAFT_NAME_JS = """(name) => {
    const el = document.getElementById('draft_item_name');
    if (!el) return {ok: false, error: 'the Save draft dialog has no #draft_item_name input'};
    el.value = name;
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
    if (window.angular) {
        const scope = window.angular.element(el).scope();
        if (scope) { try { scope.$apply(); } catch (e) { /* digest in progress */ } }
    }
    if (el.value !== name) {
        return {ok: false, error: 'the dialog still holds ' + JSON.stringify(el.value)};
    }
    return {ok: true, applied: el.value};
}"""


def _save_draft(self, snapshot: str, draft_name: Optional[str]) -> str:
    """Click 'Save as Draft' and complete ServiceNow's 'Save draft' modal.

    Returns the confirmation snapshot. Raises when ServiceNow does not confirm
    the save, so a failed draft can never be reported as a success.
    """
    draft_ref = parsers.find_element_ref(snapshot, 'button "Save as Draft"')
    if not draft_ref:
        raise ClientError("Could not find the 'Save as Draft' button on the catalog item form.")
    self._click(draft_ref)
    self._wait(2500)

    modal = self._snapshot()
    if DRAFT_MODAL_MARKER not in modal:
        raise ClientError(
            f"Clicking 'Save as Draft' did not open ServiceNow's {DRAFT_MODAL_MARKER!r} "
            "dialog, so the draft name could not be confirmed and nothing was saved."
        )

    if draft_name:
        result = self._svc._get_page().evaluate(_SET_DRAFT_NAME_JS, draft_name)
        if not result.get("ok"):
            raise ClientError(
                f"Could not set the draft name to {draft_name!r}: {result.get('error')}"
            )

    save_ref = parsers.find_element_ref(modal, 'button "Save"')
    if not save_ref:
        raise ClientError("The 'Save draft' dialog has no 'Save' button.")
    self._click(save_ref)
    self._wait(4000)
    self._dismiss_loading_overlay()

    confirmation = self._snapshot()
    if DRAFT_SAVED_MARKER not in confirmation:
        if DRAFT_MODAL_MARKER in confirmation:
            raise ClientError(
                "ServiceNow kept the 'Save draft' dialog open, so the draft was not saved. "
                "A draft with that name most likely already exists; pass --draft-name with "
                "a unique name, or delete the existing draft in My Requests > Drafts."
            )
        raise ClientError(
            "ServiceNow did not confirm the draft save "
            f"({DRAFT_SAVED_MARKER!r} never appeared). The draft was not saved."
        )
    return confirmation


def _create_ticket_from_template(self, template_key: str, template_data: Dict,
                                 field_values: Dict, draft: bool = False,
                                 draft_name: Optional[str] = None) -> Dict:
    """Create a ticket by filling the live catalog item form.

    Args:
        template_key: Template registry key (e.g. ``other_development_request``).
        template_data: The catalog item entry from ``ticket_template.json``.
        field_values: Mapping of template field key -> value.
        draft: Save the form as a draft instead of submitting it.

    Returns:
        Dict with ``status`` (``DRAFT_SAVED`` or ``SUBMITTED``), ``number``,
        ``template``, and ``url``.
    """
    fields = template_data.get("fields") or {}
    for field_key, value in field_values.items():
        if field_key not in fields:
            raise ClientError(
                f"Unknown field {field_key!r} for template {template_key!r}. "
                f"Use 'ticket template fields {template_key}' to see available fields."
            )
        _validate_field_value(field_key, fields[field_key], value)

    _navigate_to_catalog_form(self, template_data=template_data)

    snapshot = self._snapshot()
    for field_key, value in field_values.items():
        _apply_field(self, snapshot, field_key, fields[field_key], value)

    self._wait(1000)
    self._dismiss_loading_overlay()
    snapshot = self._snapshot()

    if draft:
        confirmation = _save_draft(self, snapshot, draft_name)
        page = self._svc._get_page()
        return {
            "status": "DRAFT_SAVED",
            "number": parsers.extract_ritm_from_snapshot(confirmation) or "",
            "template": template_key,
            "url": page.url,
            "drafts_url": f"{self.config.base_url}?id=my_requests"
            f"&draftSearchText={template_data.get('name', '')}",
        }

    submit_ref = parsers.find_submit_button_ref(snapshot)
    if not submit_ref:
        raise ClientError(
            "Could not find the Submit button on the catalog item form. "
            "The form may not have loaded correctly."
        )
    self._click(submit_ref)
    self._wait(5000)
    self._dismiss_loading_overlay()
    page = self._svc._get_page()
    ritm = parsers.extract_ritm_from_snapshot(self._snapshot())
    if not ritm:
        raise ClientError(
            "Submission failed: no RITM number appeared on the confirmation page at "
            f"{page.url}. The form may not have submitted successfully."
        )
    return {"status": "SUBMITTED", "number": ritm, "template": template_key, "url": page.url}


ProgressServicenowClient._navigate = _guarded_navigate
ProgressServicenowClient._snapshot = _guarded_snapshot
ProgressServicenowClient.catalog_page = _catalog_page
ProgressServicenowClient.catalog_item_definition = _catalog_item_definition
ProgressServicenowClient.resolve_catalog_sys_id = _resolve_catalog_sys_id
ProgressServicenowClient._navigate_to_catalog_form = _navigate_to_catalog_form
ProgressServicenowClient.list_products = _list_products
ProgressServicenowClient.create_ticket_from_template = _create_ticket_from_template
