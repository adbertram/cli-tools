import unittest

from cli_tools_shared.exceptions import ClientError

from cvs_cli.client import CvsClient, EXPERIENCE_IDS
from cvs_cli.models import Prescription


def make_prescription(status: str, program_name: str = "RXC_READY_FILL") -> Prescription:
    return Prescription(
        id="12345",
        idType="RXC_RX_PRESCRIPTION_ID_TYPE",
        prescriptionLookupKey="lookup-key",
        drugInfo={
            "drug": {
                "name": "TEST DRUG",
            },
        },
        rxSubscriptions=[
            {
                "programName": program_name,
                "status": status,
            }
        ],
    )


class FakeCvsClient(CvsClient):
    def __init__(self, prescriptions):
        self.prescriptions = list(prescriptions)
        self.requests = []

    def get_prescription(self, rx_id: str) -> Prescription:
        return self.prescriptions.pop(0)

    def _make_request(self, experience_id, extra_data=None, extra_headers=None, refresh_on_unauthorized=True):
        self.requests.append(
            {
                "experience_id": experience_id,
                "extra_data": extra_data,
                "extra_headers": extra_headers,
                "refresh_on_unauthorized": refresh_on_unauthorized,
            }
        )
        return {
            "enrollPrescriptions": {
                "rxDetails": [
                    {
                        "program": {
                            "programName": "RXC_READY_FILL",
                        },
                        "readyFillstatus": "Success",
                    }
                ]
            }
        }


class AutoRefillTests(unittest.TestCase):
    def test_start_posts_enroll_payload_and_verifies(self):
        client = FakeCvsClient(
            [
                make_prescription("ELIGIBLE"),
                make_prescription("ENROLLED"),
            ]
        )

        result = client.set_auto_refill("12345", True)

        self.assertEqual(result["action"], "start")
        self.assertTrue(result["changed"])
        self.assertTrue(result["verified"])
        self.assertEqual(len(client.requests), 1)
        request = client.requests[0]
        self.assertEqual(request["experience_id"], EXPERIENCE_IDS["AUTO_REFILL"])
        self.assertEqual(request["extra_headers"], {"x-channel-type": "WEB"})
        rx_detail = request["extra_data"]["enrollRxRequest"]["rxDetails"][0]
        self.assertEqual(rx_detail["prescriptionLookupKey"], "lookup-key")
        self.assertEqual(rx_detail["autoRenewStatus"], "NOT_ELIGIBLE")
        self.assertEqual(
            rx_detail["program"],
            {
                "lob": "RETAIL",
                "programName": "RXC_READY_FILL",
                "status": "ENROLL",
            },
        )

    def test_stop_posts_unenroll_payload_and_verifies(self):
        client = FakeCvsClient(
            [
                make_prescription("ENROLLED"),
                make_prescription("ELIGIBLE"),
            ]
        )

        result = client.set_auto_refill("12345", False)

        self.assertEqual(result["action"], "stop")
        self.assertTrue(result["changed"])
        self.assertTrue(result["verified"])
        request = client.requests[0]
        rx_detail = request["extra_data"]["enrollRxRequest"]["rxDetails"][0]
        self.assertEqual(
            rx_detail["program"],
            {
                "lob": "RETAIL",
                "programName": "RXC_READY_FILL",
                "status": "UNENROLL",
            },
        )

    def test_already_in_requested_state_does_not_post(self):
        client = FakeCvsClient([make_prescription("ELIGIBLE")])

        result = client.set_auto_refill("12345", False)

        self.assertFalse(result["changed"])
        self.assertTrue(result["verified"])
        self.assertEqual(client.requests, [])

    def test_start_non_retail_requires_cvs_consent_flow(self):
        client = FakeCvsClient([make_prescription("ELIGIBLE", "PBM_READY_FILL")])

        with self.assertRaises(ClientError):
            client.set_auto_refill("12345", True)


if __name__ == "__main__":
    unittest.main()
