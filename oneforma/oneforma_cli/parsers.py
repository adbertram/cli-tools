"""Parse job data returned by OneForma's internal contributor API.

OneForma's contributor site is a React SPA that never server-renders job rows:
the listing at /contributor/jobs/apply is painted from JSON. `client.py`
reproduces the site's own calls from inside the authenticated page, and the
raw JSON lands here.

Endpoints and field names were captured live 2026-09-02 from an authenticated
session (request bodies copied from the site's own XHRs):

  POST /api/resource/job/v1/list-job   body {"page": <int>, "size": <int>}
    -> {"success": true, "data": {"records": [ ... ]}}
  POST /api/resource/job/v1/get-detail body {"jobId": "<id>"}
    -> {"success": true, "data": { ... }}

A listing record carries: jobId, projectId, postTitle, jobTypeValue,
projectCategoryValue, deadline, jobPublishDate, jobStatus, jobApplyStatus,
rate, rateUnitValue, rateCurrencySymbol, rateMin, rateMax, projectName,
resourceTypeValue, platform, localeValue, applicantCount, daysLeft,
targetCountryNames, inviteFlag, newFlag, fillingFastFlag.

A detail response carries: requestId, projectId, jobPostTitle, projectName,
jobCategoryValue, projectCategoryValue, hiringDeadline, jobPostDate, daysLeft,
postedDays, jdFileId, and jobDescription.jobSectionList (a list of
{sectionSubtitle, sectionContent} HTML blocks).

`url`: OneForma has no per-job route. Job cards open a modal over
/contributor/jobs/apply and the SPA pushes no history entry (confirmed by
searching the deployed same-origin bundles for a jobId-bearing route — there
is none), so every row points at the listing page rather than at an invented
per-job URL.

Anything the API does not return stays ``None``.
"""

from typing import Any, Dict, List, Optional

JOBS_LIST_URL = "https://my.oneforma.com/contributor/jobs/apply"


def normalize_job_row(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize one record from `/api/resource/job/v1/list-job`."""
    return {
        "id": _as_str(raw.get("jobId")),
        "url": JOBS_LIST_URL,
        "title": raw.get("postTitle"),
        "project_id": _as_str(raw.get("projectId")),
        "project_name": raw.get("projectName"),
        "job_type": raw.get("jobTypeValue"),
        "project_category": raw.get("projectCategoryValue"),
        "rate": raw.get("rate"),
        "rate_min": raw.get("rateMin"),
        "rate_max": raw.get("rateMax"),
        "rate_unit": raw.get("rateUnitValue"),
        "rate_currency_symbol": raw.get("rateCurrencySymbol"),
        "deadline": raw.get("deadline"),
        "days_left": raw.get("daysLeft"),
        "publish_date": raw.get("jobPublishDate"),
        "applicant_count": raw.get("applicantCount"),
        "apply_status": raw.get("jobApplyStatus"),
        "target_countries": raw.get("targetCountryNames") or [],
        "locale": raw.get("localeValue"),
        "platform": raw.get("platform"),
        "invited": raw.get("inviteFlag"),
    }


def normalize_job_rows(records: Any) -> List[Dict[str, Any]]:
    """Normalize a `data.records` list, rejecting anything else."""
    if records is None:
        return []
    if not isinstance(records, list):
        raise TypeError(f"Expected a list of job records, got {type(records).__name__}")
    return [normalize_job_row(record) for record in records]


def normalize_job_detail(raw: Dict[str, Any], job_id: str) -> Dict[str, Any]:
    """Normalize a `/api/resource/job/v1/get-detail` response body.

    The detail payload identifies the job by `requestId`/`projectId` and does
    not echo `jobId`, so the id used to request it is carried through rather
    than derived from a field the API does not return.
    """
    description = raw.get("jobDescription") or {}
    sections = description.get("jobSectionList") or []
    return {
        "id": _as_str(raw.get("jobId")) or _as_str(job_id),
        "url": JOBS_LIST_URL,
        "title": raw.get("jobPostTitle"),
        "project_id": _as_str(raw.get("projectId")),
        "project_name": raw.get("projectName"),
        "request_id": _as_str(raw.get("requestId")),
        "job_type": raw.get("jobCategoryValue"),
        "project_category": raw.get("projectCategoryValue"),
        "deadline": raw.get("hiringDeadline"),
        "days_left": raw.get("daysLeft"),
        "publish_date": raw.get("jobPostDate"),
        "posted_days": raw.get("postedDays"),
        "platform": raw.get("platform"),
        "sections": [
            {
                "subtitle": section.get("sectionSubtitle"),
                "content": section.get("sectionContent"),
            }
            for section in sections
        ],
    }


def _as_str(value: Any) -> Optional[str]:
    """OneForma returns ids as strings, but never assume — normalize without
    inventing a value for a missing one."""
    if value is None or value == "":
        return None
    return str(value)
