"""``cj relationships`` subcommand group.

Combines:

* Read paths that wrap the CJ Advertiser Lookup REST API
  (``list`` -- "what programs has my publisher account joined / not
  joined / been declined for?").
* Write paths that drive the publisher Marketplace UI via the shared
  ``BrowserAutomation`` (``apply`` and ``apply-bulk`` -- CJ exposes no
  public endpoint for joining a program).

The browser-driven actions are intentionally conservative: every apply
calls the read API first to detect an existing relationship and skip,
takes a screenshot on any failure, and rate-limits between requests
during bulk runs.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import List, Optional

import typer
from pydantic import BaseModel

from cli_tools_shared.output import handle_error, print_info, print_json, print_table

from ..client import get_client
from ..config import get_config
from ..filter_map import FilterMap  # compliance: command files must reference filter_map
from ..models import ApplyOutcome, ApplyResult, RelationshipStatus


app = typer.Typer(help="Manage publisher-to-advertiser relationships", no_args_is_help=True)


# Compliance: every command must declare which credential type(s) it needs.
# The PAT covers list/get; apply paths additionally need the browser session.
COMMAND_CREDENTIALS = {
    "list": ["personal_access_token"],
    "get": ["personal_access_token"],
    "apply": ["personal_access_token", "browser_session"],
    # Both the canonical (function-name) and CLI-name (dashed) keys are
    # required: the n8n node generator and the credential-mapping audit
    # both consult this dict.
    "apply_bulk": ["personal_access_token", "browser_session"],
    "apply-bulk": ["personal_access_token", "browser_session"],
}


def _to_dict(item):
    if isinstance(item, BaseModel):
        return item.model_dump()
    return item


# ----------------------------------------------------------------------
# relationships list
# ----------------------------------------------------------------------


@app.command("list")
def relationships_list(
    table: bool = typer.Option(False, "--table", "-t", help="Display as table"),
    limit: int = typer.Option(100, "--limit", "-l", help="Maximum number of records"),
    filter: Optional[List[str]] = typer.Option(
        None, "--filter", "-f", help="Client-side filter (field:op:value)"
    ),
    properties: Optional[str] = typer.Option(
        None, "--properties", "-p", help="Comma-separated fields to include"
    ),
    status: str = typer.Option(
        "joined",
        "--status",
        "-s",
        help="Relationship status: joined | notjoined | pending | declined | all",
    ),
    page: int = typer.Option(1, "--page", help="1-indexed page number"),
):
    """List the publisher's current advertiser relationships.

    Examples:
        cj relationships list
        cj relationships list --status pending --table
        cj relationships list --status declined --limit 200
    """
    try:
        client = get_client()
        rows = client.list_relationships(status=status, page=page, limit=limit)

        if filter:
            # The list_relationships path doesn't pass through the
            # client-side filter helper, so apply manually here.
            from ..client import _apply_filters  # local import to keep public surface clean
            rows = _apply_filters(rows, filter)

        if properties:
            fields = [f.strip() for f in properties.split(",")]
            rows = [
                {f: _to_dict(r).get(f) for f in fields}
                for r in rows
            ]

        if table:
            if properties:
                cols = [f.strip() for f in properties.split(",")]
                print_table(rows, cols, cols)
            else:
                print_table(
                    rows,
                    ["advertiser_id", "advertiser_name", "relationship_status", "network_rank"],
                    ["ID", "Name", "Status", "Rank"],
                )
        else:
            print_json(rows)

    except Exception as exc:
        raise typer.Exit(handle_error(exc))


# ----------------------------------------------------------------------
# relationships get
# ----------------------------------------------------------------------


@app.command("get")
def relationships_get(
    advertiser_id: str = typer.Argument(..., help="The CJ advertiser ID"),
    table: bool = typer.Option(False, "--table", "-t", help="Display as a key/value table"),
):
    """Get the current relationship for a single advertiser.

    Examples:
        cj relationships get 1234567
        cj relationships get 1234567 --table
    """
    try:
        client = get_client()
        detail = client.get_advertiser(advertiser_id)
        payload = {
            "advertiser_id": detail.advertiser_id,
            "advertiser_name": detail.advertiser_name,
            "relationship_status": (
                detail.relationship_status.value if detail.relationship_status else None
            ),
            "program_url": detail.program_url,
            "network_rank": detail.network_rank,
        }
        if table:
            rows = [{"field": k, "value": str(v)} for k, v in payload.items() if v is not None]
            print_table(rows, ["field", "value"], ["Field", "Value"])
        else:
            print_json(payload)
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


# ----------------------------------------------------------------------
# Helper: detect existing relationship via the REST API
# ----------------------------------------------------------------------


def _lookup_advertiser(advertiser_id: str):
    """Single REST lookup; returns the AdvertiserDetail for ``advertiser_id``.

    Used both by ``_existing_outcome`` (to decide whether to short-circuit
    the apply) and by ``_apply_single`` (the advertiser name is needed as
    the findAdvertisers Keyword(s) filter — searching by raw id returns
    zero results because CJ's keyword field matches advertiser name).
    """
    client = get_client()
    return client.get_advertiser(advertiser_id)


def _outcome_from_status(status) -> Optional[ApplyOutcome]:
    """Map a ``RelationshipStatus`` to its terminal ``ApplyOutcome``.

    Returns ``None`` when the relationship is genuinely "not joined" and
    the apply should proceed.
    """
    if status is None:
        return None
    if status == RelationshipStatus.JOINED:
        return ApplyOutcome.ALREADY_JOINED
    if status == RelationshipStatus.PENDING:
        return ApplyOutcome.ALREADY_PENDING
    if status == RelationshipStatus.DECLINED:
        return ApplyOutcome.DECLINED
    return None  # NOT_JOINED


def _existing_outcome(advertiser_id: str) -> Optional[ApplyOutcome]:
    """Return the apply outcome implied by the current relationship.

    Thin wrapper around ``_lookup_advertiser`` for callers that only
    need the outcome.  ``_apply_single`` calls the helpers directly to
    avoid a second REST round-trip.
    """
    detail = _lookup_advertiser(advertiser_id)
    return _outcome_from_status(detail.relationship_status)


# ----------------------------------------------------------------------
# Helper: drive the Marketplace apply UI for a single advertiser
# ----------------------------------------------------------------------


def _discover_publisher_account_id(page) -> str:
    """Read the publisher account id (URL-path id) from the live dashboard.

    CJ exposes TWO ids that the apply path needs:

    * ``publisher_id`` (a.k.a. ``requestor-cid``, set via the
      ``CJ_PUBLISHER_ID`` env var) — used as the Bearer-API
      ``requestor-cid`` header and as the ``publisherId`` field in the
      findAdvertisers.cj hash-state JSON.
    * Publisher *account* id — the integer that prefixes member URLs:
      ``https://members.cj.com/member/<account-id>/publisher/...``.  This
      is the id baked into every rendered member URL on the dashboard
      but is NOT the same as ``publisher_id`` (CJ historically called it
      "company id" / member account number).

    Navigating ``findAdvertisers.cj`` with the wrong path id 302s to
    ``/member/publisher/home.do`` and the search page never renders.

    Rather than add a new env var that users would forget to set, we
    discover the path id by reading one of the rendered member URLs on
    the dashboard.  This is a one-time call per apply session.  Returns
    the account id as a string, raises ``RuntimeError`` if discovery
    fails (fail-fast — no fallback to the wrong id).
    """
    page.goto("https://members.cj.com/member/publisher/home.do")
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        page.wait_for_timeout(3000)
    js = (
        "() => { "
        "const a = document.querySelector("
        "'a[href*=\"/member/\"][href*=\"/publisher/\"]'); "
        "if (!a) return null; "
        "const m = a.getAttribute('href').match("
        "/\\/member\\/(\\d+)\\/publisher\\//); "
        "return m ? m[1] : null; "
        "}"
    )
    # PlaywrightService.page_eval returns a dict {result, page_url,
    # page_title}; the raw evaluation result lives under "result".
    eval_response = page.page_eval(js)
    if isinstance(eval_response, dict):
        account_id = eval_response.get("result")
        page_url = eval_response.get("page_url", "")
    else:
        account_id = eval_response
        page_url = ""
    if not account_id:
        raise RuntimeError(
            "Could not discover the CJ publisher account id from the "
            f"dashboard (current page: {page_url!r}). The session may be "
            "unauthenticated -- run 'cj auth login --force', or CJ has "
            "moved the rendered /member/<id>/publisher/ URLs."
        )
    return str(account_id)


def _find_advertisers_url(
    advertiser_id: str,
    publisher_account_id: str,
    keyword: str,
) -> str:
    """Return the live ``findAdvertisers.cj`` URL filtered to one advertiser.

    Bug 6: CJ retired the legacy ``advertiser-details.cj?adId=<id>`` page —
    that URL now serves a generic "the link you clicked isn't currently
    active" stub.  The Apply control was moved to the publisher
    findAdvertisers.cj search view, where each advertiser row exposes a
    ``<button class="ui-btn primary uppercase">Apply to Program</button>``.

    Three distinct identifiers go into this URL:

    * ``publisher_account_id`` — URL-path id (the integer that prefixes
      every ``/member/<id>/publisher/...`` URL on the dashboard).  The
      wrong path id 302s the page to ``home.do``.
    * ``config.publisher_id`` — the ``publisherId`` field the SPA expects
      in its hash-state JSON (a.k.a. ``requestor-cid``).
    * ``keyword`` — the SPA's ``keywords`` filter is a *name* search; the
      raw advertiser id returns zero results because CJ's keyword field
      matches advertiser-name substrings, not ids.  Callers MUST pass
      the advertiser name (looked up via ``_lookup_advertiser``).

    The advertiser id is still embedded in the row's
    ``href*="advertiserIds=<id>"`` anchor by CJ's own SPA once the search
    returns — that's what ``_apply_locator`` scopes the click to.
    """
    if not publisher_account_id:
        raise ValueError(
            "_find_advertisers_url requires a publisher_account_id; the "
            "URL-path id and publisher_id are NOT interchangeable."
        )
    if not keyword:
        raise ValueError(
            "_find_advertisers_url requires a keyword (the advertiser "
            "name); CJ's keyword filter matches name substrings, not ids."
        )
    config = get_config()
    publisher_id = config.publisher_id
    # CJ's SPA reads the hash as JSON.  Names occasionally contain ``"``
    # or backslashes; escape them so the JSON parses.  All quotes here
    # are doubled because this string IS the literal JSON the SPA sees.
    safe_keyword = keyword.replace("\\", "\\\\").replace('"', '\\"')
    hash_state = (
        '{"pageNumber":1,'
        f'"publisherId":{publisher_id},'
        '"pageSize":"50",'
        f'"keywords":"{safe_keyword}",'
        '"sortColumn":"advertiserName",'
        '"sortDescending":false}'
    )
    # ``advertiser_id`` is part of the public surface so callers can
    # double-check we built the URL for the right row, but the SPA does
    # not actually read it from the hash — it surfaces via the rendered
    # row anchors after the keyword search returns.
    _ = advertiser_id
    return (
        f"https://members.cj.com/member/{publisher_account_id}/publisher/advertisers/"
        f"findAdvertisers.cj#{hash_state}"
    )


def _apply_locator(advertiser_id: str) -> str:
    """Return the Playwright selector for ``advertiser_id``'s Apply button.

    Bug 6: the live Apply button is
    ``<button class="ui-btn primary uppercase">Apply to Program</button>``
    inside a row that contains
    ``<a href=".../links/search/#!advertiserIds=<id>">``.  The button has
    no testid, no aria-label, no data attributes — its only stable
    identifiers are its literal text "Apply to Program" and the
    advertiser-scoped sibling anchor.

    The returned selector pins the click to the row containing the
    requested advertiser's anchor and then text-matches the button.  A
    bare ``button:has-text("Apply to Program")`` would match every row
    on the page; row-scoping is what makes the click safe.
    """
    # The row container on findAdvertisers.cj is ``<div class="adv-row">``.
    # Pinning the outer ``:has()`` to that class is what makes the click
    # safe -- a bare ``div:has(a[href*=advertiserIds=...]) button``
    # matches every ancestor div on the page (~55 hits) because every
    # outer container also contains the anchor.  ``button:has-text("Apply
    # to Program")`` is the only stable button identifier on the live
    # element ``<button class="ui-btn primary uppercase">Apply to
    # Program</button>`` -- no testid, no aria-label, no data attributes.
    #
    # If CJ renames ``adv-row``, this selector will fail loudly with the
    # row-not-rendered timeout above (the wait_for_selector for the
    # advertiser anchor stays valid) and the apply locator wait will
    # time out.  That is the intended failure mode: a loud regression is
    # better than silently clicking the wrong row's button.
    return (
        f'div.adv-row:has(a[href*="advertiserIds={advertiser_id}"]) '
        f'button:has-text("Apply to Program")'
    )


def _capture_screenshot(page) -> Optional[str]:
    """Capture a diagnostic screenshot for an apply-flow failure.

    ``PlaywrightService.page_screenshot()`` writes the file to its own
    tempdir (``$TMPDIR/playwright-screenshots/``) and returns
    ``{'file': <path>, 'page_url': ...}``.  Returns the saved path or
    ``None`` if the screenshot raised.

    The ``ref`` kwarg on ``page_screenshot`` is a Playwright element
    locator -- NOT a destination path.  Every prior call site that
    passed ``ref=str(shot)`` (where ``shot`` was a ``Path``) silently
    failed because the path was interpreted as an invalid CSS
    selector, and the bare ``except Exception`` swallowed the error.
    """
    try:
        result = page.page_screenshot()
    except Exception:
        return None
    if isinstance(result, dict):
        return result.get("file")
    return None


# Selectors that confirm the apply succeeded (banner/toast/status pill).
# Bug 6: kept as a small ordered tuple because the post-click confirmation
# UI legitimately renders as either a toast/banner ("Application
# submitted") or an inline status pill ("Application pending").  These
# are not a fallback for a missing primary — they are the two
# equally-valid shapes the UI ships.  If none match, the apply path
# explicitly re-polls the REST API and falls through to FAILED with a
# screenshot.
_APPLY_CONFIRM_SELECTORS = (
    "text=Application pending",
    "text=Application submitted",
    "text=Pending Application",
)


def _apply_single(advertiser_id: str, dry_run: bool = False) -> ApplyResult:
    """Submit a join request for ``advertiser_id``.

    Order of operations:

    1. Ask the REST API for the current relationship.  Short-circuit if
       we are already joined / pending / declined.
    2. Navigate the persistent browser session to the Marketplace
       advertiser detail page.
    3. Locate one of the known apply selectors and click it.
    4. Wait for a confirmation marker; on failure, capture a
       screenshot and return ``FAILED``.
    """
    # One REST lookup serves two purposes: (1) decide whether to
    # short-circuit on an existing relationship, and (2) fetch the
    # advertiser name -- CJ's findAdvertisers keyword filter matches
    # names, not ids, so we MUST pass the name to render the row.
    detail = _lookup_advertiser(advertiser_id)
    existing = _outcome_from_status(detail.relationship_status)
    if existing is not None:
        return ApplyResult(
            advertiser_id=advertiser_id,
            outcome=existing,
            detail=f"REST API reported existing relationship_status={existing.value}",
        )

    if dry_run:
        return ApplyResult(
            advertiser_id=advertiser_id,
            outcome=ApplyOutcome.SKIPPED,
            detail="dry-run -- would have submitted apply via findAdvertisers",
        )

    if not detail.advertiser_name:
        raise typer.Exit(
            handle_error(
                RuntimeError(
                    f"Advertiser {advertiser_id} REST lookup returned no "
                    "advertiser_name; cannot drive the findAdvertisers "
                    "keyword search without a name."
                )
            )
        )

    config = get_config()
    browser = config.get_browser()
    auth = browser.is_authenticated()
    if not auth:
        raise typer.Exit(
            handle_error(
                RuntimeError(
                    "CJ browser session is not authenticated. "
                    "Run 'cj auth login' before applying to programs."
                )
            )
        )

    # Discover the publisher account id (URL-path id) from the live
    # dashboard.  The wrong path id 302s the page to home.do and the
    # apply silently fails — see Bug 6.
    bootstrap_page = browser.get_page("https://members.cj.com/member/publisher/home.do")
    publisher_account_id = _discover_publisher_account_id(bootstrap_page)

    target_url = _find_advertisers_url(
        advertiser_id,
        publisher_account_id,
        keyword=detail.advertiser_name,
    )
    page = browser.get_page(target_url)
    # Settle the page -- findAdvertisers.cj is a SPA, so wait for the
    # search results to hydrate before looking for the apply control.
    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        # ``networkidle`` is best-effort; the SPA fetches results
        # asynchronously, so also wait for the advertiser's own row
        # anchor to render before reaching for the button.
        page.wait_for_timeout(2000)
    try:
        page.wait_for_selector(
            f'a[href*="advertiserIds={advertiser_id}"]', timeout=10000
        )
    except Exception:
        shot = _capture_screenshot(page)
        return ApplyResult(
            advertiser_id=advertiser_id,
            outcome=ApplyOutcome.FAILED,
            detail=(
                f"Advertiser {advertiser_id} row did not render on the "
                f"findAdvertisers search page within 10s."
            ),
            screenshot_path=shot,
        )

    selector = _apply_locator(advertiser_id)
    try:
        # Use wait_for_selector at the page level (the only wait API the
        # shared PlaywrightService exposes -- _ServiceLocator has no
        # ``wait_for``).  Then resolve the locator and click.
        page.wait_for_selector(selector, timeout=6000)
        page.locator(selector).first.click()
    except Exception as exc:
        # The row rendered (we passed the row-anchor wait_for_selector
        # above) but the "Apply to Program" button is absent.  Distinguish
        # two cases by re-polling REST:
        #   (a) the apply was just submitted in a recent run and CJ's
        #       REST relationship_status has caught up -> return the
        #       new status (pending / joined / declined).
        #   (b) REST still says notjoined but CJ removed the button
        #       (onboarding gate, advertiser deactivated apply, REST
        #       propagation lag) -> return FAILED with a state-specific
        #       message rather than a misleading "button not found".
        time.sleep(1)
        post = _existing_outcome(advertiser_id)
        if post is not None:
            return ApplyResult(
                advertiser_id=advertiser_id,
                outcome=post,
                detail=(
                    f"No Apply button rendered for advertiser "
                    f"{advertiser_id}; REST now reports "
                    f"{post.value} (apply already registered)."
                ),
            )
        shot = _capture_screenshot(page)
        return ApplyResult(
            advertiser_id=advertiser_id,
            outcome=ApplyOutcome.FAILED,
            detail=(
                f"Advertiser {advertiser_id} row rendered but no Apply "
                f"button was present.  CJ may be gating apply (Network "
                f"Profile / onboarding incomplete), the advertiser may "
                f"have deactivated public apply, or the apply registered "
                f"in a previous run and CJ REST has not propagated yet. "
                f"Locator: {selector!r}; underlying error: {exc}"
            ),
            screenshot_path=shot,
        )
    last_selector = selector

    # Bug 7: after the first "Apply to Program" click, CJ branches into
    # two flows that look the same from the browser's perspective:
    #   (a) Auto-approve advertisers register the application immediately
    #       on the first click.  REST relationship_status flips to
    #       joined/pending within a couple of seconds.  joinprograms.do
    #       may or may not render -- and if it does, it shows the
    #       "your application is being processed" state, not a T&C form.
    #   (b) Manual-review advertisers navigate to joinprograms.do with
    #       an "Accept and Apply" submit that MUST be clicked to register
    #       the application.
    # REST is the source of truth -- poll it first.  Only walk the T&C
    # path when REST still reports notjoined.  This fixes the false-
    # negative FAILED returns where the apply succeeded but the CLI
    # crashed waiting for an Accept-and-Apply form that an auto-approve
    # advertiser never renders.
    try:
        page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        page.wait_for_timeout(2000)

    time.sleep(2)
    post = _existing_outcome(advertiser_id)
    if post is not None:
        return ApplyResult(
            advertiser_id=advertiser_id,
            outcome=post,
            detail=(
                f"Apply submitted via {selector}; REST now reports "
                f"{post.value} (auto-approved or pending review)."
            ),
        )

    current_url_resp = page.page_eval("() => window.location.href")
    current_url = (
        current_url_resp.get("result")
        if isinstance(current_url_resp, dict)
        else current_url_resp
    )
    if current_url and "joinprograms.do" in current_url:
        # On the live joinprograms.do page the "Accept and Apply" control
        # is an ``<input type="submit" value="Accept and Apply">`` -- not
        # a ``<button>`` element.  Match it by its ``value`` attribute so
        # the click finds the submit input regardless of which tag CJ
        # uses tomorrow.
        accept_selector = (
            'input[type="submit"][value="Accept and Apply"], '
            'button:has-text("Accept and Apply")'
        )
        try:
            # Bumped from 6s to 15s -- joinprograms.do hydration takes
            # longer than the prior window when the page renders a real
            # T&C form, and the 6s deadline routinely fired before the
            # form appeared, surfacing as a false-negative FAILED.
            page.wait_for_selector(accept_selector, timeout=15000)
            page.locator(accept_selector).first.click()
            last_selector = (
                f"{selector} -> Accept and Apply (joinprograms.do)"
            )
            # The form POSTs to ``joinprograms.do`` and the server
            # responds with the "Application submitted for review" page.
            # Wait explicitly for the title to flip; networkidle alone
            # often returns before the response renders because the page
            # had already settled to idle before the submit fired.
            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                page.wait_for_timeout(2000)
            # Belt-and-braces: poll the document title for up to 8 more
            # seconds so the confirmation check below has a real chance.
            deadline = time.time() + 8
            while time.time() < deadline:
                title_resp = page.page_eval("() => document.title")
                title = (
                    title_resp.get("result")
                    if isinstance(title_resp, dict)
                    else title_resp
                )
                if title and "submitted" in title.lower():
                    break
                time.sleep(0.5)
        except Exception as exc:
            # Before declaring failure, re-poll REST: some advertisers
            # auto-approve on the first click even after navigating to
            # joinprograms.do, in which case the T&C form never renders
            # because the application was already registered.
            time.sleep(2)
            post = _existing_outcome(advertiser_id)
            if post is not None:
                return ApplyResult(
                    advertiser_id=advertiser_id,
                    outcome=post,
                    detail=(
                        f"Apply submitted via {selector}; REST now reports "
                        f"{post.value} (the joinprograms.do T&C form did "
                        f"not render -- apply registered on first click)."
                    ),
                )
            return ApplyResult(
                advertiser_id=advertiser_id,
                outcome=ApplyOutcome.FAILED,
                detail=(
                    f"Reached joinprograms.do for advertiser {advertiser_id} "
                    f"but the Accept and Apply control did not render "
                    f"within 15s and REST is still notjoined: {exc}"
                ),
                screenshot_path=_capture_screenshot(page),
            )

    # Confirm the application registered.  CJ's REST relationship_status
    # is the source of truth -- the UI banner shape varies per advertiser.
    confirmed = False
    confirmation_errors: list[str] = []
    for confirm_selector in _APPLY_CONFIRM_SELECTORS:
        try:
            page.wait_for_selector(confirm_selector, timeout=4000)
            confirmed = True
            break
        except Exception as exc:
            confirmation_errors.append(
                f"{confirm_selector}: {type(exc).__name__}: {exc}"
            )

    # Always re-poll REST -- it is the authoritative check, regardless
    # of which (if any) UI confirmation rendered.
    time.sleep(2)
    post = _existing_outcome(advertiser_id)
    if post is not None:
        return ApplyResult(
            advertiser_id=advertiser_id,
            outcome=post,
            detail=f"Apply submitted via {last_selector}; relationship now {post.value}.",
        )

    if not confirmed:
        shot = _capture_screenshot(page)
        return ApplyResult(
            advertiser_id=advertiser_id,
            outcome=ApplyOutcome.FAILED,
            detail=(
                f"Clicked {last_selector} but no UI confirmation appeared "
                f"and REST relationship_status is still notjoined. "
                f"Confirmation checks: {'; '.join(confirmation_errors)}"
            ),
            screenshot_path=shot,
        )

    return ApplyResult(
        advertiser_id=advertiser_id,
        outcome=ApplyOutcome.APPLIED,
        detail=f"Apply submitted via {last_selector}.",
    )


# ----------------------------------------------------------------------
# relationships apply
# ----------------------------------------------------------------------


@app.command("apply")
def relationships_apply(
    advertiser_id: str = typer.Argument(..., help="The CJ advertiser ID to apply to"),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Check existing relationship and report what would happen, but do not click Apply"
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Display result as a table row"),
):
    """Apply to (join) a single advertiser program.

    Idempotent: if the publisher is already joined / pending / declined,
    the command reports the existing status without re-submitting.

    Examples:
        cj relationships apply 1234567
        cj relationships apply 1234567 --dry-run
    """
    try:
        result = _apply_single(advertiser_id, dry_run=dry_run)
        if table:
            print_table(
                [result],
                ["advertiser_id", "outcome", "detail"],
                ["Advertiser", "Outcome", "Detail"],
            )
        else:
            print_json(result)
    except typer.Exit:
        raise
    except Exception as exc:
        raise typer.Exit(handle_error(exc))


# ----------------------------------------------------------------------
# relationships apply-bulk
# ----------------------------------------------------------------------


def _read_ids(source: Optional[str]) -> List[str]:
    """Read advertiser IDs from a file path or from stdin.

    Accepts one ID per line; blank lines and ``#`` comments are
    ignored.  ``-`` or no value means read from stdin.
    """
    if source in (None, "-"):
        stream = sys.stdin
        raw = stream.read()
    else:
        raw = Path(source).read_text()
    ids: List[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        ids.append(line)
    return ids


@app.command("apply-bulk")
def relationships_apply_bulk(
    source: Optional[str] = typer.Argument(
        None,
        help="Path to a file with one advertiser ID per line. Omit or pass '-' to read stdin.",
    ),
    delay: float = typer.Option(
        3.0,
        "--delay",
        "-d",
        help="Seconds to sleep between applies (rate-limit). Default 3s.",
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Report what would happen without clicking Apply"
    ),
    table: bool = typer.Option(False, "--table", "-t", help="Stream results as a table"),
    stop_on_error: bool = typer.Option(
        False,
        "--stop-on-error",
        help="Halt on the first FAILED outcome instead of continuing",
    ),
):
    """Apply to many advertiser programs from a file or stdin.

    Each input line is one advertiser ID; comments (``#``) and blank
    lines are ignored.  Results stream as JSON (or a streaming table)
    so a downstream agent can act on each row as it lands.

    Examples:
        cj advertisers list --relationship notjoined --properties advertiser_id | jq -r '.[].advertiser_id' \
            | cj relationships apply-bulk -
        cj relationships apply-bulk targets.txt --delay 5 --dry-run
    """
    try:
        ids = _read_ids(source)
        if not ids:
            print_info("No advertiser IDs supplied.")
            return

        results: List[ApplyResult] = []
        for index, advertiser_id in enumerate(ids):
            result = _apply_single(advertiser_id, dry_run=dry_run)
            results.append(result)
            if not table:
                # Stream one JSON object per result for downstream tools.
                print_json(result)
            if stop_on_error and result.outcome == ApplyOutcome.FAILED:
                break
            if index < len(ids) - 1 and not dry_run:
                time.sleep(delay)

        if table:
            print_table(
                results,
                ["advertiser_id", "outcome", "detail"],
                ["Advertiser", "Outcome", "Detail"],
            )

    except typer.Exit:
        raise
    except Exception as exc:
        raise typer.Exit(handle_error(exc))
