"""Parse DOM data extracted from Microworkers worker-side pages.

Selectors and field shapes below were validated against the live site
(microworkers.com) on 2026-09-02 using an authenticated browser session:
  - Job listing rows: div.jobslist on /jobs.php (id="campaign<hex>")
  - Job detail pages: .jobarealeft / .jobdetailsnoteleft / .jobdetailsnoteright /
    .jobdetailsbox, shared across the "microworkers" (jobs_details.php) and
    "hire_group" (hm_jobs_details.php) worker job types.

Microworkers lists three distinct worker job systems from /jobs.php:
  - "microworkers": classic campaign jobs (jobs_details.php?Id=<obfuscated>,
    submitted via POST /jobs_i_did_it.php)
  - "hire_group": Hire Group jobs (hm_jobs_details.php?Id=<hex>, submitted via
    POST /hm_jobs_i_did_it.php)
  - "ttv": TTV-branded campaign jobs, whose read-only detail page lives on the
    separate ttv.microworkers.com subdomain. The CLI parses those details but
    deliberately does not implement TTV apply/accept/proof submission.
"""
import re
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlsplit


APPLY_PATHS = {
    "/jobs_details.php": ("microworkers", "https://www.microworkers.com/jobs_i_did_it.php"),
    "/hm_jobs_details.php": ("hire_group", "https://www.microworkers.com/hm_jobs_i_did_it.php"),
}

PAYMENT_STATUS_BY_HISTORY_STATUS = {
    "Satisfied & paid": "paid",
    "Not-Satisfied": "not_paid",
    "Pending Employer review": "pending",
    "Revise": "pending",
}


def provider_for_url(url: Optional[str]) -> str:
    """Classify a task detail URL into its worker job system."""
    if not url:
        return "unknown"
    if "ttv.microworkers.com" in url:
        return "ttv"
    if "hm_jobs_details.php" in url:
        return "hire_group"
    if "jobs_details.php" in url:
        return "microworkers"
    return "unknown"


def parse_apply_target(url: str) -> tuple[str, str, str]:
    """Return the provider, task ID, and required POST action for a task URL.

    Mutation targets use a stricter parser than listing classification: only
    HTTPS worker-detail URLs on the exact Microworkers host are accepted.
    """
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ValueError("task URL is malformed") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != "www.microworkers.com"
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.fragment
    ):
        raise ValueError(
            "task URL must be an HTTPS worker task on www.microworkers.com"
        )
    if parsed.path not in APPLY_PATHS:
        raise ValueError(
            "task URL path must be /jobs_details.php or /hm_jobs_details.php"
        )
    query = parse_qs(parsed.query, keep_blank_values=True)
    if set(query) != {"Id"} or len(query["Id"]) != 1 or not query["Id"][0]:
        raise ValueError("task URL must contain exactly one non-empty Id parameter")
    provider, action = APPLY_PATHS[parsed.path]
    return provider, query["Id"][0], action


def parse_ttv_detail_target(url: str) -> str:
    """Return the campaign ID from an exact, read-only TTV task-detail URL."""
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError) as exc:
        raise ValueError("TTV task URL is malformed") from exc
    if (
        parsed.scheme != "https"
        or parsed.hostname != "ttv.microworkers.com"
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "TTV task URL must be HTTPS on ttv.microworkers.com without query or fragment"
        )
    match = re.fullmatch(r"/dotask/info/([0-9a-f]{12}_(?:B|HG))", parsed.path)
    if not match:
        raise ValueError(
            "TTV task URL path must be /dotask/info/<12_HEX_ID_B_OR_HG>"
        )
    return match.group(1)


def _parse_int(value: Optional[str]) -> Optional[int]:
    if not value:
        return None
    match = re.search(r"-?\d+", value)
    return int(match.group()) if match else None


def _split_done_total(value: Optional[str]) -> tuple:
    """Split a "2980/3000" style string into (done, total) ints."""
    if not value:
        return (None, None)
    match = re.search(r"(\d+)\s*/\s*(\d+)", value)
    if not match:
        return (None, None)
    return (int(match.group(1)), int(match.group(2)))


def normalize_task_row(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize one /jobs.php listing row (from LIST_JS) into a task record."""
    url = raw.get("url")
    done, total = _split_done_total(raw.get("done"))
    return {
        "id": url,
        "campaign_id": raw.get("campaign_id"),
        "title": raw.get("title"),
        "provider": provider_for_url(url),
        "url": url,
        "payment": raw.get("payment"),
        "success_rate_required": _parse_int(raw.get("success_rate")),
        "ttr_days": _parse_int(raw.get("ttr_days")),
        "ttf_minutes": _parse_int(raw.get("ttf_minutes")),
        "positions_done": done,
        "positions_total": total,
    }


def normalize_task_detail(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a task detail page (from DETAIL_JS) into a task record."""
    url = raw.get("url")
    return {
        "id": url,
        "url": url,
        "provider": provider_for_url(url),
        "title": raw.get("title"),
        "work_summary": raw.get("work_summary") or [],
        "employer": raw.get("employer"),
        "employer_url": raw.get("employer_url"),
        "employer_details": raw.get("employer_details") or [],
        "country_notice": raw.get("country_notice"),
        "instructions_and_proof": raw.get("instructions_and_proof") or [],
        "apply_action": raw.get("apply_action"),
        "apply_method": raw.get("apply_method"),
        "apply_id_field": raw.get("apply_id_field"),
        "apply_hidden_fields": raw.get("apply_hidden_fields") or [],
        "apply_submit_label": raw.get("apply_submit_label"),
        "proof_file_fields": raw.get("proof_file_fields") or [],
        "proof_text_fields": raw.get("proof_text_fields") or [],
    }


def normalize_history_row(
    raw: Dict[str, Any], detail: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Normalize one Basic-task history row and its read-only detail popup."""
    task_id = raw.get("task_id")
    title = raw.get("title")
    detail_matches = bool(
        task_id
        and title
        and detail
        and detail.get("task_id") == task_id
        and detail.get("title") == title
    )
    matched_detail = detail if detail_matches else {}
    status = raw.get("status_label")
    return {
        "id": task_id,
        "job_id": matched_detail.get("job_id"),
        "url": None,
        "provider": "microworkers",
        "title": title,
        "proof_preview": raw.get("proof_preview"),
        "submitted_at": matched_detail.get("finished"),
        "submitted_age": raw.get("submitted_age"),
        "status": status,
        "status_icon": raw.get("status_icon"),
        "payment": matched_detail.get("earned") or raw.get("earned"),
        "payment_status": PAYMENT_STATUS_BY_HISTORY_STATUS.get(status),
    }
