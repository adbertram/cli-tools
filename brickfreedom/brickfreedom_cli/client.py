"""Brickfreedom client using BrowserAutomation from cli_tools_shared."""
import json
import random
import re
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

from cli_tools_shared.activity_log import get_activity_logger
from cli_tools_shared.auth import BrowserAutomationError
from cli_tools_shared.http_session import BrowserAuthState, BrowserAuthenticatedHttpClient
from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import print_warning

from .browser import BrickfreedomBrowser
from .config import get_config
from .models import (
    Platform,
    OrderStatus,
    Task,
    TaskResult,
    TaskList,
    OrderCost,
    Order,
    OrderList,
    ProcessedOrder,
    ProcessedOrderList,
    MissingPart,
    MissingPartList,
    ProcessResult,
    PostResult,
    ResolveResult,
    TrackingResult,
    create_task,
    create_order,
    create_processed_order,
    create_missing_part,
)

activity_logger = get_activity_logger("brickfreedom")

# Statuses indicating order has been picked/packed
PICKED_STATUSES = [OrderStatus.PROCESSED, OrderStatus.PACKED]

# Shared JavaScript function bodies (injected inside IIFEs at each call site).
# Used by list_orders, get_order, and get_brickfreedom_ids.
_JS_PARSE_ORDER_ROW = """
    function parseOrderRow(cells) {
        const platformText = cells[0].textContent?.trim().replace(/\\s+/g, ' ').split(' ')[0] || '';
        const platform = platformText === 'BL' ? 'bricklink' : platformText === 'BO' ? 'brickowl' : '';
        const orderIdLink = cells[1].querySelector('a');
        const rawOrderId = orderIdLink?.textContent?.trim() || '';
        const orderId = rawOrderId.replace(/^(BL|BO)/i, '');
        const lotsCell = cells[4];
        const lotsLink = lotsCell.querySelector('a[href*="order-picker"]');
        const lotsHref = lotsLink?.href || '';
        const bfIdMatch = lotsHref.match(/brickfreedom_order_id=(\\d+)/);
        const brickfreedomId = bfIdMatch ? bfIdMatch[1] : '';
        const buyerName = cells[2].textContent?.trim().replace(/[\\u{1F1E0}-\\u{1F1FF}]{2}/gu, '').trim() || '';
        const dateDiv = cells[3].querySelector('div');
        const dateText = dateDiv?.textContent?.trim() || cells[3].textContent?.trim() || '';
        const lotsItemsText = cells[4].textContent?.replace(/\\s+/g, ' ').trim() || '';
        const lotsItemsMatch = lotsItemsText.match(/(\\d+)\\s*\\/\\s*(\\d+)/);
        const lots = lotsItemsMatch ? parseInt(lotsItemsMatch[1], 10) : 0;
        const items = lotsItemsMatch ? parseInt(lotsItemsMatch[2], 10) : 0;
        const totalCell = cells[5];
        const allText = totalCell.textContent?.replace(/\\s+/g, ' ').trim() || '';
        const amounts = allText.match(/\\$?([\\d.]+)/g) || [];
        let subtotal = '0.00', shipping = '0.00', grandTotal = '0.00';
        if (amounts.length >= 3) {
            subtotal = amounts[0]; shipping = amounts[1]; grandTotal = amounts[2];
        } else if (amounts.length >= 1) {
            subtotal = amounts[0]; grandTotal = amounts[amounts.length - 1];
        }
        const statusCell = cells[cells.length - 1];
        const statusDiv = statusCell.querySelector('div');
        const status = (statusDiv?.textContent?.trim() || statusCell.textContent?.trim() || '').toUpperCase();
        return {
            order_id: orderId, brickfreedom_id: brickfreedomId, platform,
            date_ordered: dateText, buyer_name: buyerName, status,
            total_count: items, unique_count: lots,
            cost: { currency_code: 'USD', subtotal, shipping, grand_total: grandTotal }
        };
    }
"""

# Shared JavaScript: extract tracking ID from an order-postage list item.
_JS_EXTRACT_TRACKING = """
    function extractTrackingId(item) {
        const trackingInput = item.querySelector('input[placeholder*="Tracking"]');
        if (trackingInput) return trackingInput.value?.trim() || '';
        const allDivs = item.querySelectorAll('div');
        for (const div of allDivs) {
            const text = div.textContent?.trim();
            if (text) {
                const match = text.match(/Tracking ID\\s+(\\d{10,})/);
                if (match) return match[1];
            }
        }
        return '';
    }
"""


def _compute_order_flags(order_data: dict) -> None:
    """Set picked/shipped flags on order data dict based on status."""
    try:
        order_status = OrderStatus(order_data.get("status", ""))
        order_data["picked"] = order_status in PICKED_STATUSES
        order_data["shipped"] = order_status in [OrderStatus.SHIPPED, OrderStatus.RECEIVED]
    except ValueError:
        order_data["picked"] = False
        order_data["shipped"] = False


class BrickfreedomClient:
    """Client for interacting with Brickfreedom via browser automation."""

    def __init__(self):
        """Initialize Brickfreedom client."""
        self.config = get_config()
        self.BASE_URL = self.config.base_url
        self._browser = BrickfreedomBrowser(self.config)
        self._auth_state: Optional[BrowserAuthState] = None
        self._http_client: Optional[BrowserAuthenticatedHttpClient] = None
        self._auth_checked = False

    # ==================== Browser Helpers ====================

    def get_page(self, url: str = None):
        """Get a BrowserHarnessService backed by a persistent browser session."""
        try:
            if not self._auth_checked:
                self._auth_checked = True
                if not self._browser.is_authenticated():
                    raise ClientError(
                        "Not logged in. Run 'brickfreedom auth login -c browser_session' to authenticate."
                    )
            return self._browser.get_page(url)
        except BrowserAutomationError as e:
            raise ClientError(str(e)) from e

    def close(self):
        """Close browser session."""
        self._browser.close()
        self._http_client = None
        self._auth_state = None

    def _get_auth_state(self) -> BrowserAuthState:
        """Load the saved browser authentication state."""
        if self._auth_state is None:
            self._auth_state = BrowserAuthState.from_config(self.config)
        return self._auth_state

    def _cookie_domain(self) -> str:
        """Return the cookie domain used by BrickFreedom browser requests."""
        parsed = urlparse(self.BASE_URL)
        if not parsed.hostname:
            raise ClientError(f"BASE_URL does not contain a hostname: {self.BASE_URL}")
        return parsed.hostname

    def _get_http_client(self) -> BrowserAuthenticatedHttpClient:
        """Get the shared browser-authenticated HTTP client."""
        if self._http_client is None:
            self._http_client = BrowserAuthenticatedHttpClient(
                auth_state=self._get_auth_state(),
                allowed_domains=[self._cookie_domain()],
                timeout=30,
            )
        return self._http_client

    # ==================== Utility Methods ====================

    def extract_table(self, table: str = "table", headers: str = "thead th",
                      rows: str = "tbody tr", cells: str = "td") -> List[Dict]:
        """Extract data from HTML table as list of dicts."""
        page = self.get_page()
        t = page.locator(table)
        hdrs = [h.strip() for h in t.locator(headers).all_text_contents()]
        return [
            {hdrs[i]: c for i, c in enumerate(r.locator(cells).all_text_contents()[:len(hdrs)])}
            if hdrs else {f"col_{i}": c for i, c in enumerate(r.locator(cells).all_text_contents())}
            for r in t.locator(rows).all()
        ]

    def paginate(self, next_sel: str, extract: Callable, max_pages: int = 10) -> List:
        """Extract data across multiple pages."""
        page = self.get_page()
        data = []
        for _ in range(max_pages):
            data.extend(extract())
            btn = page.locator(next_sel)
            if btn.count() == 0 or not btn.is_enabled():
                break
            btn.click()
            page.wait_for_timeout(2000)
        return data

    def retry(self, action: Callable, attempts: int = 3, delay: int = 1000) -> Any:
        """Retry action with exponential backoff and jitter."""
        page = self.get_page()
        for i in range(attempts):
            try:
                return action()
            except Exception:
                if i == attempts - 1:
                    raise
                print_warning(f"Attempt {i+1} failed, retrying...")
                jitter = 1 + random.uniform(0, 0.1)
                page.wait_for_timeout(int(delay * (2 ** i) * jitter))

    def fetch_json(self, url: str) -> Any:
        """Fetch JSON using the saved browser-authenticated HTTP session."""
        body = self._get_http_client().get_text(url, headers={"Accept": "application/json"})
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise ClientError(f"Expected JSON response from {url}") from exc

    # ==================== Navigation Helpers ====================

    def _ensure_dashboard(self):
        """Navigate to dashboard."""
        page = self.get_page(f"{self.BASE_URL}/dashboard")
        page.wait_for_timeout(2000)

    def navigate(self, path: str):
        """Navigate to a path on Brickfreedom."""
        url = f"{self.BASE_URL}{path}" if not path.startswith("http") else path
        self.get_page(url)

    # ==================== Task Methods ====================

    @cached
    def list_tasks(self) -> TaskList:
        """List tasks from the My Tasks section on dashboard."""
        activity_logger.info("Listing tasks")
        self._ensure_dashboard()
        page = self.get_page()

        # Extract tasks from the My Tasks section
        tasks_data = page.evaluate("""() => {
            const taskList = [];
            const items = document.querySelectorAll('li[wire\\\\:sortable\\\\.item]');

            items.forEach((item, i) => {
                const textEl = item.querySelector('div[wire\\\\:click^="editTask"]');
                const text = textEl?.textContent?.trim();

                const svg = item.querySelector('svg');
                const svgPath = svg?.querySelector('path')?.getAttribute('d') || '';
                const isCompleted = !svgPath.startsWith('M256 8C119');
                const hasDeleteBtn = item.querySelector('button') !== null;

                if (text) {
                    taskList.push({
                        index: i + 1,
                        text,
                        completed: isCompleted || hasDeleteBtn
                    });
                }
            });
            return taskList;
        }""")

        tasks = [create_task(t) for t in tasks_data]
        return TaskList(tasks=tasks)

    def create_task(self, text: str) -> TaskResult:
        """Create a new task in My Tasks."""
        activity_logger.info("Creating task")
        self._ensure_dashboard()
        page = self.get_page()

        task_input = page.get_by_placeholder("Add task...")
        if task_input.count() == 0:
            raise ClientError("Could not find task input field on dashboard")

        task_input.fill(text)
        task_input.press("Enter")
        page.wait_for_timeout(1000)

        return TaskResult(success=True, task=text, message="Task created successfully")

    def _get_task_items(self):
        """Get task items from the list."""
        return self.get_page().locator('li[wire\\:sortable\\.item]').all()

    def complete_task(self, task_index: int) -> TaskResult:
        """Mark a task as complete by index (1-based)."""
        activity_logger.info("Completing task %s", task_index)
        self._ensure_dashboard()
        page = self.get_page()

        task_items = self._get_task_items()

        if task_index < 1 or task_index > len(task_items):
            raise ClientError(f"Task {task_index} not found. There are {len(task_items)} tasks.")

        item = task_items[task_index - 1]
        checkbox = item.locator("svg").first
        checkbox.click()
        page.wait_for_timeout(500)

        return TaskResult(success=True, message=f"Task {task_index} marked as complete")

    def delete_task(self, task_index: int) -> TaskResult:
        """Delete a completed task by index (1-based)."""
        activity_logger.info("Deleting task %s", task_index)
        self._ensure_dashboard()
        page = self.get_page()

        task_items = self._get_task_items()

        if task_index < 1 or task_index > len(task_items):
            raise ClientError(f"Task {task_index} not found. There are {len(task_items)} tasks.")

        item = task_items[task_index - 1]
        delete_btn = item.locator("button").first

        if delete_btn.count() == 0:
            raise ClientError(f"Task {task_index} has no delete button. Mark it complete first.")

        delete_btn.click()
        page.wait_for_timeout(500)

        return TaskResult(success=True, message=f"Task {task_index} deleted")

    def mark_all_completed(self) -> TaskResult:
        """Mark all tasks as completed."""
        activity_logger.info("Completing all tasks")
        self._ensure_dashboard()
        page = self.get_page()

        button = page.get_by_role("button", name="Mark all Completed")
        if button.count() == 0:
            raise ClientError('Could not find "Mark all Completed" button')

        button.click()
        page.wait_for_timeout(1000)

        return TaskResult(success=True, message="All tasks marked as completed")

    def delete_all_completed(self) -> TaskResult:
        """Delete all completed tasks."""
        activity_logger.info("Deleting all completed tasks")
        self._ensure_dashboard()
        page = self.get_page()

        button = page.get_by_role("button", name="Delete all Completed")
        if button.count() == 0:
            raise ClientError('Could not find "Delete all Completed" button')

        button.click()
        page.wait_for_timeout(1000)

        return TaskResult(success=True, message="All completed tasks deleted")

    # ==================== Order Methods ====================

    def _format_date(self, date_str: str) -> str:
        """Format date string to ISO format if possible."""
        if not date_str:
            return date_str
        return date_str.strip()

    @cached
    def list_orders(
        self,
        status: Optional[str] = None,
        platform: Optional[str] = None,
        picked: Optional[bool] = None,
        page_num: int = 1,
    ) -> OrderList:
        """List orders from BrickFreedom orders page."""
        activity_logger.info(
            "Listing orders status=%s platform=%s picked=%s page=%s",
            status,
            platform,
            picked,
            page_num,
        )
        page = self.get_page()

        url = f"{self.BASE_URL}/orders"
        if page_num > 1:
            url = f"{url}?page={page_num}"

        page.goto(url)
        page.wait_for_timeout(2000)

        orders_data = page.evaluate("() => {" + _JS_PARSE_ORDER_ROW + """
            const orderList = [];
            const rows = document.querySelectorAll('table tbody tr');
            rows.forEach((row) => {
                const cells = row.querySelectorAll('td');
                if (cells.length < 7) return;
                const data = parseOrderRow(cells);
                if (data.order_id && data.platform) orderList.push(data);
            });
            return orderList;
        }""")

        # Process orders and add computed flags
        orders = []
        for o in orders_data:
            o["date_ordered"] = self._format_date(o.get("date_ordered", ""))
            _compute_order_flags(o)
            orders.append(create_order(o))

        # Apply filters
        if status:
            status_filter = status.upper()
            orders = [o for o in orders if o.status.value == status_filter]

        if picked is not None:
            orders = [o for o in orders if o.picked == picked]

        if platform:
            platform_filter = platform.lower()
            orders = [o for o in orders if o.platform.value == platform_filter]

        return OrderList(orders=orders, page=page_num)

    @cached
    def get_order(self, order_id: str) -> Order:
        """Get a specific order by marketplace order ID."""
        activity_logger.info("Getting order %s", order_id)
        page = self.get_page()

        page.goto(f"{self.BASE_URL}/orders")
        page.wait_for_timeout(2000)

        # Search for the order. The orders page exposes a single Search Orders
        # input; plain CSS only — ``:visible`` is not a real CSS pseudo-class.
        search_box = page.locator('input[placeholder="Search Orders"]').first
        search_box.fill(order_id)
        search_box.press("Enter")
        page.wait_for_timeout(2000)

        order_data = page.evaluate("(targetOrderId) => {" + _JS_PARSE_ORDER_ROW + """
            const rows = document.querySelectorAll('table tbody tr');
            for (const row of rows) {
                const cells = row.querySelectorAll('td');
                if (cells.length < 7) continue;
                const data = parseOrderRow(cells);
                if (data.order_id === targetOrderId) return data;
            }
            return null;
        }""", order_id)

        if not order_data:
            raise ClientError(f"Order {order_id} not found")

        order_data["date_ordered"] = self._format_date(order_data.get("date_ordered", ""))
        _compute_order_flags(order_data)

        return create_order(order_data)

    @cached
    def list_processed_orders(self) -> ProcessedOrderList:
        """List processed orders ready for postage."""
        activity_logger.info("Listing processed orders")
        page = self.get_page()

        page.goto(f"{self.BASE_URL}/order-postage")
        page.wait_for_timeout(2000)

        orders_data = page.evaluate("() => {" + _JS_EXTRACT_TRACKING + """
            const orderList = [];
            const items = document.querySelectorAll('ul > li');

            items.forEach((item) => {
                const nameEl = item.querySelector('h3');
                if (!nameEl) return;
                const name = nameEl.textContent?.trim();

                const orderIdSpan = item.querySelector('span');
                const orderIdText = orderIdSpan?.textContent?.trim() || '';
                const orderIdMatch = orderIdText.match(/^(BO|BL)\\s+(\\d+)$/);
                const orderId = orderIdMatch ? orderIdMatch[2] : orderIdText;
                const marketplace = orderIdText.startsWith('BO') ? 'brickowl' : orderIdText.startsWith('BL') ? 'bricklink' : '';

                let lots = 0, itemCount = 0, total = '';
                const allDivs = item.querySelectorAll('div');
                for (const div of allDivs) {
                    const text = div.textContent?.trim();
                    const match = text?.match(/^(\\d+)\\s+lots?\\s+\\((\\d+)\\s+items?\\)\\s+([\\d.]+)\\s+USD$/i);
                    if (match) {
                        lots = parseInt(match[1], 10);
                        itemCount = parseInt(match[2], 10);
                        total = match[3];
                        break;
                    }
                }

                let weight = '';
                for (const div of allDivs) {
                    const text = div.textContent?.trim();
                    if (text && /^\\d+\\.?\\d*oz$/.test(text)) {
                        weight = text;
                        break;
                    }
                }

                const links = item.querySelectorAll('a');
                let email = '';
                for (const link of links) {
                    const text = link.textContent?.trim();
                    if (text && text.includes('@')) {
                        email = text;
                        break;
                    }
                }

                const addressInput = item.querySelector('textarea') || item.querySelector('input[type="text"]:not([disabled]):not([placeholder*="Tracking"])');
                const fullAddress = addressInput?.value?.trim() || '';
                const addressLines = fullAddress.split('\\n').map(l => l.trim()).filter(l => l);

                let address1 = '';
                let address2 = '';
                let city = '';
                let state = '';
                let zip = '';

                if (addressLines.length >= 4) {
                    const addrOnly = addressLines.slice(1);
                    const len = addrOnly.length;

                    if (len >= 3) {
                        zip = addrOnly[len - 1] || '';
                        state = addrOnly[len - 2] || '';
                        city = addrOnly[len - 3] || '';
                        address1 = addrOnly[0] || '';
                        if (len > 3) {
                            address2 = addrOnly.slice(1, len - 3).join(', ');
                        }
                    }
                }

                const address = addressLines.slice(1).join('\\n').trim();

                const phoneInput = item.querySelector('input[disabled]');
                const phone = phoneInput?.value?.trim() || '';

                const trackingId = extractTrackingId(item);

                let paymentMethod = '';
                let shippingMethod = '';
                for (const div of allDivs) {
                    const text = div.textContent?.trim();
                    if (!text) continue;
                    if (/PayPal/i.test(text) && !paymentMethod) paymentMethod = 'PayPal';
                    else if (/Stripe/i.test(text) && !paymentMethod) paymentMethod = 'Stripe';
                    if (/Delivery|USPS|Shipping/i.test(text)) shippingMethod = text;
                }

                if (name && orderId) {
                    orderList.push({
                        name,
                        orderId,
                        marketplace,
                        lots,
                        items: itemCount,
                        total,
                        email,
                        address,
                        address1,
                        address2,
                        city,
                        state,
                        zip,
                        phone,
                        weight,
                        trackingId,
                        paymentMethod,
                        shippingMethod
                    });
                }
            });

            return orderList;
        }""")

        orders = [create_processed_order(o) for o in orders_data]
        return ProcessedOrderList(orders=orders)

    @cached
    def get_brickfreedom_ids(self, order_ids: List[str]) -> Dict[str, str]:
        """Get BrickFreedom internal IDs for marketplace order IDs."""
        page = self.get_page()

        page.goto(f"{self.BASE_URL}/orders")
        page.wait_for_timeout(2000)

        id_map = {}

        # Extract from visible page first
        page_data = page.evaluate("() => {" + _JS_PARSE_ORDER_ROW + """
            const results = [];
            const rows = document.querySelectorAll('table tbody tr');
            rows.forEach((row) => {
                const cells = row.querySelectorAll('td');
                if (cells.length < 7) return;
                const data = parseOrderRow(cells);
                if (data.order_id && data.brickfreedom_id) {
                    results.push({ orderId: data.order_id, brickfreedomId: data.brickfreedom_id });
                }
            });
            return results;
        }""")

        for item in page_data:
            if item["orderId"] in order_ids:
                id_map[item["orderId"]] = item["brickfreedomId"]

        # Search for any not found
        for order_id in order_ids:
            if order_id not in id_map:
                search_box = page.locator('input[placeholder="Search Orders"]').first
                search_box.fill(order_id)
                search_box.press("Enter")
                page.wait_for_timeout(2000)

                search_result = page.evaluate("(targetOrderId) => {" + _JS_PARSE_ORDER_ROW + """
                    const rows = document.querySelectorAll('table tbody tr');
                    for (const row of rows) {
                        const cells = row.querySelectorAll('td');
                        if (cells.length < 7) continue;
                        const data = parseOrderRow(cells);
                        if (data.order_id === targetOrderId) return data.brickfreedom_id || null;
                    }
                    return null;
                }""", order_id)

                if search_result:
                    id_map[order_id] = search_result

                # Clear search
                search_box.fill("")
                search_box.press("Enter")
                page.wait_for_timeout(1000)

        return id_map

    def mark_orders_as_processed(self, order_ids: List[str]) -> ProcessResult:
        """Mark multiple orders as processed by marketplace order IDs."""
        activity_logger.info("Processing %s order(s)", len(order_ids))
        if not order_ids:
            return ProcessResult(success=True, processed=[], not_found=[], message="No orders to process")

        id_map = self.get_brickfreedom_ids(order_ids)

        not_found = [oid for oid in order_ids if oid not in id_map]
        if not_found:
            return ProcessResult(
                success=False,
                processed=[],
                not_found=not_found,
                message=f"Orders not found: {', '.join(not_found)}"
            )

        bf_ids = [id_map[oid] for oid in order_ids]
        url = f"{self.BASE_URL}/order-picker?brickfreedom_order_ids={','.join(bf_ids)}"
        self.get_page().goto(url)
        self.get_page().wait_for_timeout(2000)

        action_btn = self.get_page().get_by_role("button", name=re.compile(r"Mark.*as Processed", re.I))
        if action_btn.count() == 0:
            raise ClientError('"Mark as Processed" button not found on page')
        action_btn.click()
        self.get_page().wait_for_timeout(2000)

        processed = [{"orderId": oid, "brickfreedomId": id_map[oid]} for oid in order_ids]
        return ProcessResult(
            success=True,
            processed=processed,
            not_found=[],
            message=f"Processed {len(processed)} order(s)"
        )

    def post_orders(self, order_ids: List[str]) -> PostResult:
        """Post orders (mark as shipped). All must have tracking numbers."""
        activity_logger.info("Posting %s order(s)", len(order_ids))
        if not order_ids:
            return PostResult(success=True, posted=[], missing_tracking=[], not_found=[], message="No orders to post")

        id_map = self.get_brickfreedom_ids(order_ids)

        not_found = [oid for oid in order_ids if oid not in id_map]
        if not_found:
            return PostResult(
                success=False,
                posted=[],
                missing_tracking=[],
                not_found=not_found,
                message=f"Orders not found: {', '.join(not_found)}"
            )

        bf_ids = [id_map[oid] for oid in order_ids]
        url = f"{self.BASE_URL}/order-postage?brickfreedom_order_ids={','.join(bf_ids)}"
        self.get_page().goto(url)
        self.get_page().wait_for_timeout(2000)

        # Check for tracking numbers
        page_orders = self.get_page().evaluate("() => {" + _JS_EXTRACT_TRACKING + """
            const orderList = [];
            const items = document.querySelectorAll('ul > li');
            items.forEach((item) => {
                const orderIdSpan = item.querySelector('span');
                const orderIdText = orderIdSpan?.textContent?.trim() || '';
                const orderIdMatch = orderIdText.match(/^(BO|BL)\\s+(\\d+)$/);
                const orderId = orderIdMatch ? orderIdMatch[2] : '';
                if (!orderId) return;
                orderList.push({ orderId, trackingId: extractTrackingId(item) });
            });
            return orderList;
        }""")

        missing_tracking = []
        order_data = {}
        for order_id in order_ids:
            order = next((o for o in page_orders if o["orderId"] == order_id), None)
            if order and not order["trackingId"]:
                missing_tracking.append(order_id)
            elif order:
                order_data[order_id] = {"trackingId": order["trackingId"]}

        if missing_tracking:
            return PostResult(
                success=False,
                posted=[],
                missing_tracking=missing_tracking,
                not_found=[],
                message=f"Cannot post orders: {', '.join(missing_tracking)} missing tracking numbers"
            )

        action_btn = self.get_page().get_by_role("button", name=re.compile(r"Mark.*as Posted", re.I))
        if action_btn.count() == 0:
            raise ClientError('"Mark as Posted" button not found on page')
        action_btn.click()
        self.get_page().wait_for_timeout(2000)

        posted = [
            {"orderId": oid, "brickfreedomId": id_map[oid], **order_data.get(oid, {})}
            for oid in order_ids
        ]
        return PostResult(
            success=True,
            posted=posted,
            missing_tracking=[],
            not_found=[],
            message=f"Posted {len(posted)} order(s)"
        )

    def update_tracking(self, order_id: str, tracking_number: str) -> TrackingResult:
        """Update tracking number for an order on order-postage page."""
        activity_logger.info("Updating tracking for order %s", order_id)
        page = self.get_page()

        page.goto(f"{self.BASE_URL}/order-postage")
        page.wait_for_timeout(2000)

        # Find the order row
        order_row = page.get_by_role("listitem").filter(
            has_text=re.compile(rf"(BO|BL)\s+{order_id}\b")
        )

        if order_row.count() == 0:
            raise ClientError(f"Order {order_id} not found on postage page")

        tracking_input = order_row.get_by_placeholder("Add Tracking ID")
        if tracking_input.count() == 0:
            raise ClientError(f"Tracking input not found for order {order_id}")

        tracking_input.fill(tracking_number)
        page.wait_for_timeout(500)

        save_btn = order_row.get_by_role("button", name="Save")
        if save_btn.count() > 0:
            save_btn.click()
            page.wait_for_timeout(1000)
        else:
            tracking_input.press("Tab")
            page.wait_for_timeout(1000)

        return TrackingResult(
            success=True,
            order_id=order_id,
            tracking_number=tracking_number,
            message="Tracking updated successfully"
        )

    # ==================== Missing Parts Methods ====================

    @cached
    def list_missing_parts(self, include_completed: bool = False) -> MissingPartList:
        """List missing parts parsed from tasks."""
        activity_logger.info("Listing missing parts include_completed=%s", include_completed)
        task_list = self.list_tasks()

        parts = []
        for task in task_list.tasks:
            parsed = MissingPart.from_task_text(task.index, task.text, task.completed)
            if parsed:
                parts.append(parsed)

        if not include_completed:
            parts = [p for p in parts if not p.completed]

        return MissingPartList(parts=parts)

    def resolve_missing_parts(self, order_id: str) -> ResolveResult:
        """Mark all missing parts tasks for an order as completed."""
        activity_logger.info("Resolving missing parts for order %s", order_id)
        task_list = self.list_tasks()

        matching_tasks = []
        for task in task_list.tasks:
            parsed = MissingPart.from_task_text(task.index, task.text, task.completed)
            if parsed and parsed.order_id == order_id:
                matching_tasks.append({
                    "index": task.index,
                    "orderId": parsed.order_id,
                    "itemNumber": parsed.item_number,
                    "colorName": parsed.color_name,
                    "completed": task.completed
                })

        if not matching_tasks:
            return ResolveResult(
                success=False,
                message=f"No missing parts tasks found for order {order_id}",
                resolved=[]
            )

        to_resolve = [t for t in matching_tasks if not t["completed"]]

        if not to_resolve:
            return ResolveResult(
                success=True,
                message=f"All {len(matching_tasks)} missing parts tasks for order {order_id} are already completed",
                resolved=[]
            )

        # Sort by index descending to avoid index shifting
        to_resolve.sort(key=lambda t: t["index"], reverse=True)

        resolved = []
        for task in to_resolve:
            self.complete_task(task["index"])
            resolved.append({"itemNumber": task["itemNumber"], "colorName": task["colorName"]})

        return ResolveResult(
            success=True,
            message=f"Resolved {len(resolved)} missing parts task(s) for order {order_id}",
            resolved=resolved
        )


# ==================== Module-level Singleton ====================

_client: Optional[BrickfreedomClient] = None


def get_client() -> BrickfreedomClient:
    """Get or create the global Brickfreedom client instance."""
    global _client
    if _client is None:
        _client = BrickfreedomClient()
    return _client
