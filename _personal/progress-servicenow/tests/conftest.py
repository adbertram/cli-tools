"""Shared fixtures for progress-servicenow tests.

``LIVE_CATALOG_ITEM`` is a trimmed copy of a real
``GET /api/sn_sc/servicecatalog/items/838c9810dbe5db0408f33a1b7c961930``
response captured from progress1.service-now.com, so the parsing tests run
against the live payload shape rather than an invented one.
"""

import pytest

LIVE_CATALOG_ITEM = {
    "sys_id": "838c9810dbe5db0408f33a1b7c961930",
    "name": "Other Development Request",
    "short_description": "Requests for Other Development Resources",
    "category": {"title": "Development Support"},
    "variables": [
        {
            "name": "vs_product",
            "label": "Product",
            "friendly_type": "container_start",
            "mandatory": False,
            "children": [
                {
                    "name": "var_product",
                    "label": "Product",
                    "friendly_type": "select_box",
                    "mandatory": True,
                    "choices": [
                        {"label": "-- None --", "value": ""},
                        {"label": "Chef", "value": "Chef"},
                        {"label": "Sitefinity", "value": "Sitefinity"},
                        {"label": "OpenEdge", "value": "OpenEdge"},
                    ],
                }
            ],
        },
        {
            "name": "description__desc",
            "label": "Description",
            "friendly_type": "html",
            "mandatory": True,
        },
        {
            "name": "ReqImpact",
            "label": "What's the impact of the problem on your productivity?",
            "friendly_type": "select_box",
            "mandatory": True,
            "choices": [
                {"label": "Low", "value": "Low"},
                {"label": "Medium", "value": "Medium"},
                {"label": "High", "value": "High"},
            ],
        },
    ],
}

# Trimmed from a real accessibility snapshot of the Other Development Request
# catalog item form.
LIVE_FORM_SNAPSHOT = """- main [ref=e83]:
  - heading "Other Development Request" [ref=e84]:
  - form [ref=e130]:
    - generic [ref=e136]:
        - text [ref=e137]: Product
    - generic [ref=e139]:
      - combobox "Product" [ref=e140]:
    - generic [ref=e146]:
        - generic "Describe your request" [ref=e147]:
          - text [ref=e148]: Description
    - generic [ref=e151]:
      - application [ref=e152]:
    - generic [ref=e208]:
        - text [ref=e209]: What's the impact of the problem on your productivity?
    - generic [ref=e211]:
      - combobox "What's the impact of the problem on your productivity? Low" [ref=e212]:
  - button "Save as Draft" [ref=e224]:
  - button "Submit" [ref=e227]:
"""

DRAFT_MODAL_SNAPSHOT = """- generic [ref=e1]:
  - dialog "Catalog item save" [ref=e2]:
    - heading "Save draft" [ref=e11]:
    - textbox " Save draft as" [ref=e24]:
    - button "Cancel" [ref=e28]:
    - button "Save" [ref=e31]:
"""

DRAFT_SAVED_SNAPSHOT = """- main [ref=e83]:
  - text [ref=e94]: Your item has been saved in My Requests.
  - button "Update Draft" [ref=e214]:
"""

# Trimmed from a real accessibility snapshot captured while the saved session
# was expired: progress1.service-now.com 302s to the Progress Entra tenant and
# returns this sign-in page in place of ticket data.
SSO_LOGIN_SNAPSHOT = """- form [ref=e1]:
  - main [ref=e5]:
    - button "Back" [ref=e6]:
    - text [ref=e8]: bertram@progress.com
    - heading "Enter password" [ref=e11]:
      - text [ref=e12]: Enter password
    - textbox "Enter the password for bertram@progress.com" [ref=e15]:
    - link "Forgot my password" [ref=e18]:
    - button "Sign in" [ref=e22]:
"""

SSO_LOGIN_URL = (
    "https://login.microsoftonline.com/db266a67-cbe0-4d26-ae1a-d0581fe03535/saml2"
    "?SAMLRequest=jVLLbtswEPwVgXc9KEs0Q1gGXBtFDaSpELs59EaTK4cARapcymn%2FvgrtIumhCXrl"
    "&RelayState=https%3A%2F%2Fprogress1.service-now.com%2Fesc"
)

TICKET_URL = (
    "https://progress1.service-now.com/esc"
    "?id=ticket&table=sc_req_item&sys_id=d224f82b4780c7d04dd5454a516d432a"
)

UNAUTHORIZED_SNAPSHOT = """- main [ref=e83]:
  - heading "Development Cloud Issue" [ref=e84]:
  - text [ref=e92]: You are either not authorized or record is not valid.
"""


@pytest.fixture
def live_catalog_item():
    return LIVE_CATALOG_ITEM
