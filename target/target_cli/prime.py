"""Capture the redsky read session via a real (headed) browser.

Target's redsky API only honors ``_tgt_token`` / ``_tgt_session`` cookies minted
by a genuine, visible browser (headless requests are 403'd by PerimeterX). This
opens a headed browser, mints + harvests those cookies, persists them (see
``session.py``), and verifies them with a live httpx search before trusting them.
No partial or unverified session is ever saved.

Kept out of ``browser.py`` so the ``BrowserAutomation`` subclass stays declarative.
"""

import os

from cli_tools_shared.exceptions import ClientError
from cli_tools_shared.output import print_info

from . import session as session_store

# A stable, high-availability product page whose client-side XHR mints _tgt_token.
# The prime is verified by a real search, so it still succeeds if this exact TCIN
# is ever delisted.
PRIME_TCIN = "88830890"  # Energizer Max AA


def prime_redsky(config) -> int:
    """Open a headed browser, capture + verify redsky cookies, persist them.

    Returns the product count from the verification search. Raises ``ClientError``
    if a working session could not be captured.
    """
    print_info("Priming fast-search session (a browser window will open briefly)...")

    # redsky rejects headless-minted tokens, so force a visible browser for the
    # capture regardless of the HEADLESS setting.
    prev_headless = os.environ.get("HEADLESS")
    os.environ["HEADLESS"] = "false"
    browser = config.get_browser()
    try:
        page = browser.get_page("https://www.target.com")
        page.wait_for_timeout(6000)  # let the PerimeterX sensor run in the visible browser
        page = browser.get_page(f"https://www.target.com/p/-/A-{PRIME_TCIN}")
        try:
            page.wait_for_network_idle(timeout=12.0, idle_ms=800)
        except Exception:
            pass
        page.wait_for_timeout(3000)

        cookies = {c["name"]: c for c in page.cookie_list()}
        token, sess, visitor = (
            cookies.get("_tgt_token"),
            cookies.get("_tgt_session"),
            cookies.get("visitorId"),
        )
        if not (token and sess and visitor):
            missing = [
                name for name, cookie in
                (("_tgt_token", token), ("_tgt_session", sess), ("visitorId", visitor))
                if not cookie
            ]
            raise ClientError(f"Could not capture redsky cookies ({', '.join(missing)} missing).")

        captured = session_store.save_session(
            config,
            tgt_token=token["value"],
            tgt_session=sess["value"],
            visitor_id=visitor["value"],
            store_id=config.store_id,
            zip=config.zip,
        )
    finally:
        browser.close()
        if prev_headless is None:
            os.environ.pop("HEADLESS", None)
        else:
            os.environ["HEADLESS"] = prev_headless

    # Verify the captured session actually authorizes redsky (httpx, no browser).
    from .api import RedskyAPI

    api = RedskyAPI(captured)
    try:
        result = api.search("aa batteries", count=5)
    except ClientError:
        session_store.clear_session(config)
        raise ClientError(
            "Captured a redsky session but it was rejected on verification. "
            "Re-run `target session refresh` from a normal desktop session."
        )
    finally:
        api.close()

    count = len((result.get("data", {}).get("search", {}) or {}).get("products", []) or [])
    if count == 0:
        session_store.clear_session(config)
        raise ClientError("redsky verification returned no results; session not saved.")
    print_info(f"Fast-search session captured and verified ({count} results).")
    return count
