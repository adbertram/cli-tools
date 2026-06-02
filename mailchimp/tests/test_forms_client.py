import unittest

from mailchimp_cli.client import MailchimpClient


class RecordingMailchimpClient(MailchimpClient):
    def __init__(self, response):
        self.response = response
        self.calls = []

    def _make_request(self, method, endpoint, data=None, params=None):
        self.calls.append(
            {
                "method": method,
                "endpoint": endpoint,
                "data": data,
                "params": params,
            }
        )
        return self.response


class FormsClientTests(unittest.TestCase):
    def test_list_signup_forms_calls_mailchimp_signup_forms_endpoint(self):
        client = RecordingMailchimpClient(
            {
                "signup_forms": [
                    {
                        "list_id": "abc123",
                        "signup_form_url": "https://example.list-manage.com/subscribe?u=abc&id=def",
                    }
                ]
            }
        )

        result = client.list_signup_forms("abc123")

        self.assertEqual(
            client.calls,
            [
                {
                    "method": "GET",
                    "endpoint": "/lists/abc123/signup-forms",
                    "data": None,
                    "params": None,
                }
            ],
        )
        self.assertEqual(
            result,
            [
                {
                    "list_id": "abc123",
                    "signup_form_url": "https://example.list-manage.com/subscribe?u=abc&id=def",
                }
            ],
        )

    def test_customize_signup_form_posts_mailchimp_signup_form_payload(self):
        client = RecordingMailchimpClient(
            {
                "list_id": "abc123",
                "signup_form_url": "https://example.list-manage.com/subscribe?u=abc&id=def",
            }
        )

        result = client.customize_signup_form(
            list_id="abc123",
            header_text="Example beta",
            signup_message="Join the beta tester list.",
            signup_thank_you_title="You are on the list",
        )

        self.assertEqual(
            client.calls,
            [
                {
                    "method": "POST",
                    "endpoint": "/lists/abc123/signup-forms",
                    "data": {
                        "header": {"text": "Example beta"},
                        "contents": [
                            {
                                "section": "signup_message",
                                "value": "Join the beta tester list.",
                            },
                            {
                                "section": "signup_thank_you_title",
                                "value": "You are on the list",
                            },
                        ],
                    },
                    "params": None,
                }
            ],
        )
        self.assertEqual(
            result,
            {
                "list_id": "abc123",
                "signup_form_url": "https://example.list-manage.com/subscribe?u=abc&id=def",
            },
        )

    def test_get_signup_form_returns_default_form_when_exactly_one_exists(self):
        client = RecordingMailchimpClient(
            {
                "signup_forms": [
                    {
                        "list_id": "abc123",
                        "signup_form_url": "https://example.list-manage.com/subscribe?u=abc&id=def",
                    }
                ]
            }
        )

        result = client.get_signup_form("abc123")

        self.assertEqual(
            result,
            {
                "list_id": "abc123",
                "signup_form_url": "https://example.list-manage.com/subscribe?u=abc&id=def",
            },
        )

    def test_list_all_signup_forms_lists_audiences_then_each_signup_form(self):
        class MultiResponseClient(RecordingMailchimpClient):
            def __init__(self):
                self.calls = []
                self.responses = [
                    {"lists": [{"id": "abc123"}, {"id": "def456"}]},
                    {
                        "signup_forms": [
                            {
                                "list_id": "abc123",
                                "signup_form_url": "https://example.list-manage.com/subscribe?u=abc&id=def",
                            }
                        ]
                    },
                    {
                        "signup_forms": [
                            {
                                "list_id": "def456",
                                "signup_form_url": "https://second.example.list-manage.com/subscribe?u=abc&id=ghi",
                            }
                        ]
                    },
                ]

            def _make_request(self, method, endpoint, data=None, params=None):
                self.calls.append(
                    {
                        "method": method,
                        "endpoint": endpoint,
                        "data": data,
                        "params": params,
                    }
                )
                return self.responses.pop(0)

        client = MultiResponseClient()

        result = client.list_all_signup_forms(count=2)

        self.assertEqual(
            client.calls,
            [
                {
                    "method": "GET",
                    "endpoint": "/lists",
                    "data": None,
                    "params": {"count": 2, "offset": 0},
                },
                {
                    "method": "GET",
                    "endpoint": "/lists/abc123/signup-forms",
                    "data": None,
                    "params": None,
                },
                {
                    "method": "GET",
                    "endpoint": "/lists/def456/signup-forms",
                    "data": None,
                    "params": None,
                },
            ],
        )
        self.assertEqual(
            result,
            [
                {
                    "list_id": "abc123",
                    "signup_form_url": "https://example.list-manage.com/subscribe?u=abc&id=def",
                },
                {
                    "list_id": "def456",
                    "signup_form_url": "https://second.example.list-manage.com/subscribe?u=abc&id=ghi",
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()
