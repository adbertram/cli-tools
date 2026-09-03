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
  - "ttv": TTV-branded campaign jobs, whose task-execution flow lives on the
    separate ttv.microworkers.com subdomain. Per explicit scope, this CLI does
    not implement get/apply for the "ttv" provider (listing still reports it).
"""
import re
from typing import Any, Dict, Optional


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
        "apply_id_field": raw.get("apply_id_field"),
        "proof_file_fields": raw.get("proof_file_fields") or [],
        "proof_text_fields": raw.get("proof_text_fields") or [],
    }
