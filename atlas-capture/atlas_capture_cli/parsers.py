"""Parse Atlas Capture worker data returned by the site's internal API.

Atlas Capture's worker portal (audit.atlascapture.io) is a Next.js app whose
authenticated pages are painted from tRPC calls to ``/api/trpc/<procedure>``,
never from server-rendered HTML. ``client.py`` reproduces the site's own
same-origin GETs from inside the authenticated page, and the raw JSON lands
here.

Endpoints and payload shapes were captured live 2026-09-03 from Adam's
authenticated session (request = plain GET of the procedure path):

  GET /api/trpc/user.me                  -> account record
  GET /api/trpc/rooms.getConfig          -> labeling rooms + access state
  GET /api/trpc/user.getAccountStatus    -> account-activity bucket
  GET /api/trpc/payment.getSurgeStatus   -> pay tiers / surge eligibility
  GET /api/trpc/humanVerifier.migrationExperience -> cohort + cert state
  GET /api/trpc/certification.getAll     -> earned certifications

A tRPC GET response is wrapped as ``{"result": {"data": {"json": <payload>}}}``
on this site (tRPC's "split" / batched envelope with ``meta.values`` marking
dates); ``unwrap_trpc`` returns the inner payload.

TASKS ARE CURRENTLY EMPTY FOR THIS ACCOUNT — verified live, not assumed:

  * navigating ``/tasks`` immediately redirects to ``/dashboard`` (the account
    has no Tasks route / nav item), and
  * ``rooms.getConfig`` and ``humanVerifier.migrationExperience`` report the
    account is NOT certified (``certified: false``,
    ``certification.getAll == []``) while the platform is under a
    "Temporary Labeling Pause" announcement.

No real task record has therefore ever been captured, so no task-row field
mapping exists: ``normalize_task_rows`` refuses any non-empty record list with
a loud error rather than guessing a schema. ``tasks list`` returns ``[]`` only
when the live route check proves no task surface exists. Everything else the
API returns is mapped as captured.
"""

from typing import Any, Dict, List, Optional

from cli_tools_shared.exceptions import ClientError

DASHBOARD_URL = "https://audit.atlascapture.io/dashboard"
TASKS_URL = "https://audit.atlascapture.io/tasks"


def unwrap_trpc(body: Any) -> Any:
    """Return the inner payload of this site's tRPC GET envelope.

    ``{"result": {"data": {"json": <payload>, "meta": ...}}}`` -> <payload>.
    Anything else is a contract mismatch and fails loudly — a payload shape
    change must be re-captured, not silently unwrapped differently.
    """
    if not isinstance(body, dict):
        raise ClientError(f"tRPC response is not an object: {body!r}")
    result = body.get("result")
    if not isinstance(result, dict):
        raise ClientError(f"tRPC response has no 'result' object: keys={list(body)}")
    data = result.get("data")
    if not isinstance(data, dict):
        raise ClientError(f"tRPC result has no 'data' object: keys={list(result)}")
    payload = data.get("json")
    return payload


def normalize_user_me(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize the ``user.me`` account record (captured live 2026-09-03).

    Only fields the site actually returned are emitted; anything absent stays
    ``None`` rather than being invented. ``id`` is the Mongo ObjectId string.
    """
    return {
        "id": raw.get("id"),
        "email": raw.get("email"),
        "first_name": raw.get("firstName"),
        "last_name": raw.get("lastName"),
        "full_name": _full_name(raw.get("firstName"), raw.get("lastName")),
        "country": raw.get("country"),
        "role": raw.get("role"),
        "reviewer_tier": raw.get("reviewerTier"),
        "is_paused": raw.get("isPaused"),
        "onboarding_step": raw.get("onboardingStep"),
        "onboarding_completed": raw.get("onboardingCompleted"),
        "gt_probation_completed": raw.get("gtProbationCompleted"),
        "certified_role_count": len(
            (raw.get("partnerContext") or {}).get("certifiedRoles") or []),
    }


def normalize_rooms_config(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize ``rooms.getConfig``: which labeling room the account can use.

    ``access`` carries the real gating facts: the room's ``hasAccess`` flag,
    any ``lockReason``, and the ``enabled`` flag of the ``normal`` room.
    """
    room_config = raw.get("roomConfig") or {}
    rooms = room_config.get("rooms") or {}
    normal = rooms.get("normal") or {}
    access = raw.get("normalRoomAccess") or {}
    return {
        "default_room_id": room_config.get("defaultRoomId"),
        "room_enabled": normal.get("enabled"),
        "room_label": normal.get("label"),
        "has_access": access.get("hasAccess"),
        "lock_reason": access.get("lockReason"),
        "admin_only": access.get("adminOnly"),
        "room_portal_enabled": bool((raw.get("featureFlags") or {}).get("roomPortalEnabled")),
    }


def normalize_account_status(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize ``user.getAccountStatus`` (activity bucket facts)."""
    return {
        "bucket": raw.get("bucket"),
        "unit_label": raw.get("unitLabel"),
        "episodes_this_period": raw.get("episodesThisPeriod"),
        "is_stale": raw.get("isStale"),
        "at_risk": raw.get("atRisk"),
        "period_start": raw.get("periodStart"),
        "period_end": raw.get("periodEnd"),
    }


def normalize_task_rows(records: Any) -> List[Dict[str, Any]]:
    """Normalize the raw ``tasks list`` records into task rows.

    The site currently exposes no task records for this account (see module
    docstring), so the only real payload is an empty list — which maps to an
    empty task list. A non-empty record list has never been captured, so
    instead of guessing a schema it raises; the mapping must be written from
    the first real record the day tasks become visible.
    """
    if records is None:
        return []
    if not isinstance(records, list):
        raise ClientError(
            f"Atlas Capture task payload is not a list: {type(records).__name__}"
        )
    if records:
        raise ClientError(
            "Atlas Capture returned task records, but no real Atlas task record "
            "has ever been captured, so there is no schema to map them with. "
            "Capture one first (the day /tasks stops redirecting for this "
            "account) and implement the mapping from that real record."
        )
    return []


def evaluate_tasks_route_state(final_url: str, page_text: str) -> Dict[str, Any]:
    """Judge whether ``/tasks`` rendered a task surface for this account.

    ``final_url`` is where the browser ended after requesting ``/tasks`` and
    ``page_text`` is the rendered body text. Pure function over captured state
    so it is unit-testable against real fixture evidence.
    """
    if not final_url:
        return {"has_tasks_surface": False,
                "reason": "no page state captured after requesting /tasks"}
    if _url_path(final_url).startswith("/tasks"):
        # Still on the /tasks URL itself: the surface exists.
        text = (page_text or "").strip()
        if not text:
            return {"has_tasks_surface": True, "reason": None, "empty": True}
        lowered = text.lower()
        empty_markers = ("no tasks", "nothing to do", "all caught up",
                         "no available", "currently no")
        return {
            "has_tasks_surface": True,
            "reason": None,
            "empty": any(marker in lowered for marker in empty_markers),
        }
    if _url_path(final_url).startswith(("/login", "/verify")):
        return {"has_tasks_surface": False,
                "reason": "the /tasks route redirected to the login/verify flow "
                          "(session not authenticated)"}
    # Redirected to /dashboard (observed live) or another route.
    return {"has_tasks_surface": False,
            "reason": f"the /tasks route redirected to {final_url} — no task "
                      "surface is available to this account right now (not "
                      "certified and/or labeling paused)."}


def _full_name(first: Optional[str], last: Optional[str]) -> Optional[str]:
    if not first and not last:
        return None
    return " ".join(part for part in (first, last) if part)


def _url_path(url: str) -> str:
    """Path component of a URL (``https://host/a/b?x=1`` -> ``/a/b``)."""
    without_query = url.split("?", 1)[0].split("#", 1)[0]
    if "://" not in without_query:
        return without_query
    rest = without_query.split("://", 1)[1]
    if "/" not in rest:
        return "/"
    return "/" + rest.split("/", 1)[1]
