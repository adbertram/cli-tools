"""Browser-automation instructions for Impact marketplace operations.

Impact.com's Publisher API has no marketplace/discovery endpoint
(see <https://integrations.impact.com/impact-publisher>) — every documented
``/Mediapartners/{AccountSID}/...`` endpoint is post-approval/operational.
Marketplace browsing and program application are therefore UI-only flows in
the Impact partner portal.

The ``impact marketplace ...`` commands return structured JSON that another
agent (using the ``playwright-cli`` skill) can follow to drive the partner
portal browser UI.
"""
from typing import Any, Dict, List, Literal, Optional

from pydantic import ConfigDict, Field

from cli_tools_shared.models import CLIModel
from cli_tools_shared.repo_paths import secret_manager_script


PORTAL_LOGIN_URL = "https://app.impact.com/login.user"
# Brand Marketplace landing page in the publisher portal. Impact migrated the
# legacy ``/secure/marketplace/brand-listings.ihtml`` path; that URL now returns
# 404 for authenticated publishers. The current canonical URL was verified
# 2026-05-13 against a live publisher session and matches the deep link
# documented in the impact.com Help Center.
PORTAL_MARKETPLACE_URL = (
    "https://app.impact.com/secure/mediapartner/marketplace/"
    "new-campaign-marketplace-flow.ihtml"
)
# Fragment-based query format used by the marketplace SPA. ``joinState`` is one
# of ``all`` (All Brands tab) or ``pre-approved`` (Pre-approved tab); ``q`` is
# the AI-powered search box value.
PORTAL_MARKETPLACE_SEARCH_URL_TEMPLATE = (
    PORTAL_MARKETPLACE_URL + "#joinState=all&q={keyword}"
)
SECRET_MANAGER_SCRIPT = str(secret_manager_script())

DEFAULT_DISCLAIMER = (
    "no public Impact Publisher API endpoint exists for marketplace discovery; "
    "this command returns instructions for browser automation via playwright-cli."
)

AUTH_NOTE = (
    "Credentials live in the CLI-tools secret manager: "
    f"`{SECRET_MANAGER_SCRIPT} get impact-username` and "
    f"`{SECRET_MANAGER_SCRIPT} get impact-password`. (LastPass does NOT "
    "have an `app.impact.com` entry — do not waste a call on `lastpass items "
    "list` for impact.) An authenticated persistent profile already exists at "
    "`.playwright-cli/profiles/impact`; reuse it via "
    "`playwright-cli -s=impact open --profile .playwright-cli/profiles/impact "
    "--headed <url>`. Only fall back to the login form if the session is not "
    "authenticated. When typing credentials into shell, use a unique variable "
    "name (e.g. `IMPACT_USER`, `IMPACT_PW`) — `$USERNAME` is shadowed by a "
                "system env var and silently truncates account names."
)


class BrowserStep(CLIModel):
    """A single ordered playwright-cli action."""

    action: str
    description: str
    arguments: Optional[Dict[str, Any]] = None


class MarketplaceInstruction(CLIModel):
    """Structured instructions for an AI agent to execute an Impact marketplace flow.

    The schema is deliberately top-level-flat so an agent can read every required
    field directly from the JSON root.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, populate_by_name=True)

    type: Literal["browser_navigation_instruction"] = "browser_navigation_instruction"
    schema_version: Literal["1.0"] = "1.0"
    tool: Literal["impact"] = "impact"
    command: str
    action_id: str
    objective: str
    disclaimer: str = Field(default=DEFAULT_DISCLAIMER)
    target_url: str
    auth_note: str = Field(default=AUTH_NOTE)
    structured_context: Dict[str, Any]
    steps: List[BrowserStep]
    extraction_target: Dict[str, Any]
    allowed_tools: List[str] = Field(default_factory=lambda: ["playwright-cli", "lastpass"])
    constraints: List[str]
    success_criteria: List[str]
    next_actions: List[str]


def _common_login_steps() -> List[BrowserStep]:
    """The steps every marketplace flow needs before navigating to the target page."""
    return [
        BrowserStep(
            action="ensure_authenticated_session",
            description=(
                "Reuse the persistent playwright-cli session named `impact` if "
                "one is open (`playwright-cli list` will show it). Otherwise "
                "launch it against the persisted profile: "
                "`playwright-cli -s=impact open --profile "
                "`.playwright-cli/profiles/impact` --headed <target_url>`. If "
                "the page renders the login form, fill it: read the username "
                f"from `{SECRET_MANAGER_SCRIPT} get impact-username` and "
                f"the password from `{SECRET_MANAGER_SCRIPT} get "
                "impact-password`, bind them to non-conflicting shell vars "
                "(e.g. IMPACT_USER / IMPACT_PW — never $USERNAME), fill the "
                "Username/Email and Password textboxes, then click 'Sign In'. "
                "Do not query lastpass — there is no `app.impact.com` entry."
            ),
            arguments={
                "login_url": PORTAL_LOGIN_URL,
                "session_name": "impact",
                "profile_path": ".playwright-cli/profiles/impact",
                "credentials_source": "cli-tools-secret-manager",
                "username_secret": "impact-username",
                "password_secret": "impact-password",
            },
        ),
    ]


def build_search_instruction(
    keyword: Optional[str],
    category: Optional[str],
) -> MarketplaceInstruction:
    """Instruction object for `impact marketplace search`."""
    if keyword:
        target_url = PORTAL_MARKETPLACE_SEARCH_URL_TEMPLATE.format(keyword=keyword)
    else:
        target_url = PORTAL_MARKETPLACE_URL
    steps: List[BrowserStep] = _common_login_steps()
    steps.append(
        BrowserStep(
            action="navigate",
            description=(
                "Open the Brand Marketplace SPA. If the agent is not yet "
                "authenticated, Impact will redirect to the login page; the "
                "marketplace URL is the post-login landing for publisher "
                "accounts and will load directly once auth is established. "
                "WARNING: the SPA's default landing tab is 'Home' (curated "
                "subset, NOT the full catalog). On initial render the URL "
                "fragment `q=<keyword>` is applied against the 'Home' tab — "
                "which has ~0 entries for most niche keywords, producing a "
                "false-negative '0 rows'. Always switch tabs and re-enter the "
                "keyword in steps 4–5 below, regardless of the URL fragment."
            ),
            arguments={"url": target_url},
        )
    )
    steps.append(
        BrowserStep(
            action="page_snapshot",
            description=(
                "Capture a full DOM snapshot of the marketplace page so the "
                "agent can locate the 'All Brands' tab button, the search "
                "input, the 'Categories' filter dropdown, and the brand result "
                "grid before interacting. The result grid is composed of one "
                "``.brands-card`` element per brand. Total result count is "
                "rendered as text matching `/^\\|?\\s*[\\d,]+ rows$/` (e.g. "
                "'|8,767 rows' on All Brands with no filter) inside an "
                "indicator above the grid — use this to verify the page has "
                "settled before harvesting."
            ),
        )
    )
    steps.append(
        BrowserStep(
            action="select_tab",
            description=(
                "Click the 'All Brands' tab button. The default 'Home' tab is "
                "a curated highlights subset and is NOT a comprehensive "
                "listing — most keywords return 0 rows there even when "
                "matches exist on 'All Brands'. Use 'Pre-approved' only if "
                "you explicitly want pre-approved brands. CRITICAL SIDE "
                "EFFECT: clicking 'All Brands' rewrites the URL to drop the "
                "`q=<keyword>` fragment, so the search box is cleared. The "
                "fill_search step below is mandatory whenever a keyword is "
                "specified — do NOT rely on the URL fragment alone."
            ),
            arguments={"tab": "All Brands"},
        )
    )
    if keyword is not None:
        steps.append(
            BrowserStep(
                action="fill_search",
                description=(
                    "Locate the textbox with placeholder 'Search for a brand "
                    "or enter a prompt', fill it with the supplied keyword, "
                    "then press Enter (a separate `press Enter` action — fill "
                    "alone does not submit). After Enter, wait ~3-5s for the "
                    "result count above the grid to update from the previous "
                    "value before re-snapshotting. The search is AI-powered "
                    "(branded 'Powered by impact AI'), so natural-language "
                    "queries are valid (e.g. 'brands new to impact.com'). "
                    "OBSERVATION (verified 2026-05-13): the catalog is "
                    "heavily consumer/retail; B2B IT-tool keywords return "
                    "very few hits. Empirical counts on 'All Brands' "
                    "(8,767 total): PowerShell=0, scripting=0, sysadmin=0, "
                    "DevOps=0, automation=2, windows=6, developer=34. For "
                    "developer-tool discovery prefer 'developer' or vertical "
                    "names; for IT/automation prefer 'automation' or "
                    "'windows'."
                ),
                arguments={
                    "keyword": keyword,
                    "selector": "input[placeholder='Search for a brand or enter a prompt']",
                    "submit": "press Enter after fill",
                },
            )
        )
    if category is not None:
        steps.append(
            BrowserStep(
                action="apply_category_filter",
                description=(
                    "Click the 'Categories' filter chip to open its dropdown, "
                    "then click the entry matching the supplied category "
                    "label. Wait for the result count above the grid (e.g. "
                    "'8,765 rows') to update before snapshotting."
                ),
                arguments={"category": category},
            )
        )
    steps.append(
        BrowserStep(
            action="page_snapshot",
            description=(
                "Re-snapshot the page after filters are applied so the result "
                "list can be harvested. BEFORE harvesting, locate the row "
                "count indicator (text `/^\\|?\\s*([\\d,]+) rows$/`). If it "
                "reads `0 rows`, return an empty list immediately — do not "
                "scroll or wait further. If it reads a non-zero count, that "
                "count is the upper bound on `.brands-card` elements to "
                "extract."
            ),
        )
    )
    steps.append(
        BrowserStep(
            action="harvest_results",
            description=(
                "From the post-filter snapshot, extract one record per "
                "``.brands-card`` element matching the fields in "
                "``extraction_target.fields``. The brand's campaign ID is "
                "embedded in the card's logo URL (regex "
                "``display-logo-via-campaign/(\\d+)\\.gif`` against the "
                "background-image style of ``.brands-card .image``). The "
                "marketplace SPA virtualises the grid, so the agent must "
                "scroll the grid container to load additional rows until "
                "either no new rows appear, the row-count indicator is "
                "reached, or the caller-imposed limit is hit."
            ),
        )
    )

    return MarketplaceInstruction(
        command="marketplace search",
        action_id="impact_marketplace_search",
        objective=(
            "Discover Impact-marketplace brand programs the partner has not yet "
            "joined, optionally filtered by keyword and/or category, and return "
            "a structured list of matching programs."
        ),
        target_url=target_url,
        structured_context={
            "keyword": keyword,
            "category": category,
            "portal_login_url": PORTAL_LOGIN_URL,
            "portal_marketplace_url": PORTAL_MARKETPLACE_URL,
            "search_url_template": PORTAL_MARKETPLACE_SEARCH_URL_TEMPLATE,
            "brand_card_selector": ".brands-card",
            "search_input_selector": "input[placeholder='Search for a brand or enter a prompt']",
            "category_filter_label": "Categories",
            "campaign_id_regex": r"display-logo-via-campaign/(\d+)\.gif",
            "row_count_regex": r"^\|?\s*([\d,]+) rows$",
            "tabs": {
                "default": "Home",
                "comprehensive": "All Brands",
                "pre_approved": "Pre-approved",
                "side_effect_on_tab_switch": "Clicking 'All Brands' rewrites the URL fragment and drops q=<keyword>; the search box must be re-filled.",
            },
            "credential_source": {
                "primary": f"{SECRET_MANAGER_SCRIPT} get impact-username|impact-password",
                "session_profile": ".playwright-cli/profiles/impact",
                "lastpass": "no app.impact.com entry — do not query lastpass for impact creds",
            },
            "empirical_keyword_counts_2026_05_13": {
                "PowerShell": 0,
                "scripting": 0,
                "sysadmin": 0,
                "DevOps": 0,
                "automation": 2,
                "windows": 6,
                "developer": 34,
                "total_all_brands": 8767,
                "note": "Catalog skews consumer/retail; B2B IT keywords return few or zero hits.",
            },
        },
        steps=steps,
        extraction_target={
            "container_selector_hint": (
                "``.brands-card`` element inside the marketplace results grid"
            ),
            "fields": [
                {"name": "program_name", "description": "Brand or program display name (first text node inside the card)"},
                {"name": "advertiser", "description": "Brand / advertiser name if shown separately from program name"},
                {"name": "category", "description": "Comma-separated category labels shown on the card"},
                {"name": "terms_summary", "description": "Commission rate / payout summary text shown on the card (e.g. 'Shoebacca 5%')"},
                {"name": "program_id", "description": "Impact campaign ID parsed from the card's logo URL via regex ``display-logo-via-campaign/(\\d+)\\.gif``"},
                {"name": "join_state", "description": "One of 'eligible-to-apply', 'pre-approved', 'applied', 'joined' — read from any badge on the card"},
            ],
        },
        constraints=[
            "Do not attempt to call any Impact REST API for program discovery — no such endpoint exists in the Impact Publisher API.",
            f"Reuse the persistent `impact` playwright session and profile at `.playwright-cli/profiles/impact` when available. Read credentials only from `{SECRET_MANAGER_SCRIPT}` (`impact-username` / `impact-password`); LastPass has no `app.impact.com` entry.",
            "Do not click 'Apply' from the search flow; use the dedicated `marketplace apply` instruction for application submission.",
            "Default landing tab is 'Home' (curated, limited). Click 'All Brands' before harvesting for a complete listing — even if the URL fragment already has `joinState=all`, the SPA still renders 'Home' initially.",
            "After clicking the 'All Brands' tab the URL fragment is rewritten and the `q=<keyword>` portion is lost; always re-fill the search input when a keyword is specified.",
            "Fill alone does not submit the search — explicitly press Enter after filling the search input.",
            "Trust the row-count indicator above the grid before scrolling. `0 rows` is authoritative; do not retry the same keyword expecting different results.",
            "When binding values from shell, do NOT use `$USERNAME` — it is shadowed by a macOS system env var and truncates the value. Use `IMPACT_USER` / `IMPACT_PW` or similar.",
            "Do NOT use the legacy ``/secure/marketplace/brand-listings.ihtml`` URL — that path now returns 404 for publishers.",
        ],
        success_criteria=[
            "A JSON list of matching programs is returned, each containing the fields requested in `extraction_target.fields`.",
            "If no matches are found, an empty list (not an error) is returned.",
            "Pagination either completed or was bounded by the caller's limit.",
        ],
        next_actions=[
            "impact marketplace apply <program-id>  # to submit an application against one of the discovered programs",
            "impact marketplace list-categories  # to enumerate the category filter values currently surfaced by the UI",
        ],
    )


def build_apply_instruction(program_id: str) -> MarketplaceInstruction:
    """Instruction object for `impact marketplace apply <program-id>`."""
    # The marketplace SPA does NOT expose a per-program deep link by campaign
    # id. The agent must navigate to the marketplace landing page, locate the
    # ``.brands-card`` whose logo URL contains the matching campaign id, and
    # interact with the inline Apply button (which opens a side-panel form).
    target_url = PORTAL_MARKETPLACE_URL
    steps: List[BrowserStep] = _common_login_steps()
    steps.append(
        BrowserStep(
            action="navigate",
            description=(
                "Open the Brand Marketplace landing page. The marketplace SPA "
                "does not support direct deep links to a specific program; "
                "the program card must be located inside the grid."
            ),
            arguments={"url": target_url, "program_id": program_id},
        )
    )
    steps.append(
        BrowserStep(
            action="select_tab",
            description=(
                "Click the 'All Brands' tab so the full brand grid is "
                "filterable — the default 'Home' tab is a curated subset and "
                "will not contain most campaign ids."
            ),
            arguments={"tab": "All Brands"},
        )
    )
    steps.append(
        BrowserStep(
            action="locate_program_card",
            description=(
                "Find the ``.brands-card`` whose logo URL matches the "
                "supplied program (campaign) id using the regex "
                "``display-logo-via-campaign/<program_id>\\.gif`` against "
                "the background-image style on the card's ``.image`` "
                "element. The marketplace grid virtualises rows — scroll the "
                "grid container until the card is mounted, or type the "
                "brand's known name into the search input to narrow the grid "
                "first."
            ),
            arguments={"program_id": program_id},
        )
    )
    steps.append(
        BrowserStep(
            action="click_apply",
            description=(
                "Click the 'Apply' button inside the located card. This "
                "opens an inline side-panel / drawer with the application "
                "form. There is no separate apply URL."
            ),
        )
    )
    steps.append(
        BrowserStep(
            action="page_snapshot",
            description=(
                "Capture a snapshot of the application form drawer. The form "
                "fields vary by advertiser; the agent must read the live "
                "form to learn which fields are required before filling them."
            ),
        )
    )
    steps.append(
        BrowserStep(
            action="fill_application_form",
            description=(
                "Fill every required field on the apply form using the "
                "partner's stored profile data (Impact partner-portal "
                "account info). Use the agent's own judgment to map profile "
                "fields to the form's required inputs based on labels "
                "visible in the snapshot."
            ),
        )
    )
    steps.append(
        BrowserStep(
            action="submit_application",
            description=(
                "Click the form's primary submit / 'Submit Application' "
                "button at the bottom of the drawer."
            ),
        )
    )
    steps.append(
        BrowserStep(
            action="capture_confirmation",
            description=(
                "After submission, snapshot the page again and capture any "
                "confirmation text, status banner, or new URL that indicates "
                "the application was accepted or pending. Save the "
                "confirmation to the agent's working notes."
            ),
        )
    )

    return MarketplaceInstruction(
        command=f"marketplace apply {program_id}",
        action_id="impact_marketplace_apply",
        objective=(
            "Submit an application to join the specified Impact program, "
            "filling the live application form and capturing any confirmation."
        ),
        target_url=target_url,
        structured_context={
            "program_id": program_id,
            "portal_login_url": PORTAL_LOGIN_URL,
            "portal_marketplace_url": PORTAL_MARKETPLACE_URL,
            "brand_card_selector": ".brands-card",
            "apply_button_selector": ".brands-card button:has-text('Apply')",
            "campaign_id_regex": r"display-logo-via-campaign/(\d+)\.gif",
        },
        steps=steps,
        extraction_target={
            "container_selector_hint": (
                "post-submit confirmation banner or status panel inside the "
                "application drawer"
            ),
            "fields": [
                {"name": "submission_status", "description": "Status word (e.g. submitted, pending, approved, rejected)"},
                {"name": "confirmation_text", "description": "Verbatim confirmation copy from the success banner"},
                {"name": "next_step_url", "description": "URL the portal redirected to after submission, if any"},
            ],
        },
        constraints=[
            "Do not call the Impact REST API for application submission — no such endpoint exists.",
            "Do not invent answers for required fields. If a required field has no obvious value, stop and surface the form to the user before submitting.",
            "Confirm the program identifier matches what the form shows before clicking Submit.",
            "Do NOT navigate to a per-program URL — the marketplace SPA has no deep link by campaign id. The apply flow is inline within the marketplace page.",
        ],
        success_criteria=[
            "A confirmation banner / message is captured verbatim.",
            "submission_status is non-empty and reflects the live page state.",
        ],
        next_actions=[
            "impact campaigns list  # after approval, the program will surface here as a joined campaign",
            "impact marketplace search  # to keep discovering more programs",
        ],
    )


def build_list_categories_instruction() -> MarketplaceInstruction:
    """Instruction object for `impact marketplace list-categories`."""
    steps: List[BrowserStep] = _common_login_steps()
    steps.append(
        BrowserStep(
            action="navigate",
            description=(
                "Open the Brand Marketplace landing page. Default tab is "
                "'Home'; switch to 'All Brands' before opening the category "
                "filter so the full set of categories is enumerated."
            ),
            arguments={"url": PORTAL_MARKETPLACE_URL},
        )
    )
    steps.append(
        BrowserStep(
            action="select_tab",
            description="Click the 'All Brands' tab so the full filter set is exposed.",
            arguments={"tab": "All Brands"},
        )
    )
    steps.append(
        BrowserStep(
            action="open_category_filter",
            description=(
                "Click the 'Categories' filter chip / dropdown trigger above "
                "the result grid. The dropdown contains an input with "
                "placeholder 'Categories' followed by a vertical list of "
                "every category label."
            ),
            arguments={"trigger_text": "Categories"},
        )
    )
    steps.append(
        BrowserStep(
            action="page_snapshot",
            description=(
                "Capture a snapshot showing the expanded category dropdown "
                "so every label is visible."
            ),
        )
    )
    steps.append(
        BrowserStep(
            action="harvest_categories",
            description=(
                "Read every category label inside the expanded dropdown and "
                "return them as a list, preserving the labels exactly as "
                "they appear in the UI. The dropdown is virtualised — scroll "
                "inside the dropdown container until no new labels appear."
            ),
        )
    )

    return MarketplaceInstruction(
        command="marketplace list-categories",
        action_id="impact_marketplace_list_categories",
        objective=(
            "Enumerate every category label currently available in the Impact "
            "Marketplace UI so future search calls can use a known-valid "
            "category value."
        ),
        target_url=PORTAL_MARKETPLACE_URL,
        structured_context={
            "portal_login_url": PORTAL_LOGIN_URL,
            "portal_marketplace_url": PORTAL_MARKETPLACE_URL,
            "category_filter_trigger_text": "Categories",
        },
        steps=steps,
        extraction_target={
            "container_selector_hint": (
                "Expanded 'Categories' dropdown above the marketplace result grid"
            ),
            "fields": [
                {"name": "category_label", "description": "Verbatim category label as displayed in the UI"},
                {"name": "category_count", "description": "Optional program count next to each category, when shown"},
            ],
        },
        constraints=[
            "Do not infer categories from training data — return only labels actually visible on the live page.",
            "Preserve label spelling and casing exactly as displayed.",
            "Switch to 'All Brands' before opening the Categories dropdown. The 'Home' tab is a curated subset and the Categories filter is hidden or partial there.",
        ],
        success_criteria=[
            "A non-empty list of categories is returned.",
            "Each category includes its visible label; counts are included when displayed.",
        ],
        next_actions=[
            "impact marketplace search --category <label>  # to filter by one of the harvested categories",
        ],
    )


def render_text(instruction: MarketplaceInstruction) -> str:
    """Render an instruction object in human-readable plain text."""
    lines: List[str] = []
    lines.append(f"# {instruction.objective}")
    lines.append("")
    lines.append(f"DISCLAIMER: {instruction.disclaimer}")
    lines.append("")
    lines.append(f"Target URL: {instruction.target_url}")
    lines.append(f"Auth: {instruction.auth_note}")
    lines.append("")
    lines.append("Steps:")
    for index, step in enumerate(instruction.steps, start=1):
        suffix = ""
        if step.arguments:
            suffix = f"  [args: {step.arguments}]"
        lines.append(f"  {index}. ({step.action}) {step.description}{suffix}")
    lines.append("")
    lines.append("Extraction target:")
    lines.append(f"  Container hint: {instruction.extraction_target.get('container_selector_hint', '')}")
    fields = instruction.extraction_target.get("fields", [])
    for field in fields:
        lines.append(f"    - {field.get('name')}: {field.get('description')}")
    lines.append("")
    lines.append("Constraints:")
    for constraint in instruction.constraints:
        lines.append(f"  - {constraint}")
    lines.append("")
    lines.append("Success criteria:")
    for criterion in instruction.success_criteria:
        lines.append(f"  - {criterion}")
    lines.append("")
    lines.append("Next actions:")
    for action in instruction.next_actions:
        lines.append(f"  - {action}")
    return "\n".join(lines)
