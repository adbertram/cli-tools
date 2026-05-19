"""Progress ServiceNow client using BrowserAutomation for browser automation."""
import re
from typing import Dict, List, Optional

from cli_tools_shared.activity_log import get_activity_logger
from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

activity = get_activity_logger("progress-servicenow")

from .config import get_config
from .parsers import (
    extract_tickets_from_list,
    extract_ticket_detail,
    extract_comments,
    extract_catalog_items,
    extract_search_results,
    extract_home_tickets,
    find_combobox_ref,
    find_comment_textbox_ref,
    find_post_button_ref,
    find_close_button_ref,
    find_form_field_ref,
    find_submit_button_ref,
    extract_ritm_from_snapshot,
    find_checkbox_ref_by_label,
    extract_select2_options,
    parse_form_fields,
)
from .models import (
    Ticket,
    TicketDetail,
    TicketView,
    Comment,
    CatalogItem,
)


# Map CLI-friendly view names to TicketView values
VIEW_MAP = {
    "open": TicketView.OPEN,
    "closed": TicketView.CLOSED,
    "watchlist-open": TicketView.WATCHLIST_OPEN,
    "watchlist-closed": TicketView.WATCHLIST_CLOSED,
}

# Regex matching an element line in the aria snapshot YAML.
# Captures: (indent, role, optional_name, rest_of_line)
# Examples:
#   - link "Description , RITM0352332":
#   - generic: Work in Progress
#   - combobox "View":
#   - heading "Title" [level=2]
#   - paragraph:
_ELEMENT_LINE_RE = re.compile(
    r'^(\s*- )'           # indent + bullet
    r'([a-zA-Z]+)'        # role name
    r'(?: "([^"]*)")?'    # optional quoted name
    r'(.*)'               # rest (attributes, colon, inline text)
)

# Roles that correspond to interactive or identifiable ARIA roles.
# Used to build Playwright locators from ref -> role+name mapping.
_PW_ROLE_MAP = {
    "button": "button",
    "link": "link",
    "textbox": "textbox",
    "combobox": "combobox",
    "checkbox": "checkbox",
    "radio": "radio",
    "heading": "heading",
    "listitem": "listitem",
    "tab": "tab",
    "tabpanel": "tabpanel",
    "menuitem": "menuitem",
    "option": "option",
    "row": "row",
    "cell": "cell",
    "list": "list",
    "table": "table",
    "img": "img",
    "navigation": "navigation",
    "dialog": "dialog",
    "alert": "alert",
    "progressbar": "progressbar",
    "separator": "separator",
    "slider": "slider",
    "spinbutton": "spinbutton",
    "switch": "switch",
    "tree": "tree",
    "treeitem": "treeitem",
    "group": "group",
    "region": "region",
    "search": "search",
    "banner": "banner",
    "contentinfo": "contentinfo",
    "main": "main",
    "complementary": "complementary",
    "form": "form",
}


def _inject_refs(snapshot_text: str) -> tuple:
    """Inject [ref=eN] markers into an aria snapshot and build a ref map.

    Processes each element line in the aria snapshot YAML, adding [ref=eN]
    markers that the parsers expect. Returns the modified snapshot text and
    a dict mapping ref IDs to element metadata for locator resolution.

    Returns:
        (modified_snapshot_text, ref_map) where ref_map is
        {ref_id: {"role": str, "name": str|None, "nth": int}}
    """
    ref_map = {}
    ref_counter = 0
    # Track how many times each (role, name) pair has appeared, for nth-match
    role_name_counts: Dict[tuple, int] = {}
    output_lines = []

    for line in snapshot_text.split('\n'):
        m = _ELEMENT_LINE_RE.match(line)
        if m:
            indent = m.group(1)    # e.g. "  - "
            role = m.group(2)      # e.g. "link"
            name = m.group(3)      # e.g. "Description , RITM0352332" or None
            rest = m.group(4)      # e.g. " [level=2]:" or ": text"

            ref_counter += 1
            ref_id = f"e{ref_counter}"

            # Track nth occurrence of this (role, name) pair
            key = (role, name)
            count = role_name_counts.get(key, 0)
            role_name_counts[key] = count + 1

            ref_map[ref_id] = {
                "role": role,
                "name": name,
                "nth": count,  # 0-based index among same role+name elements
            }

            # Build the line with [ref=eN] injected after the role+name
            if name is not None:
                line = f'{indent}{role} "{name}" [ref={ref_id}]{rest}'
            else:
                line = f'{indent}{role} [ref={ref_id}]{rest}'

        output_lines.append(line)

    return '\n'.join(output_lines), ref_map


class ProgressServicenowClient:
    """Client that uses BrowserAutomation to automate Progress ServiceNow.

    Uses BrowserAutomation.get_page() to obtain a persistent browser page
    backed by the shared cli_tools_shared browser session. This ensures proper
    session reuse with the credential check gate.
    """

    def __init__(self):
        self.config = get_config()
        self._browser = self.config.get_browser()
        self._svc = None  # Lazily obtained via _ensure_browser
        self._ref_map: Dict[str, Dict] = {}
        activity.info("Client initialized (session=%s)", self.config.SESSION_NAME)

    def _ensure_browser(self):
        """Ensure a persistent browser session is open.

        Delegates to BrowserAutomation.get_page() which handles session reuse,
        persistent profiles, and auth state restoration.
        """
        if self._svc is not None:
            return
        activity.info("Opening persistent headless browser -> %s", self.config.base_url)
        try:
            self._svc = self._browser.get_page(self.config.base_url)
        except Exception as e:
            raise ClientError(f"Failed to open browser: {e}")

    def _navigate(self, url: str):
        """Navigate to a URL."""
        activity.info("navigate -> %s", url)
        try:
            self._svc.page_goto(url)
        except Exception as e:
            raise ClientError(f"Failed to navigate to {url}: {e}")

    def _snapshot(self) -> str:
        """Take an accessibility tree snapshot and return YAML with [ref=eN] markers.

        Uses Playwright's Locator.aria_snapshot() to capture the accessibility
        tree, then injects [ref=eN] markers that the parsers expect.
        """
        try:
            page = self._svc._get_page()
            raw = page.locator('body').aria_snapshot()
        except Exception as e:
            raise ClientError(f"Failed to capture page snapshot: {e}")

        snapshot, self._ref_map = _inject_refs(raw)
        return snapshot

    def _wait(self, ms: int = 2000):
        """Wait for page content to load."""
        self._svc.wait_for_timeout(ms)

    def _dismiss_loading_overlay(self):
        """Dismiss ServiceNow's persistent loading overlay.

        The ESC portal sets class 'sp-loading' on .sp-page-root and shows a
        spinner via .sp-page-loader.  The Angular variable main.firstPage
        never transitions to false in headless Chromium, so the overlay
        permanently hides the real content from both the visual viewport
        and the accessibility tree.  Removing the class and element exposes
        the already-rendered DOM.
        """
        try:
            self._svc.page_eval(
                'document.querySelector(".sp-page-root")?.classList.remove("sp-loading")'
            )
        except Exception:
            pass
        try:
            self._svc.page_eval(
                'document.querySelector(".sp-page-loader")?.remove()'
            )
        except Exception:
            pass

    def _resolve_ref(self, ref: str):
        """Resolve a ref ID to a Playwright locator on the current page.

        Uses the ref_map built during the last _snapshot() call to find the
        element by its ARIA role and accessible name.
        """
        info = self._ref_map.get(ref)
        if not info:
            raise ClientError(f"Unknown element ref: {ref}")

        page = self._svc._get_page()
        role = info["role"]
        name = info["name"]
        nth = info["nth"]

        pw_role = _PW_ROLE_MAP.get(role)
        if pw_role and name:
            locator = page.get_by_role(pw_role, name=name, exact=True)
        elif pw_role:
            locator = page.get_by_role(pw_role)
        elif name:
            # Fallback: use CSS with aria attributes
            locator = page.locator(f'[role="{role}"][aria-label="{name}"]')
        else:
            locator = page.locator(f'[role="{role}"]')

        # If there are multiple matches, use nth to disambiguate
        if nth > 0:
            locator = locator.nth(nth)

        return locator

    def _click(self, ref: str):
        """Click an element by its ref."""
        activity.info("click ref=%s", ref)
        try:
            self._resolve_ref(ref).click()
        except ClientError:
            raise
        except Exception as e:
            raise ClientError(f"Failed to click element {ref}: {e}")

    def _fill(self, ref: str, text: str):
        """Fill text into an element by its ref."""
        activity.info("fill ref=%s", ref)
        try:
            self._resolve_ref(ref).fill(text)
        except ClientError:
            raise
        except Exception as e:
            raise ClientError(f"Failed to fill element {ref}: {e}")

    def _select(self, ref: str, value: str):
        """Select a dropdown option by its ref and value."""
        activity.info("select ref=%s value=%s", ref, value)
        try:
            self._resolve_ref(ref).select_option(value)
        except ClientError:
            raise
        except Exception as e:
            raise ClientError(f"Failed to select option on element {ref}: {e}")

    def _fill_tinymce(self, ref: str, value: str):
        """Fill text into a TinyMCE rich text editor.

        TinyMCE editors render as iframes. We click the editor area to focus
        it, then use the keyboard to type the content.
        """
        activity.info("fill_tinymce ref=%s", ref)
        page = self._svc._get_page()
        try:
            locator = self._resolve_ref(ref)
            # Click the TinyMCE editor area to focus it
            locator.click()
            self._wait(500)
            # TinyMCE may have an iframe body — try to find and fill it
            # Look for the iframe inside or near the editor element
            tinymce_iframe = page.locator('iframe[id*="mce"]').first
            if tinymce_iframe.count() > 0:
                frame = tinymce_iframe.content_frame()
                body = frame.locator('body')
                body.fill(value)
            else:
                # Fallback: just type into whatever is focused
                page.keyboard.type(value)
        except ClientError:
            raise
        except Exception as e:
            raise ClientError(f"Failed to fill TinyMCE editor {ref}: {e}")

    def _select_dropdown(self, ref: str, value: str):
        """Select a dropdown value, handling both native selects and Select2 widgets.

        Select2 replaces <select> elements with a custom widget:
        - The real <input role="combobox"> is hidden (class ``select2-offscreen``)
        - A visible ``<a class="select2-choice">`` container intercepts clicks
        - Clicking the container opens a search dropdown with ``<input class="select2-input">``
        - Typing filters options; clicking a result selects it

        This method detects Select2 by checking for the ``select2-offscreen`` class
        on the resolved element and uses the proper interaction pattern.
        """
        activity.info("select_dropdown ref=%s value=%s", ref, value)

        # "-- None --" is the default/placeholder state for Select2 dropdowns.
        # No interaction needed — the field is already in this state.
        if value == "-- None --":
            activity.info("Skipping dropdown %s — '-- None --' is the default state", ref)
            return

        locator = self._resolve_ref(ref)
        page = self._svc._get_page()

        # Detect Select2: check if the element has the select2-offscreen class
        try:
            is_select2 = locator.evaluate(
                'el => el.classList.contains("select2-offscreen") '
                '|| el.closest(".select2-container") !== null'
            )
        except Exception:
            is_select2 = False

        if not is_select2:
            # Not Select2 — try native select_option, then fall back to click+type
            try:
                locator.select_option(value)
                return
            except Exception:
                try:
                    locator.click()
                    self._wait(500)
                    locator.fill(value)
                    self._wait(500)
                    page.keyboard.press("Enter")
                    return
                except Exception as e:
                    raise ClientError(
                        f"Failed to select dropdown option '{value}' on {ref}: {e}"
                    )

        # Select2 interaction pattern
        activity.info("Detected Select2 widget for ref=%s, using Select2 pattern", ref)
        try:
            # Step 1: Find the Select2 container and its search input ID.
            # Each Select2 has a unique container with an <input> whose ID
            # follows the pattern "s2id_autogenN_search".  We use that to
            # scope all subsequent selectors to THIS dropdown only.
            s2_info = locator.evaluate(
                """el => {
                    let c = el.closest(".select2-container");
                    if (!c) {
                        let prev = el.previousElementSibling;
                        if (prev && prev.classList.contains("select2-container")) c = prev;
                    }
                    if (!c) {
                        let parent = el.parentElement;
                        if (parent) c = parent.querySelector(".select2-container");
                    }
                    if (!c) return null;
                    let focusser = c.querySelector("input.select2-focusser");
                    let resultsId = focusser ? focusser.getAttribute("aria-owns") : null;
                    /* The search input ID = focusser ID + "_search" */
                    let searchId = focusser ? focusser.id + "_search" : null;
                    return {
                        containerId: c.id || null,
                        searchInputId: searchId,
                        resultsId: resultsId
                    };
                }"""
            )

            if not s2_info:
                raise ClientError(
                    f"Could not find Select2 container for {ref}"
                )

            container_id = s2_info.get("containerId")
            search_input_id = s2_info.get("searchInputId")
            results_id = s2_info.get("resultsId")
            activity.info(
                "Select2 info: container=%s search=%s results=%s",
                container_id, search_input_id, results_id,
            )

            # Click the container to open the dropdown
            if container_id:
                page.locator(f"#{container_id}").click()
            else:
                locator.evaluate(
                    """el => {
                        let parent = el.parentElement;
                        while (parent) {
                            let choice = parent.querySelector("a.select2-choice");
                            if (choice) { choice.click(); return; }
                            parent = parent.parentElement;
                        }
                    }"""
                )
            self._wait(500)

            # Step 2: Type into THIS dropdown's search input (scoped by ID).
            if search_input_id:
                search_input = page.locator(f"#{search_input_id}")
            else:
                search_input = page.locator(
                    f"#{container_id} input.select2-input"
                ) if container_id else page.locator(
                    '.select2-drop-active input.select2-input'
                ).first
            search_input.fill(value)
            self._wait(1000)

            # Step 3: Click the matching result from THIS dropdown's results list.
            if results_id:
                results_scope = f"#{results_id}"
            else:
                results_scope = ".select2-drop-active .select2-results"

            highlighted = page.locator(f"{results_scope} .select2-highlighted")
            if highlighted.count() > 0:
                highlighted.first.click()
            else:
                first_result = page.locator(
                    f"{results_scope} li.select2-result"
                )
                if first_result.count() > 0:
                    first_result.first.click()
                else:
                    page.keyboard.press("Enter")

            # Wait for dropdown to close, then dismiss any lingering overlay
            self._wait(500)
            mask = page.locator('#select2-drop-mask')
            if mask.count() > 0 and mask.is_visible():
                page.keyboard.press("Escape")
                self._wait(300)
            page.keyboard.press("Tab")
            self._wait(300)

        except ClientError:
            raise
        except Exception as e:
            raise ClientError(
                f"Failed to select Select2 dropdown option '{value}' on {ref}: {e}"
            )

    def close(self):
        """Close the browser."""
        if self._svc is not None:
            self._browser.close()
            self._svc = None

    # ==================== Ticket Methods ====================

    @cached
    def list_tickets(
        self,
        view: str = "watchlist-open",
        limit: int = 100,
        filters: Optional[List[str]] = None,
    ) -> List[Ticket]:
        """List tickets from My Requests page.

        Args:
            view: View to display. One of: open, closed, watchlist-open, watchlist-closed
            limit: Maximum number of tickets to return
            filters: Optional client-side filters

        Returns:
            List of Ticket models
        """
        activity.info("list_tickets view=%s limit=%d", view, limit)
        self._ensure_browser()

        # Navigate to My Requests page
        self._navigate(f"{self.config.base_url}?id=my_requests")
        self._wait(5000)
        self._dismiss_loading_overlay()

        # Switch view if needed
        ticket_view = VIEW_MAP.get(view, TicketView.WATCHLIST_OPEN)

        snapshot = self._snapshot()
        combobox_ref = find_combobox_ref(snapshot)
        if combobox_ref:
            self._select(combobox_ref, ticket_view.value)
            self._wait(3000)
            self._dismiss_loading_overlay()
            snapshot = self._snapshot()

        # Parse tickets from snapshot
        raw = extract_tickets_from_list(snapshot)
        tickets = [Ticket(**t) for t in raw[:limit]]
        return tickets

    @cached
    def get_ticket(self, number_or_sys_id: str) -> TicketDetail:
        """Get detailed ticket information.

        Args:
            number_or_sys_id: RITM number (e.g., RITM0352332) or sys_id

        Returns:
            TicketDetail model with comments
        """
        self._ensure_browser()

        # If it looks like a sys_id (hex string), navigate directly
        if self._is_sys_id(number_or_sys_id):
            sys_id = number_or_sys_id
        else:
            # It's an RITM number - find the sys_id by listing tickets
            sys_id = self._resolve_ritm_to_sys_id(number_or_sys_id)
            if not sys_id:
                raise ClientError(
                    f"Ticket {number_or_sys_id} not found. "
                    "Try listing tickets first to find the correct number."
                )

        # Navigate to ticket detail page
        url = f"{self.config.base_url}?id=ticket&table=sc_req_item&sys_id={sys_id}"
        self._navigate(url)
        self._wait(5000)
        self._dismiss_loading_overlay()

        snapshot = self._snapshot()

        # Parse ticket detail
        detail = extract_ticket_detail(snapshot)
        detail.setdefault('sys_id', sys_id)
        detail.setdefault('number', number_or_sys_id)
        detail.setdefault('description', '')

        # Parse comments
        raw_comments = extract_comments(snapshot)
        comments = [Comment(**c) for c in raw_comments]

        ticket = TicketDetail(
            **{k: v for k, v in detail.items() if k != 'comments'},
            comments=comments if comments else None,
        )
        activity.info("get_ticket %s -> %s (%s)", number_or_sys_id, ticket.number, ticket.state)
        return ticket

    def comment_ticket(self, number_or_sys_id: str, message: str) -> bool:
        """Post a comment on a ticket.

        Args:
            number_or_sys_id: RITM number or sys_id
            message: Comment text to post

        Returns:
            True if comment was posted successfully
        """
        activity.info("comment_ticket %s", number_or_sys_id)
        self._ensure_browser()

        # Navigate to the ticket
        if self._is_sys_id(number_or_sys_id):
            sys_id = number_or_sys_id
        else:
            sys_id = self._resolve_ritm_to_sys_id(number_or_sys_id)
            if not sys_id:
                raise ClientError(f"Ticket {number_or_sys_id} not found.")

        url = f"{self.config.base_url}?id=ticket&table=sc_req_item&sys_id={sys_id}"
        self._navigate(url)
        self._wait(5000)
        self._dismiss_loading_overlay()

        snapshot = self._snapshot()

        # Find and fill the comment textbox
        textbox_ref = find_comment_textbox_ref(snapshot)
        if not textbox_ref:
            raise ClientError("Could not find comment textbox on ticket page.")

        self._fill(textbox_ref, message)
        self._wait(500)

        # Take a new snapshot to find the Post button (it may appear after filling)
        snapshot = self._snapshot()
        post_ref = find_post_button_ref(snapshot)
        if not post_ref:
            raise ClientError("Could not find Post button on ticket page.")

        self._click(post_ref)
        self._wait(2000)

        return True

    def close_ticket(self, number_or_sys_id: str) -> bool:
        """Close a ticket.

        Args:
            number_or_sys_id: RITM number or sys_id

        Returns:
            True if ticket was closed successfully
        """
        activity.info("close_ticket %s", number_or_sys_id)
        self._ensure_browser()

        # Navigate to the ticket
        if self._is_sys_id(number_or_sys_id):
            sys_id = number_or_sys_id
        else:
            sys_id = self._resolve_ritm_to_sys_id(number_or_sys_id)
            if not sys_id:
                raise ClientError(f"Ticket {number_or_sys_id} not found.")

        url = f"{self.config.base_url}?id=ticket&table=sc_req_item&sys_id={sys_id}"
        self._navigate(url)
        self._wait(5000)
        self._dismiss_loading_overlay()

        snapshot = self._snapshot()

        # Find and click the Close Ticket button
        close_ref = find_close_button_ref(snapshot)
        if not close_ref:
            raise ClientError(
                "Could not find 'Close Ticket' button. "
                "The ticket may already be closed or you may not have permission."
            )

        self._click(close_ref)
        self._wait(3000)

        return True

    def create_ticket(self):
        """Open a headed browser at the ServiceNow home page for manual ticket creation.

        This opens the browser in headed (visible) mode so the user can
        browse the catalog and fill out a form manually.
        """
        activity.info("create_ticket -> opening headed browser")
        # Close any existing headless session
        self.close()

        try:
            svc = self.config.get_browser().open_headed(self.config.base_url)
        except Exception as e:
            raise ClientError(f"Failed to open headed browser: {e}")
        self._svc = svc

    def create_ticket_from_template(
        self,
        template_key: str,
        template_data: dict,
        field_values: Dict[str, str],
        draft: bool = False,
    ) -> str:
        """Create a ticket programmatically using a template and field values.

        Navigates to the catalog item form, fills in the fields using browser
        automation, and submits the form (or saves as draft).

        Args:
            template_key: Template key (e.g., 'development_cloud_issue').
            template_data: The catalog item dict from ticket_template.json.
            field_values: Dict of field_key -> value to fill.
            draft: If True, click "Save as Draft" instead of "Submit".

        Returns:
            The RITM number of the created ticket.

        Raises:
            ClientError: If form filling or submission fails.
        """
        activity.info(
            "create_ticket_from_template template=%s fields=%s",
            template_key, list(field_values.keys()),
        )

        # Step 1: Navigate to the catalog item form (prefers template url,
        # falls back to catalog search + click).
        self._navigate_to_catalog_form(template_data=template_data)
        page = self._svc._get_page()

        # Step 2: Fill in the form fields
        template_fields = template_data.get("fields", {})
        snapshot = self._snapshot()

        for field_key, value in field_values.items():
            field_def = template_fields.get(field_key)
            if not field_def:
                raise ClientError(
                    f"Unknown field '{field_key}' for template '{template_key}'. "
                    f"Use 'ticket template fields {template_key}' to see available fields."
                )

            field_type = field_def.get("type", "text")
            field_label = field_def.get("label", field_key)

            activity.info(
                "Filling field: %s (%s) = %s", field_key, field_type, value[:50]
            )

            if field_type == "checkbox_group":
                # For checkbox groups, value is comma-separated option labels
                option_labels = [v.strip() for v in value.split(",")]
                for opt_label in option_labels:
                    ref = find_checkbox_ref_by_label(snapshot, opt_label)
                    if not ref:
                        raise ClientError(
                            f"Could not find checkbox option '{opt_label}' for "
                            f"field '{field_key}' on the form. Check that the "
                            "option label matches exactly."
                        )
                    self._click(ref)
                    self._wait(500)
                    # Re-snapshot after each click as the DOM may change
                    snapshot = self._snapshot()
                continue

            if field_type == "checkbox":
                # For single checkbox, value should be "true" or "false"
                ref = find_form_field_ref(snapshot, field_label, field_type)
                if not ref:
                    raise ClientError(
                        f"Could not find checkbox '{field_label}' on the form."
                    )
                # Check current state and toggle if needed
                locator = self._resolve_ref(ref)
                is_checked = locator.is_checked()
                should_check = value.lower() in ("true", "yes", "1", "checked")
                if is_checked != should_check:
                    self._click(ref)
                    self._wait(500)
                    snapshot = self._snapshot()
                continue

            # For text, textarea, dropdown, reference, date fields
            ref = find_form_field_ref(snapshot, field_label, field_type)
            if not ref:
                raise ClientError(
                    f"Could not find field '{field_label}' (type={field_type}) "
                    f"on the form. The form may have loaded differently than "
                    f"expected, or the field may be conditional."
                )

            if field_type == "dropdown":
                self._select_dropdown(ref, value)
            elif field_type == "reference":
                # Reference fields are search/lookup boxes
                self._fill(ref, value)
                self._wait(1500)
                # Press Enter or select the first suggestion
                page.keyboard.press("Enter")
                self._wait(1000)
            elif field_type == "textarea":
                # May be a plain textbox or a TinyMCE rich text editor.
                # TinyMCE renders as an iframe with role "application".
                # Try plain fill first; if it fails, use TinyMCE approach.
                try:
                    self._fill(ref, value)
                except ClientError:
                    activity.info(
                        "Plain fill failed for textarea %s, trying TinyMCE", ref
                    )
                    self._fill_tinymce(ref, value)
            else:
                # text, date
                self._fill(ref, value)

            self._wait(500)
            # Re-snapshot after filling as the form may update dynamically
            snapshot = self._snapshot()

        # Step 3: Submit the form (or save as draft)
        snapshot = self._snapshot()
        if draft:
            activity.info("Looking for Save as Draft button")
            pattern = r'button "Save as Draft"'
            from .parsers import find_element_ref
            draft_ref = find_element_ref(snapshot, pattern)
            if not draft_ref:
                raise ClientError(
                    "Could not find the 'Save as Draft' button on the form."
                )
            self._click(draft_ref)
            self._wait(3000)
            self._dismiss_loading_overlay()
            self._wait(2000)
            self._dismiss_loading_overlay()

            # After saving a draft, the page may show the RITM or stay on form
            snapshot = self._snapshot()
            ritm = extract_ritm_from_snapshot(snapshot)
            if ritm:
                activity.info("Draft saved: %s", ritm)
                return ritm
            # Draft saved but no RITM — check if we're still on the form
            # (drafts may not redirect to a confirmation page)
            activity.info("Draft saved (no RITM on page — draft may not generate one)")
            return "DRAFT_SAVED"
        else:
            activity.info("Looking for Submit button")
            submit_ref = find_submit_button_ref(snapshot)
            if not submit_ref:
                raise ClientError(
                    "Could not find the Submit button on the form. "
                    "The form may not have loaded correctly."
                )

            self._click(submit_ref)
            self._wait(5000)
            self._dismiss_loading_overlay()
            self._wait(2000)
            self._dismiss_loading_overlay()

            # Step 4: Extract the RITM number from the confirmation page
            snapshot = self._snapshot()
            ritm = extract_ritm_from_snapshot(snapshot)
            if ritm:
                activity.info("Ticket created: %s", ritm)
                return ritm

            # RITM not found — fail with diagnostics
            import sys as _sys
            print(f"DEBUG post-submit URL: {page.url}", file=_sys.stderr)
            print(f"DEBUG post-submit snapshot:\n{snapshot}", file=_sys.stderr)
            raise ClientError(
                "Submission failed: could not find RITM number on the "
                "confirmation page. The form may not have submitted "
                "successfully, or the confirmation page format is unexpected."
            )

    # ==================== Catalog Methods ====================

    @cached
    def list_catalog(
        self,
        category: Optional[str] = None,
        limit: int = 100,
    ) -> List[CatalogItem]:
        """List catalog items, optionally filtered by category.

        Args:
            category: Category slug (e.g., "it", "business-operations")
            limit: Maximum number of items to return

        Returns:
            List of CatalogItem models
        """
        activity.info("list_catalog category=%s limit=%d", category, limit)
        self._ensure_browser()

        if category:
            # Navigate to the category page
            # Categories map to taxonomy topic pages
            url = f"{self.config.base_url}?id=emp_taxonomy_topic&topic_id={category}"
        else:
            # Navigate to the home page and browse
            url = f"{self.config.base_url}?id=ec_pro_home"

        self._navigate(url)
        self._wait(5000)
        self._dismiss_loading_overlay()

        snapshot = self._snapshot()
        raw = extract_catalog_items(snapshot)
        return [CatalogItem(**item) for item in raw[:limit]]

    @cached
    def get_catalog_item(self, sys_id: str) -> CatalogItem:
        """Get details for a specific catalog item by sys_id.

        Args:
            sys_id: The sys_id of the catalog item

        Returns:
            CatalogItem model
        """
        self._ensure_browser()

        url = f"{self.config.base_url}?id=sc_cat_item&sys_id={sys_id}"
        self._navigate(url)
        self._wait(5000)
        self._dismiss_loading_overlay()

        snapshot = self._snapshot()

        # Try to extract catalog items from the page
        raw = extract_catalog_items(snapshot)
        if raw:
            item = raw[0]
            item.setdefault('sys_id', sys_id)
            return CatalogItem(**item)

        # Fallback: build a minimal item from page content
        # Look for heading or title on the page
        name = None
        description = None
        for line in snapshot.split('\n'):
            if name is None:
                heading_match = re.match(r'^\s*- heading "(.+?)"\s+\[level=', line)
                if heading_match:
                    name = heading_match.group(1).strip()
            if description is None:
                para_match = re.match(r'^\s*- paragraph \[ref=\w+\]:\s*(.+)', line)
                if para_match:
                    description = para_match.group(1).strip()

        return CatalogItem(
            name=name or "Unknown",
            description=description,
            sys_id=sys_id,
            url=f"?id=sc_cat_item&sys_id={sys_id}",
        )

    @cached
    def search_catalog(self, query: str, limit: int = 100) -> List[CatalogItem]:
        """Search the ServiceNow catalog.

        Args:
            query: Search query string
            limit: Maximum number of results

        Returns:
            List of CatalogItem models
        """
        activity.info("search_catalog query=%r limit=%d", query, limit)
        self._ensure_browser()

        # Navigate to search results
        url = f"{self.config.base_url}?id=search&q={query}"
        self._navigate(url)
        self._wait(5000)
        self._dismiss_loading_overlay()

        snapshot = self._snapshot()
        raw = extract_search_results(snapshot)
        return [CatalogItem(**item) for item in raw[:limit]]

    # ==================== Product Methods ====================

    _DEV_CLOUD_ISSUE_URL = (
        "?id=sc_cat_item"
        "&sys_id=c9f3a854dbe5db0408f33a1b7c9619dc"
        "&table=sc_cat_item"
    )

    @cached
    def list_products(self) -> List[str]:
        """List available Product dropdown options from the Development Cloud Issue form.

        Navigates to the catalog item form, opens the Product Select2 dropdown,
        waits for AJAX options to load, and scrapes all option text values.
        Scrolls the results list to capture any lazy-loaded options.

        Returns:
            List of product name strings.

        Raises:
            ClientError: If the form or dropdown cannot be loaded.
        """
        activity.info("list_products -> Development Cloud Issue form")
        self._ensure_browser()

        # Navigate directly to the Development Cloud Issue catalog item form
        url = f"{self.config.base_url}{self._DEV_CLOUD_ISSUE_URL}"
        self._navigate(url)
        self._wait(5000)
        self._dismiss_loading_overlay()
        self._wait(2000)
        self._dismiss_loading_overlay()

        # Take a snapshot to find the Product combobox
        snapshot = self._snapshot()
        product_ref = find_form_field_ref(snapshot, "Product", "dropdown")
        if not product_ref:
            raise ClientError(
                "Could not find the Product dropdown on the Development Cloud Issue form. "
                "The form may not have loaded correctly."
            )

        # Resolve the combobox locator to detect Select2
        locator = self._resolve_ref(product_ref)
        page = self._svc._get_page()

        # Get Select2 container info (reuses the same JS from _select_dropdown)
        s2_info = locator.evaluate(
            """el => {
                let c = el.closest(".select2-container");
                if (!c) {
                    let prev = el.previousElementSibling;
                    if (prev && prev.classList.contains("select2-container")) c = prev;
                }
                if (!c) {
                    let parent = el.parentElement;
                    if (parent) c = parent.querySelector(".select2-container");
                }
                if (!c) return null;
                let focusser = c.querySelector("input.select2-focusser");
                let resultsId = focusser ? focusser.getAttribute("aria-owns") : null;
                let searchId = focusser ? focusser.id + "_search" : null;
                return {
                    containerId: c.id || null,
                    searchInputId: searchId,
                    resultsId: resultsId
                };
            }"""
        )

        if not s2_info:
            raise ClientError(
                "Could not find Select2 container for the Product dropdown."
            )

        container_id = s2_info.get("containerId")
        results_id = s2_info.get("resultsId")
        activity.info(
            "Select2 Product: container=%s results=%s",
            container_id, results_id,
        )

        # Click the container to open the dropdown (empty search = all options)
        if container_id:
            page.locator(f"#{container_id}").click()
        else:
            locator.click()
        self._wait(1500)

        # Scroll the results list to load all lazy-loaded options.
        # Select2 loads more results when the user scrolls near the bottom.
        results_selector = f"#{results_id}" if results_id else ".select2-drop-active .select2-results"
        prev_count = 0
        max_scroll_attempts = 20

        for _ in range(max_scroll_attempts):
            # Count current options
            current_count = page.eval_on_selector(
                results_selector,
                "el => el.querySelectorAll('li.select2-result').length"
            )
            if current_count == prev_count and current_count > 0:
                # No new options loaded after scroll — we have them all
                break
            prev_count = current_count

            # Scroll the results list to the bottom to trigger lazy-load
            page.eval_on_selector(
                results_selector,
                "el => el.scrollTop = el.scrollHeight"
            )
            self._wait(800)

        # Extract all option text via JavaScript for reliability
        products = page.eval_on_selector(
            results_selector,
            """el => {
                const items = el.querySelectorAll('li.select2-result');
                const texts = [];
                items.forEach(item => {
                    const text = item.textContent.trim();
                    if (text && text !== 'Searching…' && text !== 'Loading…'
                        && text !== 'No matches found') {
                        texts.push(text);
                    }
                });
                return texts;
            }"""
        )

        # Close the dropdown
        page.keyboard.press("Escape")
        self._wait(300)

        activity.info("list_products -> %d products found", len(products))
        return products

    # ==================== Form Introspection Methods ====================

    def _navigate_to_catalog_form(
        self,
        template_data: Optional[dict] = None,
        url: Optional[str] = None,
    ) -> None:
        """Open a catalog item form in the authenticated browser.

        Exactly one of ``template_data`` or ``url`` must be provided.

        - With ``template_data``: searches the catalog for the item's name
          and clicks the first matching search result. Handles catalog items
          that don't have a known sys_id URL in ticket_template.json.
        - With ``url``: navigates directly. Use this for catalog items whose
          sys_id URL is known (e.g., Request Application Assistance).

        Raises:
            ClientError: If navigation fails or the form doesn't load.
        """
        if (template_data is None) == (url is None):
            raise ClientError(
                "_navigate_to_catalog_form requires exactly one of "
                "template_data or url."
            )

        self._ensure_browser()
        page = self._svc._get_page()

        # Prefer a template's stored URL when present — fastest path.
        if url is None and template_data and template_data.get("url"):
            url = template_data["url"]
            activity.info("Using template url: %s", url)

        if url:
            if not url.startswith("http"):
                url = f"{self.config.base_url}{url}"
            activity.info("Navigating directly to form: %s", url)
            self._navigate(url)
        else:
            item_name = template_data["name"]
            search_url = f"{self.config.base_url}?id=search&q={item_name}"
            activity.info("Searching catalog for: %s", item_name)
            self._navigate(search_url)
            self._wait(5000)
            self._dismiss_loading_overlay()
            self._wait(2000)
            self._dismiss_loading_overlay()

            clicked = False
            # Prefer exact match; fall back to substring match for forgiveness.
            exact_target = item_name.lower()
            substring_target = item_name.lower()
            candidate_links = page.get_by_role("link").all()

            for link in candidate_links:
                try:
                    text = link.text_content(timeout=1000)
                    if text and text.strip().lower() == exact_target:
                        activity.info("Clicking exact catalog match: %s", text)
                        link.click()
                        clicked = True
                        break
                except Exception:
                    continue

            if not clicked:
                for link in candidate_links:
                    try:
                        text = link.text_content(timeout=1000)
                        if text and substring_target in text.lower():
                            activity.info("Clicking substring catalog match: %s", text)
                            link.click()
                            clicked = True
                            break
                    except Exception:
                        continue

            if not clicked:
                raise ClientError(
                    f"Could not find catalog item '{item_name}' in search "
                    "results. Provide --url explicitly or verify the template name."
                )

        self._wait(6000)
        self._dismiss_loading_overlay()
        self._wait(2000)
        self._dismiss_loading_overlay()

    def inspect_form(
        self,
        template_data: Optional[dict] = None,
        url: Optional[str] = None,
    ) -> List[dict]:
        """Navigate to a catalog item form and parse its live fields.

        Returns the form fields observed on the live page, not the offline
        ticket_template.json snapshot. Use this to discover fields for
        catalog items whose templates are stale or empty.

        Args:
            template_data: Catalog item dict from ticket_template.json.
            url: Direct URL to the catalog item form.

        Returns:
            List of field dicts with keys: label, type, required, ref,
            key_suggestion.
        """
        activity.info("inspect_form")
        self._navigate_to_catalog_form(template_data=template_data, url=url)
        snapshot = self._snapshot()
        return parse_form_fields(snapshot)

    def lookup_form_field(
        self,
        field_label: str,
        search: str,
        template_data: Optional[dict] = None,
        url: Optional[str] = None,
    ) -> List[str]:
        """Search a Select2/reference field on a catalog item form.

        Navigates to the form, finds the field by its label, opens the
        Select2 dropdown, types the search string, and returns the matching
        option labels.

        Args:
            field_label: Visible label of the dropdown/reference field.
            search: Search string to type into the dropdown.
            template_data: Catalog item dict from ticket_template.json.
            url: Direct URL to the catalog item form.

        Returns:
            List of matching option label strings.

        Raises:
            ClientError: If the field cannot be found or the dropdown
                doesn't behave like a Select2 widget.
        """
        activity.info(
            "lookup_form_field label=%s search=%s", field_label, search
        )
        self._navigate_to_catalog_form(template_data=template_data, url=url)
        snapshot = self._snapshot()

        # Look for the field as either a dropdown or reference
        ref = find_form_field_ref(snapshot, field_label, "dropdown")
        if not ref:
            ref = find_form_field_ref(snapshot, field_label, "reference")
        if not ref:
            raise ClientError(
                f"Could not find field '{field_label}' on the form."
            )

        locator = self._resolve_ref(ref)
        page = self._svc._get_page()

        s2_info = locator.evaluate(
            """el => {
                let c = el.closest(".select2-container");
                if (!c) {
                    let prev = el.previousElementSibling;
                    if (prev && prev.classList.contains("select2-container")) c = prev;
                }
                if (!c) {
                    let parent = el.parentElement;
                    if (parent) c = parent.querySelector(".select2-container");
                }
                if (!c) return null;
                let focusser = c.querySelector("input.select2-focusser");
                let searchId = focusser ? focusser.id + "_search" : null;
                let resultsId = focusser ? focusser.getAttribute("aria-owns") : null;
                return {
                    containerId: c.id || null,
                    searchInputId: searchId,
                    resultsId: resultsId,
                };
            }"""
        )

        if not s2_info:
            raise ClientError(
                f"Field '{field_label}' is not a Select2 widget. "
                "lookup_form_field only supports Select2-based dropdowns."
            )

        container_id = s2_info.get("containerId")
        search_input_id = s2_info.get("searchInputId")
        results_id = s2_info.get("resultsId")

        # Open the dropdown
        if container_id:
            page.locator(f"#{container_id}").click()
        else:
            locator.click()
        self._wait(800)

        # Fill the search input
        if search_input_id:
            search_input = page.locator(f"#{search_input_id}")
        elif container_id:
            search_input = page.locator(f"#{container_id} input.select2-input")
        else:
            search_input = page.locator(
                ".select2-drop-active input.select2-input"
            ).first

        search_input.fill(search)
        self._wait(2500)

        # Extract all matching option labels
        results_selector = (
            f"#{results_id}" if results_id else ".select2-drop-active .select2-results"
        )

        try:
            options = page.eval_on_selector(
                results_selector,
                """el => {
                    const items = el.querySelectorAll('li.select2-result');
                    const texts = [];
                    items.forEach(item => {
                        const text = item.textContent.trim();
                        if (text && text !== 'Searching…' && text !== 'Loading…'
                            && text !== 'No matches found') {
                            texts.push(text);
                        }
                    });
                    return texts;
                }"""
            )
        except Exception as e:
            raise ClientError(
                f"Failed to read Select2 results for '{field_label}': {e}"
            )

        # Close the dropdown cleanly
        page.keyboard.press("Escape")
        self._wait(300)

        activity.info(
            "lookup_form_field -> %d matches for '%s'", len(options), search
        )
        return options

    # ==================== Helper Methods ====================

    @staticmethod
    def _is_sys_id(value: str) -> bool:
        """Check if a value looks like a ServiceNow sys_id (32-char hex)."""
        return bool(re.match(r'^[a-f0-9]{32}$', value))

    def _resolve_ritm_to_sys_id(self, ritm_number: str) -> Optional[str]:
        """Resolve an RITM number to a sys_id by searching the My Requests page.

        Tries multiple views to find the ticket.
        """
        # Normalize the RITM number
        ritm = ritm_number.upper()
        if not ritm.startswith('RITM'):
            ritm = f"RITM{ritm}"

        # Try each view to find the ticket
        for view_name in ["open", "watchlist-open", "closed", "watchlist-closed"]:
            self._navigate(f"{self.config.base_url}?id=my_requests")
            self._wait(5000)
            self._dismiss_loading_overlay()

            ticket_view = VIEW_MAP[view_name]
            snapshot = self._snapshot()

            combobox_ref = find_combobox_ref(snapshot)
            if combobox_ref:
                self._select(combobox_ref, ticket_view.value)
                self._wait(3000)
                self._dismiss_loading_overlay()
                snapshot = self._snapshot()

            raw = extract_tickets_from_list(snapshot)
            for t in raw:
                if t.get("number", "").upper() == ritm:
                    return t.get("sys_id")

        return None


_client: Optional[ProgressServicenowClient] = None


def get_client() -> ProgressServicenowClient:
    """Get or create the global Progress ServiceNow client instance."""
    global _client
    if _client is None:
        _client = ProgressServicenowClient()
    return _client
