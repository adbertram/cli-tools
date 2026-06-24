"""Globiflow client using browser automation.

This client wraps GlobiflowBrowser with site-specific methods
for Globiflow operations.
"""
from typing import Dict, List, Optional, Any

from .config import get_config
from .browser import GlobiflowBrowser, BrowserError, AuthenticationRequired
from .models import Flow, FlowDetail, FlowLog, Step, AnyStep, create_step, HttpMethod, RelationshipDirection, Trigger, TriggerType


# Field name to UI selector mapping for step updates
FIELD_SELECTORS = {
    # Variable/Calc fields
    "variable_name": ["input[placeholder='Variable Name']", "input[name*='varname']"],
    "code": ["textarea[name*='gmvalue']", "textarea[name*='expression']"],

    # HTTP Call fields
    "url": ["textarea[id^='gmurl']", "textarea.xgminput[id*='url']"],
    "method": ["select[name*='method']"],
    "headers": ["textarea[name*='gmheaders']", "textarea[name*='headers']"],
    "get_params": ["textarea[name*='gmget']", "textarea[name*='getparams']"],
    "post_params": ["textarea[name*='gmpost']", "textarea[name*='postparams']"],
    "follow_redirect": ["input[type='checkbox'][name*='redirect']"],

    # Email fields
    "to": ["input[name*='to']", "textarea[name*='to']"],
    "subject": ["input[name*='subject']"],
    "body": ["textarea[name*='body']"],
    "from_name": ["input[name*='from']"],
    "reply_to": ["input[name*='replyto']"],
    "cc": ["input[name*='cc']"],
    "bcc": ["input[name*='bcc']"],

    # Comment fields
    "comment_body": ["textarea[name*='gmmessage']", "textarea[name*='comment']"],
    "silent": ["input[type='checkbox'][name*='silent']"],

    # SMS/Message fields
    "message": ["textarea[name*='message']"],

    # Task fields
    "assignee": ["input[name*='assignee']"],
    "task_text": ["textarea[name*='task']"],
    "due_date": ["input[name*='duedate']", "input[name*='due']"],

    # PDF/File fields
    "filename": ["input[name*='filename']"],
    "template": ["textarea[name*='template']"],
}


class ClientError(Exception):
    """Custom exception for Globiflow client errors."""
    pass


def _clean(value: Optional[str]) -> str:
    """Normalize a Playwright text_content() result to a stripped string.

    Playwright's ``text_content()`` returns ``Optional[str]`` and yields
    ``None`` for a node that has no text content, so calling ``.strip()``
    directly raises ``AttributeError``. This helper coalesces ``None`` to an
    empty string before stripping.
    """
    return (value or "").strip()


class GlobiflowClient:
    """Client for interacting with Globiflow via browser automation."""

    BASE_URL = "https://workflow-automation.podio.com"

    def __init__(self, profile_name: str = None):
        """Initialize Globiflow client.

        Args:
            profile_name: Named profile to use (optional).
        """
        self.config = get_config()
        self.profile_name = profile_name
        self._browser: Optional[GlobiflowBrowser] = None

    @property
    def browser(self) -> GlobiflowBrowser:
        """Get or create browser service."""
        if self._browser is None:
            self._browser = self.config.get_browser()
        return self._browser

    def close(self):
        """Close browser."""
        if self._browser:
            self._browser.close()
            self._browser = None

    # ==================== Navigation Helpers ====================

    def ensure_authenticated(self, path: str = "/"):
        """Ensure user is authenticated before accessing a page.

        Raises AuthenticationRequired when the shared browser session is not
        available. Login is handled by the common auth commands.
        """
        if not self.browser.is_authenticated():
            raise AuthenticationRequired("Run 'globiflow auth login' to authenticate.")

        url = f"{self.BASE_URL}{path}" if not path.startswith("http") else path
        page = self.browser.get_page(url)
        page.wait_for_timeout(2000)  # Allow redirects to settle

        current_url = page.url
        if path != "/" and (current_url == self.BASE_URL or current_url == f"{self.BASE_URL}/"):
            raise AuthenticationRequired("Globiflow browser session expired. Run 'globiflow auth login --force'.")

    def navigate(self, path: str):
        """Navigate to a path on Globiflow."""
        url = f"{self.BASE_URL}{path}" if not path.startswith("http") else path
        self.browser.get_page(url)

    # ==================== Trigger Methods ====================

    def list_triggers(self) -> List[Trigger]:
        """List all available trigger types for flows.

        Returns a static list of all trigger types supported by Globiflow.
        These are global and not app-specific.

        Returns:
            List of Trigger models with code, name, and description
        """
        # Static list based on Globiflow UI discovery
        trigger_data = [
            ("T", "Every Day", "Scheduled to run daily at a specific time"),
            ("C", "Item Created", "When a new Item is created in this App"),
            ("U", "Item Updated", "When an existing Item is updated in this App"),
            ("Q", "Comment Added", "When a new Comment is added on an Item"),
            ("M", "Manual", "Will be triggered manually by another Flow"),
            ("K", "Task Completed", "When a Podio Task generated in this app is marked as Completed"),
            ("F", "Date Field", "When a specific date field of any item matches certain conditions"),
            ("R", "Email Reply", "When a reply is received to an Email sent in an Action in this App"),
            ("S", "SMS Reply", "When a reply is received to an SMS Text Message sent in an Action"),
            ("X", "RightSignature", "When a document sent from this App is signed in RightSignature"),
            ("L", "External Link", "Will be triggered when a special external link is clicked"),
            ("W", "Webhook", "By an External Webhook Event"),
            ("FU", "File Upload", "When a new file is uploaded in an item"),
        ]

        return [
            Trigger(code=code, name=name, description=desc)
            for code, name, desc in trigger_data
        ]

    # ==================== Domain-Specific Methods ====================
    # TODO: Implement methods specific to Globiflow below

    def search(
        self,
        query: str,
        limit: int = 100,
        filters: Optional[List[str]] = None,
    ) -> List[Dict]:
        """Search for items on Globiflow.

        Limiting: Client-side (browser scraping)
        Filtering: Client-side

        Args:
            query: Search query
            limit: Maximum number of results
            filters: Optional filter strings (applied client-side)

        Returns:
            Array of search results only (no metadata)

        Example implementation:
            self.ensure_authenticated("/search")
            self.browser.navigate(f"{self.BASE_URL}/search?q={query}")
            self.browser.wait(2000)

            results = self.browser.extract_list(".result-item", {
                "title": ".title",
                "price": ".price",
                "url": "a::attr(href)",
            })

            # Apply client-side filters if needed
            # if filters:
            #     results = apply_filters(results, filters)

            return results[:limit]
        """
        raise NotImplementedError("Implement search for Globiflow")

    def get_item(self, item_id: str) -> Dict:
        """Get details for a specific item.

        Args:
            item_id: The item ID or URL

        Returns:
            Item details

        Example implementation:
            if item_id.startswith("http"):
                self.browser.navigate(item_id)
            else:
                self.browser.navigate(f"{self.BASE_URL}/item/{item_id}")

            self.browser.wait(2000)

            return {
                "id": item_id,
                "title": self.browser.get_text("h1.title"),
                "price": self.browser.get_text(".price"),
                "description": self.browser.get_text(".description"),
            }
        """
        raise NotImplementedError("Implement get_item for Globiflow")

    def list_items(
        self,
        limit: int = 100,
        filters: Optional[List[str]] = None,
    ) -> List[Dict]:
        """List items from Globiflow.

        Limiting: Client-side (browser scraping)
        Filtering: Client-side

        Args:
            limit: Maximum number of items
            filters: Optional filter strings (applied client-side)

        Returns:
            Array of items only (no metadata)

        Example implementation:
            self.ensure_authenticated("/items")

            # Click "Load More" to get all items
            self.browser.click_load_more("button.load-more", max_clicks=5)

            # Extract table data
            items = self.browser.extract_table(
                "table.items",
                header_selector="thead th",
                row_selector="tbody tr",
                cell_selector="td"
            )

            # Apply client-side filters if needed
            # if filters:
            #     items = apply_filters(items, filters)

            return items[:limit]
        """
        # Return empty list - Globiflow doesn't have a generic list items API
        return []

    # ==================== Flow Methods ====================

    def list_flows(self) -> List[Flow]:
        """List all flows across all apps.

        Navigates to flows.php, expands the tree, and extracts all flows
        from all apps.

        Returns:
            List of Flow models with: name, app_name, workspace_name,
            org_name, enabled
        """
        import re

        self.ensure_authenticated("/flows.php")
        page = self.browser.get_page()

        # Wait for tree to load
        page.wait_for_selector('[role="treeitem"]', timeout=10000)

        # Click "Expand All" to show full tree
        expand_link = page.get_by_role("link", name="Expand All")
        if expand_link.count() > 0:
            expand_link.click()
            page.wait_for_timeout(2000)

        flows = []

        # Track hierarchy as we traverse
        current_org = ""
        current_workspace = ""

        # Get all tree items
        tree_items = page.locator('[role="treeitem"]').all()

        # First pass: build hierarchy and identify apps with flows
        apps_with_flows = []
        for item in tree_items:
            text = _clean(item.text_content())
            level = item.get_attribute("aria-level")

            if level == "1":
                # Organization level (skip special items)
                if not text.startswith("By Date") and not text.startswith("Webhooks"):
                    current_org = text
            elif level == "2":
                current_workspace = text
            elif level == "3":
                # App level - check for flow count
                match = re.match(r"(.+) \((\d+)\)", text)
                if match:
                    app_name = match.group(1).strip()
                    flow_count = int(match.group(2))
                    if flow_count > 0:
                        apps_with_flows.append({
                            "app_name": app_name,
                            "workspace_name": current_workspace,
                            "org_name": current_org,
                            "tree_item_text": text,
                        })

        # Second pass: click each app and extract flows
        for app_info in apps_with_flows:
            # Find and click the app tree item
            app_item = page.get_by_role("treeitem", name=app_info["tree_item_text"])
            if app_item.count() > 0:
                app_item.click()
                page.wait_for_timeout(1500)

                # Extract flows from the flow list panel
                # Flows are in divs with cursor pointer containing an img and flow name
                flow_container = page.locator("hr ~ div").first
                if flow_container.count() > 0:
                    flow_items = flow_container.locator("div[style*='cursor']").all()
                    if not flow_items:
                        # Alternative selector
                        flow_items = flow_container.locator("> div").all()

                    for flow_item in flow_items:
                        # Get flow name - it's the text content excluding img
                        flow_name = _clean(flow_item.text_content())

                        # Skip toolbar elements
                        if flow_name.startswith("With Selected:"):
                            continue

                        # Extract flow ID from the checkbox value attribute
                        checkbox = flow_item.locator("input.bulkCheck").first
                        flow_id = None
                        if checkbox.count() > 0:
                            flow_id = checkbox.get_attribute("value")

                        # Check enabled status from img src
                        # Disabled flows have images ending in _off.png (e.g., transmit_off.png)
                        # Enabled flows have images ending in .png without _off
                        img = flow_item.locator("img").first
                        enabled = True
                        if img.count() > 0:
                            src = img.get_attribute("src") or ""
                            enabled = "_off" not in src.lower()

                        if flow_name and flow_id:
                            flows.append(Flow(
                                id=flow_id,
                                name=flow_name,
                                app_name=app_info["app_name"],
                                workspace_name=app_info["workspace_name"],
                                org_name=app_info["org_name"],
                                enabled=enabled,
                            ))

        return flows

    def delete_flow(self, flow_id: str) -> bool:
        """Delete a flow by its ID.

        Navigates to the flows page, finds the flow by ID, selects it,
        and clicks the Delete action.

        Args:
            flow_id: The flow ID to delete

        Returns:
            True if deletion was successful

        Raises:
            ClientError: If flow not found or deletion fails
        """
        import re

        self.ensure_authenticated("/flows.php")
        page = self.browser.get_page()

        # Wait for tree to load
        page.wait_for_selector('[role="treeitem"]', timeout=10000)

        # Click "Expand All" to show full tree
        expand_link = page.get_by_role("link", name="Expand All")
        if expand_link.count() > 0:
            expand_link.click()
            page.wait_for_timeout(2000)

        # Track hierarchy as we traverse to find apps with flows
        tree_items = page.locator('[role="treeitem"]').all()
        apps_with_flows = []
        for item in tree_items:
            text = _clean(item.text_content())
            level = item.get_attribute("aria-level")
            if level == "3":
                match = re.match(r"(.+) \((\d+)\)", text)
                if match and int(match.group(2)) > 0:
                    apps_with_flows.append(text)

        # Search through each app to find the flow
        for app_text in apps_with_flows:
            app_item = page.get_by_role("treeitem", name=app_text)
            if app_item.count() > 0:
                app_item.click()
                page.wait_for_timeout(1500)

                # Look for the checkbox with the matching flow ID
                checkbox = page.locator(f'input.bulkCheck[value="{flow_id}"]').first
                if checkbox.count() > 0:
                    # Use JavaScript to check the hidden checkbox directly
                    page.evaluate(f'''
                        document.querySelector('input.bulkCheck[value="{flow_id}"]').checked = true;
                    ''')
                    page.wait_for_timeout(500)

                    # Get the app_id from the Delete link's onclick attribute
                    delete_link = page.locator('a[onclick*="bulkDelete"]').first
                    if delete_link.count() > 0:
                        onclick = delete_link.get_attribute("onclick") or ""
                        # Extract app_id from bulkDelete(12345)
                        import re as regex
                        match = regex.search(r"bulkDelete\((\d+)\)", onclick)
                        if match:
                            app_id = match.group(1)
                            # Call the JavaScript function to show delete modal
                            page.evaluate(f"bulkDelete({app_id})")
                            page.wait_for_timeout(1000)

                            # The modal requires typing "delete" to confirm
                            # Find the visible text input in the modal
                            modal_input = page.locator("input[type='text']").last
                            if modal_input.count() > 0 and modal_input.is_visible():
                                modal_input.fill("delete")
                                page.wait_for_timeout(300)

                                # Click the OK button
                                ok_button = page.get_by_role("button", name="OK")
                                if ok_button.count() > 0:
                                    ok_button.click()
                                    page.wait_for_timeout(2000)

                                    # Verify deletion - checkbox should be gone after page updates
                                    checkbox_after = page.locator(f'input.bulkCheck[value="{flow_id}"]').first
                                    if checkbox_after.count() == 0:
                                        return True

                                    raise ClientError(f"Failed to delete flow {flow_id}")

                            raise ClientError("Delete confirmation modal not found")

                    raise ClientError("Delete action not found")

        raise ClientError(f"Flow with ID {flow_id} not found")

    def create_flow(
        self,
        app_id: str,
        trigger_code: str,
        name: str,
        description: str = "",
        enabled: bool = True,
        steps: Optional[List[dict]] = None,
    ) -> FlowDetail:
        """Create a new flow in a Globiflow app.

        Navigates to the flow configuration page, fills in the form,
        optionally adds steps, and saves the flow.

        Args:
            app_id: The Podio app ID (numeric string)
            trigger_code: Trigger type code (C, U, M, etc. - use triggers list)
            name: Flow name
            description: Optional flow description
            enabled: Whether the flow should be enabled (default True)
            steps: Optional list of step configurations (dicts with action_type and params)

        Returns:
            FlowDetail model with the created flow's ID and details

        Raises:
            ClientError: If flow creation fails
        """
        import re

        # Navigate to the flow creation page with app_id and trigger type
        self.ensure_authenticated(f"/configureflow.php?i={app_id}&t={trigger_code}")
        page = self.browser.get_page()

        # Wait for the flow configuration form to load
        page.wait_for_selector("#flowName", timeout=10000)
        page.wait_for_timeout(1000)

        # Fill in flow name
        flow_name_input = page.locator("#flowName")
        flow_name_input.fill(name)

        # Fill in description if provided
        if description:
            # Description is the textbox after flow name
            desc_input = page.locator("textarea").first
            if desc_input.count() > 0:
                desc_input.fill(description)

        # Handle enabled/disabled state
        if not enabled:
            enabled_checkbox = page.locator("#enabled input[type='checkbox']").first
            if enabled_checkbox.count() > 0 and enabled_checkbox.is_checked():
                enabled_checkbox.uncheck()

        # Add steps if provided
        if steps:
            for step_config in steps:
                self._add_step_to_flow(page, step_config)

        # Click Save
        save_link = page.get_by_role("link", name="Save")
        if save_link.count() == 0:
            raise ClientError("Save button not found")

        save_link.click()
        page.wait_for_timeout(3000)  # Wait for save and redirect

        # Extract flow_id from the redirect URL
        # After save, URL becomes /flows.php?node={flow_id}
        current_url = page.url
        flow_id_match = re.search(r"node=(\d+)", current_url)
        if not flow_id_match:
            # Try extracting from heading if we're on the flow page
            heading = page.locator("h4").filter(has_text="Flow:").first
            if heading.count() > 0:
                heading_text = heading.text_content()
                id_match = re.search(r"\(ID:(\d+)\)", heading_text)
                if id_match:
                    flow_id = id_match.group(1)
                else:
                    raise ClientError("Could not extract flow ID after creation")
            else:
                raise ClientError("Could not extract flow ID from redirect URL")
        else:
            flow_id = flow_id_match.group(1)

        # Return the created flow details
        return self.get_flow(flow_id)

    def _add_step_to_flow(self, page: "Page", step_config: dict):
        """Add a step to a flow being configured.

        Args:
            page: Playwright page object
            step_config: Dict with 'action_type' and other step parameters
        """
        action_type = step_config.get("action_type", "")
        if not action_type:
            raise ClientError("Step configuration must include 'action_type'")

        # Map action_type to UI text
        action_type_map = {
            # Logic steps
            "Create a new Variable": "Custom Variable / Calc",
            "Custom Variable": "Custom Variable / Calc",
            "VariableCalcStep": "Custom Variable / Calc",
            "If (Sanity Check)": "If (Sanity Check)",
            "IfSanityCheckStep": "If (Sanity Check)",
            "End If": "End If",
            "For Each": "For Each",
            "ForEachStep": "For Each",
            "Continue": "Continue",
            "Wait": "Wait (Delay)",
            "Sort Collected": "Sort Collected",
            "Clear Collected": "Clear Collected Item(s)",

            # Actions
            "Remote HTTP Call": "Remote HTTP Call",
            "HttpCallStep": "Remote HTTP Call",
            "Capture Result of a Remote HTTP Call": "Remote HTTP Call",
            "Send Email": "Send Email",
            "SendEmailStep": "Send Email",
            "Send SMS": "Send SMS Text",
            "SendSmsStep": "Send SMS Text",
            "Send Message": "Send Message",
            "SendMessageStep": "Send Message",
            "Add Comment": "Add Comment",
            "AddCommentStep": "Add Comment",
            "Assign Task": "Assign Task",
            "AssignTaskStep": "Assign Task",
            "Update Item": "Update Item",
            "UpdateItemStep": "Update Item",
            "Create Item": "Create Item",
            "CreateItemStep": "Create Item",
            "Make a PDF": "Make a PDF",
            "MakePdfStep": "Make a PDF",
            "Trigger Flow": "Trigger Flow",
            "TriggerFlowStep": "Trigger Flow",
            "Delete Item": "Delete Item",

            # Collectors
            "Get Referenced Item": "Get Referenced Item(s)",
            "GetReferencedItemsCollector": "Get Referenced Item(s)",
            "Search for Item": "Search for Item(s)",
            "SearchForItemsCollector": "Search for Item(s)",
            "Get Podio View": "Get Podio View",
            "GetPodioViewCollector": "Get Podio View",
        }

        ui_action_type = action_type_map.get(action_type, action_type)

        # Click the "+" button in the Actions section
        add_action_btn = page.locator("#actions").get_by_role("link", name="+")
        if add_action_btn.count() == 0:
            raise ClientError("Could not find add action button")

        add_action_btn.click()
        page.wait_for_timeout(500)

        # Find and click the action type in the step selection dropdown
        # After clicking "+", a search/select box appears - type to filter and select
        # The step type selection uses a text input that filters options
        step_search = page.locator("#actions li").last.locator("input[type='text']").first
        if step_search.count() > 0 and step_search.is_visible():
            step_search.fill(ui_action_type)
            page.wait_for_timeout(500)
            # Click the matching option in the dropdown
            dropdown_option = page.locator(f".sidebarblock:has-text('{ui_action_type}')").first
            if dropdown_option.count() > 0:
                # Use JavaScript click to bypass viewport restrictions
                dropdown_option.evaluate("el => el.click()")
                page.wait_for_timeout(500)
            else:
                raise ClientError(f"Could not find action type in dropdown: {ui_action_type}")
        else:
            # Fallback: try clicking directly in sidebar with JS
            action_option = page.locator(f".sidebarblock:has-text('{ui_action_type}')").first
            if action_option.count() == 0:
                raise ClientError(f"Could not find action type: {ui_action_type}")
            action_option.evaluate("el => el.click()")
            page.wait_for_timeout(500)

        # Fill in step-specific fields based on step_config
        # Remove action_type from config since we've handled it
        params = {k: v for k, v in step_config.items() if k != "action_type"}

        for field_name, value in params.items():
            self._fill_step_field(page, field_name, value)

    def _fill_step_field(self, page: "Page", field_name: str, value: str):
        """Fill a field in the step configuration form.

        Args:
            page: Playwright page object
            field_name: Field name (e.g., 'variable_name', 'code', 'url')
            value: Value to fill
        """
        # Map field names to selectors
        field_selector_map = {
            "variable_name": "input[placeholder='Variable Name']",
            "code": "textarea[name*='gmvalue']",
            "url": "textarea[id^='gmurl']",
            "method": "select[name*='method']",
            "headers": "textarea[name*='gmheaders']",
            "get_params": "textarea[name*='gmget']",
            "post_params": "textarea[name*='gmpost']",
            "to": "input[name*='to']",
            "subject": "input[name*='subject']",
            "body": "textarea[name*='body']",
            "message": "textarea[name*='message']",
            "comment_body": "textarea[name*='gmmessage']",  # Comment body uses gmmessage field
        }

        selector = field_selector_map.get(field_name)
        if not selector:
            # Try generic approach - look for input/textarea with matching name or placeholder
            selector = f"input[name*='{field_name}'], textarea[name*='{field_name}'], input[placeholder*='{field_name}']"

        # Find the field - look in the last step added (most recent li)
        last_step = page.locator("#actions li").last
        field = last_step.locator(selector).first

        if field.count() == 0:
            # Field not found, skip silently (may not be applicable to this step type)
            return

        # Determine input type and fill accordingly
        tag_name = field.evaluate("el => el.tagName.toLowerCase()")
        if tag_name == "select":
            field.select_option(label=str(value))
        elif tag_name == "textarea":
            element_id = field.get_attribute("id")
            # For textareas, try gMention handling first (for fields with variable references)
            if element_id and self._fill_mention_field(page, element_id, str(value)):
                pass  # Successfully filled via gMention
            else:
                # Check if gMention has a contenteditable div for this textarea
                if element_id:
                    # gMention creates a div with class gMention and data-for attribute
                    filled_via_div = page.evaluate(f"""(value) => {{
                        // Try contenteditable div first
                        const editableDiv = document.querySelector('.gMention[data-for="{element_id}"]');
                        if (editableDiv && editableDiv.contentEditable === 'true') {{
                            editableDiv.innerHTML = value;
                            editableDiv.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            // Also update the hidden textarea
                            const textarea = document.getElementById('{element_id}');
                            if (textarea) textarea.value = value;
                            return true;
                        }}
                        return false;
                    }}""", str(value))
                    if filled_via_div:
                        pass  # Successfully filled via contenteditable div
                    else:
                        # Standard fill
                        field.fill(str(value))
                else:
                    field.fill(str(value))
        elif tag_name == "input":
            field.fill(str(value))

    def get_flow(self, flow_id: str, include_steps: bool = False) -> FlowDetail:
        """Get detailed information about a specific flow.

        Iterates through all flows to find one matching the given ID,
        then extracts its details.

        Args:
            flow_id: The flow ID to retrieve
            include_steps: If True, also fetch and include step details

        Returns:
            FlowDetail model with time savings, notes, and optionally steps
        """
        import re

        self.ensure_authenticated("/flows.php")
        page = self.browser.get_page()

        # Wait for tree to load
        page.wait_for_selector('[role="treeitem"]', timeout=10000)

        # Click "Expand All" to show full tree
        expand_link = page.get_by_role("link", name="Expand All")
        if expand_link.count() > 0:
            expand_link.click()
            page.wait_for_timeout(2000)

        # Get all tree items at level 3 (apps) with flow counts
        tree_items = page.locator('[role="treeitem"]').all()
        apps_with_flows = []
        for item in tree_items:
            text = _clean(item.text_content())
            level = item.get_attribute("aria-level")
            if level == "3":
                match = re.match(r"(.+) \((\d+)\)", text)
                if match and int(match.group(2)) > 0:
                    apps_with_flows.append(text)

        # Search through each app's flows
        for app_text in apps_with_flows:
            app_item = page.get_by_role("treeitem", name=app_text)
            if app_item.count() > 0:
                app_item.click()
                page.wait_for_timeout(1500)

                # Find flow items in the list (after the separator)
                flow_container = page.locator("hr ~ div").first
                if flow_container.count() > 0:
                    flow_divs = flow_container.locator("> div").all()

                    for flow_div in flow_divs:
                        flow_name_text = _clean(flow_div.text_content())
                        if flow_name_text.startswith("With Selected:"):
                            continue

                        # Click this flow to check its ID
                        flow_div.click()
                        page.wait_for_timeout(1000)

                        # Check if this is the flow we're looking for
                        heading = page.locator("h4").filter(has_text="Flow:").first
                        if heading.count() > 0:
                            heading_text = heading.text_content()
                            heading_match = re.search(r"\(ID:(\d+)\)", heading_text)
                            if heading_match and heading_match.group(1) == flow_id:
                                # Found it! Extract details
                                flow_detail = self._extract_flow_details(page, flow_id)
                                # Optionally include steps
                                if include_steps:
                                    flow_detail.steps = self.list_flow_steps(flow_id)
                                return flow_detail

        # Flow not found
        raise ClientError(f"Flow with ID {flow_id} not found")

    def list_flow_logs(self, flow_id: str) -> List[FlowLog]:
        """Get all execution logs for a flow.

        Navigates directly to the flow configuration page and clicks the
        Logs tab to retrieve all execution log entries.

        Args:
            flow_id: The flow ID

        Returns:
            List of FlowLog models with timestamp, item_id, and entry

        Raises:
            ClientError: If flow not found or has no logs
        """
        import re

        # Navigate directly to the flow configuration page
        self.ensure_authenticated(f"/configureflow.php?id={flow_id}")
        page = self.browser.get_page()

        # Wait for the page to load
        page.wait_for_timeout(2000)

        # Click the Logs tab
        logs_link = page.locator("a").filter(has_text=re.compile(r"Logs")).first
        if logs_link.count() == 0:
            raise ClientError(f"Flow {flow_id} has no logs tab")

        logs_link.click()
        page.wait_for_timeout(1500)

        # Extract log entries from the logs panel
        # Logs are in plain text format:
        # "YYYY-MM-DD HH:MM:SS : ITEM_ID : Log Entry"
        logs = []

        # Get all text content from the page body
        content = page.locator("body").text_content()

        # Parse log entries - they are concatenated without newlines
        # Format: "2025-12-29 11:00:59 : 3223678304 : Triggered FlowItem.create"
        # Use lookahead to find entries that end before the next timestamp
        log_pattern = re.compile(
            r"(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s*:\s*(\d+)\s*:\s*(.+?)(?=\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}|$)"
        )

        for match in log_pattern.finditer(content):
            timestamp = match.group(1).strip()
            item_id = match.group(2).strip()
            message = match.group(3).strip()

            # Determine log level based on message content
            log_level = "error" if message.lower().startswith("error:") else "info"

            if timestamp and item_id and message:
                logs.append(FlowLog(
                    timestamp=timestamp,
                    item_id=item_id,
                    message=message,
                    log_level=log_level,
                ))

        return logs

    def _extract_flow_details(self, page: "Page", flow_id: str) -> FlowDetail:
        """Extract flow details from the currently selected flow.

        Args:
            page: Playwright page object
            flow_id: The flow ID

        Returns:
            FlowDetail model
        """
        import re

        # Parse flow heading: "Flow: {name} (ID:{flow_id})"
        heading = page.locator("h4").filter(has_text="Flow:").first
        heading_text = (heading.text_content() or "") if heading.count() > 0 else ""

        heading_match = re.search(r"Flow:\s*(.+?)\s*\(ID:(\d+)\)", heading_text)
        flow_name = heading_match.group(1).strip() if heading_match else ""
        extracted_id = heading_match.group(2) if heading_match else flow_id

        # Get time savings from tab link (e.g., "Saves 8-11 mins")
        time_savings = None
        saves_link = page.locator("a").filter(has_text=re.compile(r"Saves \d+-\d+ mins")).first
        if saves_link.count() > 0:
            saves_text = saves_link.text_content() or ""
            time_savings = saves_text.strip() or None

        # Check for notes - click Notes tab and get content
        notes = None
        notes_link = page.locator("a").filter(has_text="Notes").first
        if notes_link.count() > 0:
            notes_link.click()
            page.wait_for_timeout(500)
            notes_area = page.locator("textarea").first
            if notes_area.count() > 0:
                notes = notes_area.input_value()
            # Click back to Recipe tab
            recipe_link = page.locator("a").filter(has_text="Recipe").first
            if recipe_link.count() > 0:
                recipe_link.click()

        # Check for logs tab
        logs_link = page.locator("a").filter(has_text="Logs").first
        has_logs = logs_link.count() > 0

        # Determine enabled status from img in the flow list or heading
        enabled = True
        # The flow heading has an edit link and potentially a status icon

        return FlowDetail(
            id=extracted_id,
            name=flow_name,
            enabled=enabled,
            time_savings=time_savings,
            notes=notes,
            has_logs=has_logs,
        )

    def _extract_step_parameters(self, action_div: "Locator") -> dict:
        """Extract parameters from a step's action div.

        Args:
            action_div: The locator for the step's main content div

        Returns:
            Dict with parameter names and values
        """
        import re

        parameters = {}

        # Map input name patterns to parameter names
        name_pattern_map = {
            r"varname\d*": "Variable Name",
            r"gmvalue\d*": "expression",
            r"gmurl\d*": "URL",
            r"url\d*": "URL",
            r"method\d*": "Method",
            r"gmheaders\d*": "Headers",
            r"headers\d*": "Headers",
            r"gmget\d*": "GET Parameters",
            r"getparams\d*": "GET Parameters",
            r"gmpost\d*": "POST Parameters",
            r"postparams\d*": "POST Parameters",
            r"subject\d*": "Subject",
            r"body\d*": "Body",
            r"to\d*": "To",
            r"from\d*": "From Name",
            r"cc\d*": "CC",
            r"bcc\d*": "BCC",
            r"gmmessage\d*": "Comment",  # Comment body uses gmmessage field
            r"comment\d*": "Comment",
            r"message\d*": "Message",
            r"filename\d*": "Filename",
            r"template\d*": "Template",
        }

        # Extract all inputs and textareas
        all_inputs = action_div.locator("input[type='text'], textarea").all()
        for inp in all_inputs:
            name = inp.get_attribute("name") or ""
            placeholder = inp.get_attribute("placeholder") or ""
            value = inp.input_value()

            # For gMention fields, the value might be stored in a sibling div or via JS
            # Try to get the visible text from the gMention container if input_value is empty
            if not value:
                element_id = inp.get_attribute("id")
                if element_id:
                    # Try to get text from gMention's display div
                    mention_container = action_div.locator(f".gMention[data-for='{element_id}'], .mention-wrapper[data-id='{element_id}']").first
                    if mention_container.count() > 0:
                        value = _clean(mention_container.text_content())
                    else:
                        # Try evaluating the element's textContent directly
                        try:
                            value = inp.evaluate("el => el.textContent || el.value || ''").strip()
                        except Exception:
                            pass

            if not value:
                continue

            # Determine parameter name from placeholder first, then name pattern
            param_name = None
            if placeholder:
                param_name = placeholder
            else:
                for pattern, mapped_name in name_pattern_map.items():
                    if re.match(pattern, name, re.IGNORECASE):
                        param_name = mapped_name
                        break

            if param_name:
                parameters[param_name] = value

        # Extract from select dropdowns
        selects = action_div.locator("select").all()
        for select in selects:
            name = select.get_attribute("name") or ""
            selected = select.locator("option[selected]").first
            if selected.count() > 0:
                value = _clean(selected.text_content())
                if value:
                    # Map select name to parameter
                    if "method" in name.lower():
                        parameters["Method"] = value
                    elif "direction" in name.lower():
                        parameters["Direction"] = value
                    elif "operator" in name.lower():
                        parameters["Operator"] = value

        # Extract from labeled table cells (for parameters with explicit labels)
        tables = action_div.locator("table").all()
        for table in tables:
            rows = table.locator("tr").all()
            for row in rows:
                cells = row.locator("td").all()
                if len(cells) >= 2:
                    # Get label from first cell
                    label_text = _clean(cells[0].text_content()).rstrip(":")
                    if not label_text or label_text in parameters:
                        continue

                    # Check for value in second cell
                    combo = cells[1].locator("select").first
                    if combo.count() > 0:
                        selected = combo.locator("option[selected]").first
                        param_value = _clean(selected.text_content()) if selected.count() > 0 else ""
                    else:
                        textbox = cells[1].locator("input[type='text'], textarea").first
                        if textbox.count() > 0:
                            param_value = textbox.input_value()
                        else:
                            display_div = cells[1].locator("> div > div").first
                            if display_div.count() > 0:
                                param_value = _clean(display_div.text_content())
                            else:
                                param_value = _clean(cells[1].text_content()).split("\n")[0]

                    if label_text and param_value:
                        parameters[label_text] = param_value

        return parameters

    def _normalize_parameters(self, parameters: dict) -> dict:
        """Normalize scraped parameter names to model field names.

        Args:
            parameters: Raw parameter dict from page scraping

        Returns:
            Dict with normalized field names
        """
        # Map scraped parameter names to model field names
        param_mappings = {
            # Variable/Calc fields
            "expression": "code",
            "Expression": "code",
            "Variable Name": "variable_name",
            "variable_name": "variable_name",

            # HTTP Call fields
            "URL": "url",
            "url": "url",
            "From URL": "url",
            "Method": "method",
            "method": "method",
            "Headers": "headers",
            "Header(s)": "headers",
            "Custom Headers": "headers",
            "GET Parameters": "get_params",
            "POST Parameters": "post_params",
            "POST/Body Parameters": "post_params",
            "Follow Redirect": "follow_redirect",

            # Filter fields
            "Field": "field",
            "Operator": "operator",
            "Value": "value",
            "Match Type": "match_type",
            "Check Type": "check_type",
            "User": "user",

            # Collector fields
            "App": "app",
            "Get Items from App": "app",
            "Search in App": "app",
            "In App": "app",
            "Direction": "direction",
            "Using Field": "using_field",
            "Search Field": "search_field",
            "Search Value": "search_value",
            "View": "view",
            "Limit": "limit",

            # Logic fields
            "Sort By": "sort_by",
            "Sort Direction": "sort_direction",
            "Collector": "collector",
            "Iterate Over": "iterate_over",
            "Columns": "columns",
            "Include Header": "include_header",

            # Email/Message fields
            "To": "to",
            "From Name": "from_name",
            "Reply To": "reply_to",
            "CC": "cc",
            "BCC": "bcc",
            "Subject": "subject",
            "Body": "body",
            "Message": "message",
            "Reply Handling": "reply_handling",
            "Attach Files": "attach_files",
            "File Pattern": "file_pattern",

            # Comment fields
            "Comment": "comment_body",
            "Comment Body": "comment_body",
            "Silent": "silent",

            # Task fields
            "Assignee": "assignee",
            "Task Text": "task_text",
            "Task": "task_text",
            "Due Date": "due_date",
            "Reminder": "reminder",
            "Which Tasks": "which_tasks",
            "Task Pattern": "task_pattern",

            # Item fields
            "Fields": "fields",
            "Authentication": "authentication",
            "Hook Event": "hook_event",
            "Trigger Hook": "hook_event",
            "Email": "email",

            # PDF fields
            "Template": "template",
            "Filename": "filename",
            "File Name": "filename",
            "Page Size": "page_size",
            "Orientation": "orientation",

            # File fields
            "Source": "source",
            "Pattern": "pattern",
            "Which Files": "which_files",

            # Flow fields
            "Flow": "flow",
            "Trigger Flow": "flow",
            "Relationship Field": "relationship_field",

            # Widget fields
            "Workspace": "workspace",
            "Widget": "widget",
            "Content": "content",

            # Display fields
            "Title": "title",
            "Page Title": "title",
        }

        normalized = {}
        for key, value in parameters.items():
            mapped_key = param_mappings.get(key, key)

            # Convert types for certain fields
            if mapped_key == "method":
                try:
                    normalized[mapped_key] = HttpMethod(value.upper())
                except ValueError:
                    normalized[mapped_key] = value
            elif mapped_key == "direction":
                # Direction values from UI include descriptions like "FORWARD: Only Items that..."
                # Extract just the enum value (first word before colon or space-description)
                direction_value = value.split(":")[0].strip().upper()
                try:
                    normalized[mapped_key] = RelationshipDirection(direction_value)
                except ValueError:
                    normalized[mapped_key] = value
            elif mapped_key == "limit":
                try:
                    normalized[mapped_key] = int(value)
                except (ValueError, TypeError):
                    normalized[mapped_key] = value
            elif mapped_key in ("follow_redirect", "include_header", "silent", "hook_event"):
                if isinstance(value, bool):
                    normalized[mapped_key] = value
                else:
                    normalized[mapped_key] = str(value).lower() in ("true", "yes", "1", "on")
            else:
                normalized[mapped_key] = value

        return normalized

    def _fill_mention_field(self, page: "Page", element_id: str, value: str) -> bool:
        """Fill a Globiflow mention field, properly handling variable references.

        Detects variable reference patterns like [(Type) name] and uses the page's
        insertAtCursorMention function to insert them properly so they appear as
        linked/highlighted tokens rather than plain text.

        Token internal_id formats differ by type:
        - Flow variables: 'pfprepfield:{var_name}' e.g., 'pfprepfield:http_body'
        - Podio fields: field's external_id e.g., 'podio_item_id', 'title'

        Since Podio field internal_ids can't be derived from display names,
        this method triggers the token picker to load tokens, then reads them.

        Args:
            page: Playwright page object
            element_id: The textarea element ID (e.g., 'gmpost3', 'gmurl3')
            value: The value to insert, may contain variable references

        Returns:
            True if handled via gMention, False if should use standard fill

        Raises:
            ClientError: If a referenced token does not exist in the flow
        """
        import re

        # Pattern to match variable references: [(Type) name]
        # Examples: [(Variable) webhook_body], [(Topic) Podio Item ID]
        var_pattern = re.compile(r'\[\(([^)]+)\)\s+([^\]]+)\]')

        matches = list(var_pattern.finditer(value))
        if not matches:
            # No variable references, use standard fill
            return False

        # Check if gMention is available
        has_gmention = page.evaluate("() => typeof window.gMention !== 'undefined'")
        if not has_gmention:
            return False

        # Tokens are loaded lazily when the token picker icon is clicked.
        # Find the icon for this element and click it to populate the dropdown.
        # Icon ID pattern: mimce{field_type}{step_number} where element_id is gm{field_type}{step_number}
        # e.g., gmvalue2 -> mimcevalue2, gmpost3 -> mimcepost3
        icon_id = "mimce" + element_id[2:]  # Strip 'gm' prefix, add 'mimce'

        # Click the token picker icon to load tokens
        icon_clicked = page.evaluate(f"""() => {{
            const icon = document.querySelector('#{icon_id}');
            if (icon) {{
                icon.click();
                return true;
            }}
            return false;
        }}""")

        if not icon_clicked:
            # No token picker icon found - can't load tokens
            return False

        # Wait for tokens to load - showMceDropMenu may make an AJAX call
        page.wait_for_timeout(500)

        # Build a lookup table of available tokens from the page
        # This extracts tokens from insertAtCursorMention onclick handlers
        # Format: { "(Type) Name": "internal_id", ... }
        token_lookup = page.evaluate("""() => {
            const tokens = {};
            document.querySelectorAll('[onclick*="insertAtCursorMention"]').forEach(el => {
                const onclick = el.getAttribute('onclick');
                // Parse: insertAtCursorMention('elementId', 'internalId', 'displayValue')
                const match = onclick.match(/insertAtCursorMention\\s*\\(\\s*'[^']+',\\s*'([^']+)',\\s*'([^']+)'/);
                if (match) {
                    const internalId = match[1];
                    const displayValue = match[2];  // e.g., "(Variable) http_body" or "(Topic) Podio Item ID"
                    tokens[displayValue] = internalId;
                }
            });
            return tokens;
        }""")

        # Close the token picker dropdown (click the 'x' link)
        dropdown_id = "mcedropper" + element_id[2:]  # e.g., gmvalue2 -> mcedroppervalue2
        page.evaluate(f"""() => {{
            const dropdown = document.querySelector('#{dropdown_id}');
            if (dropdown) {{
                dropdown.style.display = 'none';
            }}
        }}""")

        # Validate all referenced tokens exist and get their internal_ids
        token_ids = {}  # Map display_value -> internal_id for tokens we'll insert
        for match in matches:
            var_type = match.group(1).strip()  # e.g., "Variable", "Topic"
            var_name = match.group(2).strip()  # e.g., "webhook_body", "Podio Item ID"
            display_value = f"({var_type}) {var_name}"

            if display_value in token_lookup:
                token_ids[display_value] = token_lookup[display_value]
            else:
                # Token not found - provide helpful error
                # Find similar tokens for the error message
                similar = [k for k in token_lookup.keys() if var_type in k][:5]
                similar_msg = f" Similar available: {', '.join(similar)}" if similar else ""
                raise ClientError(
                    f"Token '{display_value}' does not exist in this flow.{similar_msg}"
                )

        # Clear the textarea first
        page.evaluate(f"""() => {{
            const textarea = document.querySelector('#{element_id}');
            if (textarea) {{
                textarea.value = '';
                textarea.focus();
            }}
        }}""")

        # Process the value - insert text and tokens in order
        last_end = 0
        for match in matches:
            # Insert any plain text before this token
            if match.start() > last_end:
                plain_text = value[last_end:match.start()]
                if plain_text:
                    page.evaluate(f"""(text) => {{
                        const textarea = document.querySelector('#{element_id}');
                        if (textarea) {{
                            const start = textarea.selectionStart;
                            const before = textarea.value.substring(0, start);
                            const after = textarea.value.substring(textarea.selectionEnd);
                            textarea.value = before + text + after;
                            textarea.selectionStart = textarea.selectionEnd = start + text.length;
                        }}
                    }}""", plain_text)

            # Get the display value and its internal_id
            var_type = match.group(1).strip()
            var_name = match.group(2).strip()
            display_value = f"({var_type}) {var_name}"
            internal_id = token_ids[display_value]

            # Use insertAtCursorMention (the global function used by onclick handlers)
            # This properly creates the highlighted overlay span
            page.evaluate(f"""() => {{
                window.insertAtCursorMention(
                    '{element_id}',
                    '{internal_id}',
                    '{display_value}'
                );
            }}""")

            last_end = match.end()

        # Insert any remaining plain text after the last token
        if last_end < len(value):
            remaining_text = value[last_end:]
            if remaining_text:
                page.evaluate(f"""(text) => {{
                    const textarea = document.querySelector('#{element_id}');
                    if (textarea) {{
                        const start = textarea.selectionStart;
                        const before = textarea.value.substring(0, start);
                        const after = textarea.value.substring(textarea.selectionEnd);
                        textarea.value = before + text + after;
                        textarea.selectionStart = textarea.selectionEnd = start + text.length;
                    }}
                }}""", remaining_text)

        # Trigger blur to finalize
        page.evaluate(f"""() => {{
            const textarea = document.querySelector('#{element_id}');
            if (textarea) textarea.blur();
        }}""")

        return True

    def _get_field_selector(self, action_div: "Locator", field_name: str) -> "Locator":
        """Get the UI element selector for a model field name.

        Args:
            action_div: The step's main content locator
            field_name: Model field name (e.g., 'variable_name', 'code', 'url')

        Returns:
            Playwright Locator for the field's input element

        Raises:
            ClientError: If field selector not found
        """
        selectors = FIELD_SELECTORS.get(field_name, [])
        for selector in selectors:
            # Try to find all matching elements and filter for visible ones
            elements = action_div.locator(selector).all()
            for element in elements:
                if element.count() > 0 and element.is_visible():
                    return element
        raise ClientError(f"Cannot find UI element for field '{field_name}'")

    def _validate_fields_for_step_type(self, action_type: str, fields: dict) -> None:
        """Validate that fields are appropriate for the step type.

        Args:
            action_type: The action type string from the step
            fields: Dict of field_name -> value to validate

        Raises:
            ClientError: If any field is not valid for this step type
        """
        from .models.step import _STEP_TYPE_MAPPINGS

        # Find the matching step class
        step_class = None
        for pattern, cls, cat in _STEP_TYPE_MAPPINGS:
            if pattern.lower() in action_type.lower():
                step_class = cls
                break

        if step_class is None:
            raise ClientError(f"Unknown action type: {action_type}")

        # Get valid fields for this step class
        valid_fields = set(step_class.model_fields.keys())

        # Exclude base fields that aren't updatable
        base_fields = {'step_number', 'action_type', 'category', 'action_cost', 'parameters', 'flow_id'}
        updatable_fields = valid_fields - base_fields

        # Check each provided field
        for field_name in fields.keys():
            if field_name not in updatable_fields:
                raise ClientError(
                    f"Field '{field_name}' is not valid for step type '{action_type}'. "
                    f"Valid fields: {sorted(updatable_fields)}"
                )

    def list_flow_steps(self, flow_id: str) -> List[AnyStep]:
        """List all steps in a flow with their actual configured values.

        Navigates to the flow configuration page and extracts all steps
        with their types and actual parameter values. Returns the most
        specific step model type based on the action_type.

        Args:
            flow_id: The flow ID

        Returns:
            List of step models (specific types based on action_type)
        """
        self.ensure_authenticated(f"/configureflow.php?id={flow_id}")
        page = self.browser.get_page()

        # Wait for the actions step list to load. The steps live in
        # ul#flowactions (a stable element id), not under a heading: the page
        # renders two "Actions" h4 headings (a sidebar palette labelled
        # "Actions" plus the real "Actions (... then do the following:)"
        # section), so matching on heading text is ambiguous and unreliable.
        page.wait_for_selector("ul#flowactions", timeout=10000)
        page.wait_for_timeout(2000)  # Allow time for all step content to render

        steps = []

        # The action steps are the direct <li> children of ul#flowactions.
        actions_section = page.locator("ul#flowactions")
        if actions_section.count() == 0:
            return steps

        step_items = actions_section.locator("> li").all()

        for idx, item in enumerate(step_items, start=1):
            step_number = idx

            # Get the action type - it's in the first div
            action_div = item.locator("> div").first
            if action_div.count() > 0:
                # Use inner_text which handles whitespace better
                full_text = action_div.inner_text()

                # Split by newlines and take the first non-empty line
                lines = [l.strip() for l in full_text.split("\n") if l.strip()]
                action_type = lines[0] if lines else "Unknown"

                # Stop at common patterns that indicate parameter/option sections
                stop_patterns = [" (opt)", " (a=", "(a=", "Options:", "Select ", "Get Items from", " = "]
                for pattern in stop_patterns:
                    if pattern in action_type:
                        pattern_idx = action_type.find(pattern)
                        if pattern_idx > 0:
                            action_type = action_type[:pattern_idx].strip()
                            break

                # Clean up any trailing colons, parentheses, or equals
                action_type = action_type.rstrip(":").rstrip("(").rstrip("=").strip()

                # Truncate long action types
                if len(action_type) > 80:
                    action_type = action_type[:77] + "..."

                # Extract and normalize parameters from the step
                raw_params = self._extract_step_parameters(action_div)
                normalized_params = self._normalize_parameters(raw_params)

                # Use factory to create the appropriate step model
                step = create_step(
                    step_number=step_number,
                    action_type=action_type if action_type else "Unknown",
                    parameters=normalized_params,
                )
                steps.append(step)

        return steps

    def get_flow_step(self, flow_id: str, step_number: int) -> AnyStep:
        """Get detailed information about a specific step in a flow.

        Args:
            flow_id: The flow ID
            step_number: The step number (1-based)

        Returns:
            Specific step model (e.g., HttpCallStep, VariableCalcStep)
        """
        self.ensure_authenticated(f"/configureflow.php?id={flow_id}")
        page = self.browser.get_page()

        # Wait for the actions step list to load (see list_flow_steps for why we
        # anchor on the stable ul#flowactions id instead of an "Actions" heading).
        page.wait_for_selector("ul#flowactions", timeout=10000)
        page.wait_for_timeout(2000)  # Allow time for all step content to render

        # The action steps are the direct <li> children of ul#flowactions.
        actions_section = page.locator("ul#flowactions")
        if actions_section.count() == 0:
            raise ClientError(f"Actions section not found in flow {flow_id}")

        # Find the specific step by index (1-based)
        step_items = actions_section.locator("> li").all()
        if step_number < 1 or step_number > len(step_items):
            raise ClientError(f"Step {step_number} not found in flow {flow_id} (has {len(step_items)} steps)")

        step_item = step_items[step_number - 1]

        # Get the action div
        action_div = step_item.locator("> div").first
        if action_div.count() == 0:
            raise ClientError(f"Step {step_number} has no content")

        # Extract action type from first line
        full_text = action_div.inner_text()
        lines = [l.strip() for l in full_text.split("\n") if l.strip()]
        action_type = lines[0] if lines else "Unknown"

        # Clean action type string
        for pattern in [" (opt)", " (a=", "(a=", "Options:", "Select ", "Get Items from", " = "]:
            if pattern in action_type:
                action_type = action_type[:action_type.find(pattern)].strip()
                break
        action_type = action_type.rstrip(":").rstrip("(").rstrip("=").strip()

        # Extract and normalize parameters
        raw_params = self._extract_step_parameters(action_div)
        normalized_params = self._normalize_parameters(raw_params)

        # Use factory with flow_id to get specific step type
        return create_step(
            step_number=step_number,
            action_type=action_type if action_type else "Unknown",
            parameters=normalized_params,
            flow_id=flow_id,
        )

    def update_flow_step(
        self,
        flow_id: str,
        step_number: int,
        updates: dict
    ) -> AnyStep:
        """Update specific fields of a step in a flow.

        Args:
            flow_id: The flow ID
            step_number: The step number (1-based)
            updates: Dict of field_name -> new_value to update

        Returns:
            Updated specific step model (e.g., HttpCallStep, VariableCalcStep)

        Raises:
            ClientError: If step not found or fields don't match step type
        """
        self.ensure_authenticated(f"/configureflow.php?id={flow_id}")
        page = self.browser.get_page()

        # Wait for the actions step list to load (see list_flow_steps for why we
        # anchor on the stable ul#flowactions id instead of an "Actions" heading).
        page.wait_for_selector("ul#flowactions", timeout=10000)
        page.wait_for_timeout(2000)

        # The action steps are the direct <li> children of ul#flowactions.
        actions_section = page.locator("ul#flowactions")
        if actions_section.count() == 0:
            raise ClientError(f"Actions section not found in flow {flow_id}")

        step_items = actions_section.locator("> li").all()
        if step_number < 1 or step_number > len(step_items):
            raise ClientError(f"Step {step_number} not found in flow {flow_id} (has {len(step_items)} steps)")

        step_item = step_items[step_number - 1]
        action_div = step_item.locator("> div").first
        if action_div.count() == 0:
            raise ClientError(f"Step {step_number} has no content")

        # Get action type for validation
        full_text = action_div.inner_text()
        lines = [l.strip() for l in full_text.split("\n") if l.strip()]
        action_type = lines[0] if lines else "Unknown"
        for pattern in [" (opt)", " (a=", "(a=", "Options:", "Select ", "Get Items from", " = "]:
            if pattern in action_type:
                action_type = action_type[:action_type.find(pattern)].strip()
                break
        action_type = action_type.rstrip(":").rstrip("(").rstrip("=").strip()

        # Validate fields for this step type
        self._validate_fields_for_step_type(action_type, updates)

        # Expand options section if needed (for fields like headers, follow_redirect)
        opt_link = action_div.locator("a:has-text('(opt)')").first
        if opt_link.count() > 0:
            opt_link.click()
            page.wait_for_timeout(500)

        # Fill in the updated fields
        skipped_fields = []
        updated_fields = []
        for field_name, new_value in updates.items():
            try:
                selector = self._get_field_selector(action_div, field_name)
            except ClientError:
                # Field not found in UI
                skipped_fields.append(field_name)
                continue
            updated_fields.append(field_name)

            # Handle different input types
            tag_name = selector.evaluate("el => el.tagName.toLowerCase()")
            if tag_name == "select":
                selector.select_option(label=str(new_value))
            elif tag_name == "textarea":
                # Get element ID for gMention handling
                element_id = selector.get_attribute("id")
                if element_id and not self._fill_mention_field(page, element_id, str(new_value)):
                    # No variable references or gMention unavailable, use standard fill
                    selector.fill(str(new_value))
            elif tag_name == "input":
                input_type = selector.get_attribute("type") or "text"
                if input_type == "checkbox":
                    if new_value:
                        selector.check()
                    else:
                        selector.uncheck()
                else:
                    selector.fill(str(new_value))

        # Check if any fields were actually updated
        if not updated_fields:
            raise ClientError(
                f"No fields could be updated. Fields not found in UI: {skipped_fields}. "
                f"The selector may not match the actual form element."
            )

        # Save the flow
        save_link = page.get_by_role("link", name="Save")
        if save_link.count() > 0:
            save_link.click()
            page.wait_for_timeout(2000)
        else:
            raise ClientError("Save button not found")

        # Return updated step details
        return self.get_flow_step(flow_id, step_number)

    def add_flow_step(self, flow_id: str, step_config: dict) -> "AnyStep":
        """Add a new step to an existing flow.

        Args:
            flow_id: The flow ID to add the step to
            step_config: Dict with 'action_type' and other step parameters.
                        Supported action types include:
                        - "Add Comment" - adds a comment to the item
                        - "Custom Variable" - creates a variable
                        - "Remote HTTP Call" - makes an HTTP request
                        - "Send Email" - sends an email
                        - etc.

        Returns:
            The newly added step details

        Example:
            client.add_flow_step("4314927", {
                "action_type": "Add Comment",
                "comment_body": "This is my comment text"
            })
        """
        self.ensure_authenticated(f"/configureflow.php?id={flow_id}")
        page = self.browser.get_page()

        # Get current step count before adding
        steps_before = page.locator("#actions li").count()

        # Add the step using existing method
        self._add_step_to_flow(page, step_config)

        # Save the flow
        save_link = page.get_by_role("link", name="Save")
        if save_link.count() == 0:
            raise ClientError("Save button not found")

        save_link.click()
        page.wait_for_timeout(3000)  # Wait for save

        # Return the newly added step (last step)
        new_step_number = steps_before + 1
        return self.get_flow_step(flow_id, new_step_number)


# ==================== Module-level Singleton ====================

_client: Optional[GlobiflowClient] = None


def get_client(profile_name: str = None) -> GlobiflowClient:
    """Get or create the global Globiflow client instance.

    Args:
        profile_name: Named profile to use (optional).

    Returns:
        GlobiflowClient instance.
    """
    global _client
    if _client is None:
        _client = GlobiflowClient(profile_name=profile_name)
    return _client
