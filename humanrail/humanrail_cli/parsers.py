"""Parse task data returned by HumanRail's internal worker API.

HumanRail's frontend (a React SPA) never renders task rows as plain HTML —
it fetches JSON from `/api/workers/me/tasks/available` and
`/api/workers/me/tasks/<id>` and reads a bearer token out of localStorage
(`ee_auth_token`) to authorize the call. `client.py` reproduces that exact
call from inside the authenticated page (a fetch with the same header the
site's own code sends) and hands the parsed JSON here.

Field names below were validated against the live, deployed frontend bundle
(`index-kyQ5X666.js`, fetched 2026-09-02) — the task-card component
(`O1`) and the task-detail component (`uk`) read these exact properties off
each task object:
  - id, type, payout_sats, risk_tier, skills_required, estimated_minutes,
    sla_deadline, sla_seconds (list + detail)
  - status, description, payload, verification_result{feedback,earned_sats}
    (detail only)

No live task existed on the account at validation time (`{"tasks":[],
"total":0}` from `/api/workers/me/tasks/available` — the site currently has
zero open tasks), so these are the site's own verified field names rather
than an observed live instance. Any field HumanRail's API does not return
for a given task stays `None` — nothing here is invented.
"""
from typing import Any, Dict, List, Optional


def normalize_task_row(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize one row from `/api/workers/me/tasks/available`."""
    task_id = raw.get("id")
    return {
        "id": task_id,
        "url": f"https://routehuman.com/queue/{task_id}" if task_id else None,
        "type": raw.get("type"),
        "payout_sats": raw.get("payout_sats"),
        "risk_tier": raw.get("risk_tier"),
        "skills_required": raw.get("skills_required") or [],
        "estimated_minutes": raw.get("estimated_minutes"),
        "sla_deadline": raw.get("sla_deadline"),
        "sla_seconds": raw.get("sla_seconds"),
    }


def normalize_task_detail(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a `/api/workers/me/tasks/<id>` response."""
    task_id = raw.get("id")
    verification = raw.get("verification_result") or None
    return {
        "id": task_id,
        "url": f"https://routehuman.com/queue/{task_id}" if task_id else None,
        "type": raw.get("type"),
        "status": raw.get("status"),
        "payout_sats": raw.get("payout_sats"),
        "risk_tier": raw.get("risk_tier"),
        "skills_required": raw.get("skills_required") or [],
        "estimated_minutes": raw.get("estimated_minutes"),
        "sla_deadline": raw.get("sla_deadline"),
        "sla_seconds": raw.get("sla_seconds"),
        "description": raw.get("description"),
        "payload": raw.get("payload"),
        "verification_feedback": verification.get("feedback") if verification else None,
        "verification_earned_sats": verification.get("earned_sats") if verification else None,
    }


def normalize_task_rows(raw_tasks: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Normalize the `tasks` array from a list-endpoint response."""
    return [normalize_task_row(item) for item in (raw_tasks or [])]
