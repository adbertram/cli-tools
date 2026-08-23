"""CVS API client with browser-session JWT authentication."""
import base64
import json
import logging
import time
from typing import Any, Dict, List, Optional

import requests

from cli_tools_shared.http_session import BrowserAuthState, BrowserAuthStateError
from cli_tools_shared.exceptions import ClientError, CredentialError
from cli_tools_shared.output import print_warning

logger = logging.getLogger("cvs_cli.client")

from .browser import CvsBrowser
from .config import get_config
from .models import Order, Patient, Prescription
from .models.prescription import RefillEligibility


# Experience IDs for CVS mcapi endpoints
EXPERIENCE_IDS = {
    "AUTO_REFILL": "5eb2aee9-747e-4d59-883b-9622d58ca6a9",
    "PRESCRIPTIONS": "35d32039-61ac-47fc-9528-035f3dc5ef46",
    "ORDERS": "5f591215-cf0f-474f-8552-039f74515127",
    "PATIENTS": "5d92e709-1f65-4ec3-bd82-52eca8143556",
    "PROFILE": "bf8b3b37-9245-4258-9d04-2c5f61505b70",
}

API_ENDPOINT = "https://www.cvs.com/mcapi/client/experience/v2/load"
REQUEST_TIMEOUT = 30
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/146.0.0.0 Safari/537.36"
)


class CvsClient:
    """Client for interacting with CVS API via browser-session JWT."""

    def __init__(self, config=None):
        self.config = config or get_config()
        self._jwt: Optional[str] = None
        self._browser = None

    def _get_browser(self):
        if self._browser is None:
            self._browser = self.config.get_browser()
        return self._browser

    def _get_jwt(self) -> str:
        """Extract JWT from the shared BrowserAutomation auth state."""
        try:
            cookies = BrowserAuthState.from_config(self.config).cookies_for_host(
                "www.cvs.com",
                allowed_domains=("cvs.com",),
            )
        except BrowserAuthStateError as exc:
            raise CredentialError("No saved CVS browser session. Run 'cvs auth login' to authenticate.") from exc

        for cookie in cookies:
            if cookie.name == "access_token" and cookie.value:
                return cookie.value

        raise CredentialError(
            "No access_token cookie found. Run 'cvs auth login' to authenticate."
        )

    def _is_jwt_expired(self, jwt_str: str) -> bool:
        """Check if a JWT is expired by decoding its payload."""
        try:
            parts = jwt_str.split(".")
            if len(parts) < 2:
                return True
            payload = parts[1]
            # Add padding for base64
            padding = 4 - len(payload) % 4
            if padding != 4:
                payload += "=" * padding
            decoded = base64.urlsafe_b64decode(payload)
            claims = json.loads(decoded)
            exp = claims.get("exp")
            if exp is None:
                return False
            # Expired if less than 60 seconds remaining
            return time.time() > (exp - 60)
        except Exception:
            return True

    def _refresh_jwt(self) -> str:
        """Refresh the JWT by loading CVS through the shared browser session."""
        browser = self._get_browser()
        try:
            page = browser.get_page("https://www.cvs.com/")
            page.wait_for_timeout(3000)
        finally:
            browser.close()
            self._browser = None
        return self._get_jwt()

    def _ensure_valid_jwt(self) -> str:
        """Ensure we have a valid (non-expired) JWT."""
        if self._jwt and not self._is_jwt_expired(self._jwt):
            return self._jwt

        try:
            self._jwt = self._get_jwt()
        except ClientError:
            self._jwt = self._refresh_jwt()
        else:
            if self._is_jwt_expired(self._jwt):
                self._jwt = self._refresh_jwt()

        if self._is_jwt_expired(self._jwt):
            raise CredentialError("Session expired. Run 'cvs auth login' to re-authenticate.")
        return self._jwt

    def _make_request(
        self,
        experience_id: str,
        extra_data: Optional[Dict[str, Any]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        refresh_on_unauthorized: bool = True,
    ) -> Dict[str, Any]:
        """Make a POST request to the CVS experience API.

        Args:
            experience_id: The experience UUID to load.
            extra_data: Additional data fields to merge into the request body.

        Returns:
            Parsed response data dict.

        Raises:
            ClientError: On authentication or API errors.
        """
        jwt = self._ensure_valid_jwt()
        url = f"{API_ENDPOINT}/{experience_id}"

        body_data: Dict[str, Any] = {"channel": "WEB"}
        if extra_data:
            body_data.update(extra_data)

        headers = {
            "Content-Type": "text/plain;charset=UTF-8",
            "Accept": "application/json",
            "Origin": "https://www.cvs.com",
            "Referer": "https://www.cvs.com/pharmacy/rx/prescriptions",
            "User-Agent": USER_AGENT,
            "x-api-key": self.config.api_key,
            "x-client-fingerprint-id": self.config.fingerprint,
            "x-experienceid": experience_id,
        }
        if extra_headers:
            headers.update(extra_headers)
        cookies = f"access_token={jwt}; token_type=Bearer"
        headers["Cookie"] = cookies

        response = requests.post(
            url,
            headers=headers,
            data=json.dumps({"data": body_data}),
            timeout=REQUEST_TIMEOUT,
        )

        # On 401, refresh JWT and retry once
        if response.status_code == 401 and refresh_on_unauthorized:
            self._jwt = self._refresh_jwt()
            jwt = self._jwt
            headers["Cookie"] = f"access_token={jwt}; token_type=Bearer"
            response = requests.post(
                url,
                headers=headers,
                data=json.dumps({"data": body_data}),
                timeout=REQUEST_TIMEOUT,
            )

        if not response.ok:
            if response.status_code in (401, 403):
                raise CredentialError(
                    f"CVS session is not authorized (HTTP {response.status_code}). "
                    "Run 'cvs auth login' to re-authenticate."
                )
            raise ClientError(
                f"CVS API error: HTTP {response.status_code} - {response.text[:500]}"
            )

        try:
            result = response.json()
        except ValueError as exc:
            raise ClientError(
                "CVS returned an unexpected non-JSON response. If this persists, "
                "run 'cvs auth login' to re-authenticate."
            ) from exc
        if not isinstance(result, dict):
            raise ClientError(
                "CVS returned an unexpected response shape (expected an object)."
            )

        # CVS API uses statusCode "0000" for success
        status_code = result.get("statusCode")
        if status_code and status_code != "0000":
            status_msg = result.get("statusMessage", "Unknown error")
            raise ClientError(f"CVS API error {status_code}: {status_msg}")

        return result.get("data", result)

    def _get_drug_name(self, rx: Prescription) -> Optional[str]:
        if rx.drugInfo and rx.drugInfo.drug:
            return rx.drugInfo.drug.name
        return None

    def _get_ready_fill_subscription(self, rx: Prescription) -> Optional[Dict[str, Any]]:
        for subscription in rx.rxSubscriptions or []:
            if subscription.get("programName") in ("RXC_READY_FILL", "PBM_READY_FILL"):
                return subscription
        return None

    def _ready_fill_status(self, rx: Prescription) -> Optional[str]:
        subscription = self._get_ready_fill_subscription(rx)
        if not subscription:
            return None
        status = subscription.get("status")
        if status is None:
            return None
        return str(status).upper()

    def _ready_fill_lob(self, rx: Prescription, program_name: str) -> str:
        if program_name == "RXC_READY_FILL" or (rx.idType and "RXC" in rx.idType):
            return "RETAIL"
        if program_name == "PBM_READY_FILL" or (rx.idType and "PBM" in rx.idType):
            return "PBM"
        raise ClientError(
            f"Prescription '{rx.id}' has unsupported auto-refill program '{program_name}'."
        )

    # ==================== Prescriptions ====================

    def list_prescriptions(self) -> List[Prescription]:
        """List all prescriptions across all linked patients.

        Returns:
            Flattened list of Prescription models.
        """
        data = self._make_request(EXPERIENCE_IDS["PRESCRIPTIONS"])
        prescriptions: List[Prescription] = []
        skipped = 0

        patients = data.get("getLinkedMemberPatients", [])
        for patient in patients:
            patient_first = patient.get("firstName", "")
            patient_last = patient.get("lastName", "")
            linked_ids = patient.get("linkedIDs", [])
            for linked in linked_ids:
                rxs = linked.get("prescriptionforPatient", [])
                for rx_data in rxs:
                    rx_data["patientFirstName"] = patient_first
                    rx_data["patientLastName"] = patient_last
                    # One malformed record must not abort the whole list — skip
                    # it (visibly) and keep the rest. Read-only ops should still
                    # return everything they can.
                    try:
                        prescriptions.append(Prescription(**rx_data))
                    except Exception as exc:
                        skipped += 1
                        logger.debug("Skipping malformed prescription record: %s", exc)

        if skipped:
            print_warning(
                f"Skipped {skipped} malformed prescription record(s) in the CVS response."
            )
        return prescriptions

    def get_prescription(self, rx_id: str) -> Prescription:
        """Get a specific prescription by ID.

        Args:
            rx_id: The prescription ID.

        Returns:
            Matching Prescription model.

        Raises:
            ClientError: If prescription not found.
        """
        prescriptions = self.list_prescriptions()
        for rx in prescriptions:
            if rx.id == rx_id:
                return rx
        raise ClientError(f"Prescription '{rx_id}' not found.")

    def set_auto_refill(self, rx_id: str, enabled: bool) -> Dict[str, Any]:
        """Start or stop CVS ReadyFill auto-refill for a prescription."""
        before = self.get_prescription(rx_id)
        subscription = self._get_ready_fill_subscription(before)
        if not subscription:
            raise ClientError(f"Prescription '{rx_id}' is not eligible for CVS auto-refill.")

        program_name = str(subscription.get("programName") or "")
        if enabled and program_name != "RXC_READY_FILL":
            raise ClientError(
                "Starting auto-refill for this prescription requires the CVS consent flow. "
                "Use the CVS site for this prescription."
            )

        status_before = self._ready_fill_status(before)
        before_enabled = status_before == "ENROLLED"
        action = "start" if enabled else "stop"
        if before_enabled == enabled:
            return {
                "id": before.id,
                "drugName": self._get_drug_name(before),
                "action": action,
                "programName": program_name,
                "statusBefore": status_before,
                "statusAfter": status_before,
                "changed": False,
                "verified": True,
            }

        auto_renew_status = "NOT_ELIGIBLE"
        if before.autoRenewStatus == "ELIGIBLE" and enabled:
            auto_renew_status = "ENROLL"
        elif not enabled and program_name == "PBM_READY_FILL":
            auto_renew_status = "UNENROLL"

        payload = {
            "enrollRxRequest": {
                "rxDetails": [
                    {
                        "autoRenewStatus": auto_renew_status,
                        "prescriptionLookupKey": before.prescriptionLookupKey,
                        "program": {
                            "lob": self._ready_fill_lob(before, program_name),
                            "programName": program_name,
                            "status": "ENROLL" if enabled else "UNENROLL",
                        },
                    }
                ]
            },
            "profile": {
                "id": "$id",
                "idType": "$idType",
            },
            "patient": {
                "id": "$id",
                "idType": "$idType",
            },
        }

        response = self._make_request(
            EXPERIENCE_IDS["AUTO_REFILL"],
            payload,
            extra_headers={"x-channel-type": "WEB"},
        )

        rx_details = response.get("enrollPrescriptions", {}).get("rxDetails", [])
        if not rx_details:
            rx_details = response.get("enrollPrescriptionsWithLookupKey", {}).get(
                "rxDetails",
                [],
            )
        rx_detail = rx_details[0] if rx_details else {}
        ready_fill_status = rx_detail.get("readyFillstatus")
        if (
            program_name == "RXC_READY_FILL"
            and ready_fill_status
            and ready_fill_status != "Success"
        ):
            raise ClientError(f"CVS auto-refill update failed: {ready_fill_status}")

        after = self.get_prescription(rx_id)
        status_after = self._ready_fill_status(after)
        after_enabled = status_after == "ENROLLED"
        if after_enabled != enabled:
            raise ClientError(
                f"CVS accepted the auto-refill update, but verification still shows "
                f"status '{status_after}'."
            )

        return {
            "id": after.id,
            "drugName": self._get_drug_name(after),
            "action": action,
            "programName": program_name,
            "statusBefore": status_before,
            "statusAfter": status_after,
            "changed": True,
            "verified": True,
        }

    # ==================== Orders ====================

    def list_orders(self) -> List[Order]:
        """List order history.

        Returns:
            List of Order models.
        """
        data = self._make_request(EXPERIENCE_IDS["ORDERS"])
        orders: List[Order] = []
        skipped = 0
        for o in data.get("retailOrderHistory", []):
            # Skip a malformed record rather than losing the whole order list.
            try:
                orders.append(Order(**o))
            except Exception as exc:
                skipped += 1
                logger.debug("Skipping malformed order record: %s", exc)
        if skipped:
            print_warning(
                f"Skipped {skipped} malformed order record(s) in the CVS response."
            )
        return orders

    def get_order(self, order_id: str) -> Order:
        """Get a specific order by ID.

        Args:
            order_id: The order ID.

        Returns:
            Matching Order model.

        Raises:
            ClientError: If order not found.
        """
        orders = self.list_orders()
        for order in orders:
            if order.orderId == order_id:
                return order
        raise ClientError(f"Order '{order_id}' not found.")

    # ==================== Refills ====================

    def check_refills(self) -> List[RefillEligibility]:
        """Check which prescriptions are eligible for refill or renewal.

        Returns:
            List of RefillEligibility models for eligible prescriptions.
        """
        prescriptions = self.list_prescriptions()
        eligible: List[RefillEligibility] = []

        for rx in prescriptions:
            if rx.isRefillable or rx.isRenewEligible:
                drug_name = None
                if rx.drugInfo and rx.drugInfo.drug:
                    drug_name = rx.drugInfo.drug.name
                eligible.append(
                    RefillEligibility(
                        id=rx.id,
                        drugName=drug_name,
                        isRefillable=rx.isRefillable,
                        isRenewEligible=rx.isRenewEligible,
                        numberOfRefillsRemaining=rx.numberOfRefillsRemaining,
                        nextFillDate=rx.nextFillDate,
                        expirationDate=rx.expirationDate,
                        lastRefillDate=rx.lastRefillDate,
                        patientFirstName=rx.patientFirstName,
                    )
                )

        return eligible


# Module-level client instance - singleton pattern
_client: Optional[CvsClient] = None


def get_client(config=None) -> CvsClient:
    """Get or create the global CVS client instance."""
    global _client
    if config is not None:
        return CvsClient(config=config)
    if _client is None:
        _client = CvsClient()
    return _client
