"""Microworkers client using BrowserAutomation from cli_tools_shared."""

import re
import time
from contextlib import contextmanager
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlsplit

from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

from .browser import MicroworkersBrowser
from .config import get_config
from .parsers import (
    normalize_history_row,
    normalize_task_detail,
    normalize_task_row,
    parse_apply_target,
    parse_ttv_detail_target,
    provider_for_url,
)
from .work import WorkArtifacts, select_work_adapter, task_work_timeout

# Validated against the live /jobs.php DOM on 2026-09-02 (authenticated session).
LIST_JS = """
() => Array.from(document.querySelectorAll('.jobslist')).map(row => {
  const link = row.querySelector('.jobname a');
  const text = (sel) => {
    const el = row.querySelector(sel);
    return el ? el.innerText.trim() : null;
  };
  return {
    campaign_id: row.id.replace(/^campaign/, ''),
    title: link ? link.innerText.trim() : null,
    url: link ? link.href : null,
    payment: text('.jobpayment'),
    success_rate: text('.jobsuccess'),
    ttr_days: text('.jobttr'),
    ttf_minutes: text('.jobstatus'),
    done: text('.jobdone'),
  };
})
"""

# Validated against the live authenticated Basic history page (/worker.php)
# and its read-only task-detail endpoint on 2026-09-05. Status text is bound
# to each row by matching its icon to the legend rendered on the same page.
HISTORY_JS = r"""
() => {
  const clean = (value) => value == null ? null : value.replace(/\s+/g, ' ').trim() || null;
  const iconName = (element) => {
    const svg = element?.querySelector('svg[data-icon]');
    if (svg) return svg.getAttribute('data-icon');
    const icon = element?.querySelector('i');
    const match = icon?.className.match(/(?:^|\s)fa-([a-z-]+)(?:\s|$)/);
    return match ? match[1] : null;
  };
  const legend = {};
  document.querySelectorAll('.workerarearight p').forEach(item => {
    const icon = iconName(item);
    const label = clean(item.innerText);
    if (icon && label) legend[icon] = label;
  });
  const rows = Array.from(document.querySelectorAll('.hmworkerarea .hmworkerlist')).map(row => {
    const statusElement = row.querySelector('.hmworkerstatus p');
    const statusIcon = iconName(statusElement);
    const viewLink = Array.from(row.querySelectorAll('.workerheaderdetails a[onclick]')).find(link =>
      /^divOn5\('[A-Za-z0-9_-]+'\);\s*return false;$/.test(link.getAttribute('onclick') || '')
    );
    const viewMatch = viewLink?.getAttribute('onclick')?.match(
      /^divOn5\('([A-Za-z0-9_-]+)'\);\s*return false;$/
    );
    return {
      task_id: viewMatch ? viewMatch[1] : null,
      title: clean(row.querySelector('.workerheaderjobname')?.innerText),
      proof_preview: clean(row.querySelector('.workerheaderproof')?.innerText),
      submitted_age: clean(statusElement?.innerText),
      status_icon: statusIcon,
      status_label: statusIcon ? legend[statusIcon] || null : null,
      earned: clean(row.querySelector('.workerheaderearn')?.innerText),
    };
  });
  const next = document.querySelector(
    'nav.pagination a.pagination__item--next-page:not(.pagination__item--disabled)'
  );
  return {rows, next_url: next ? next.href : null};
}
"""

HISTORY_DETAIL_JS = """
() => {
  const clean = (value) => value == null ? null : value.replace(/\\s+/g, ' ').trim() || null;
  const fields = {};
  document.querySelectorAll('.popuplist').forEach(item => {
    const name = clean(item.querySelector('.popuplistleft')?.innerText);
    const value = clean(item.querySelector('.popuplistright')?.innerText);
    if (name) fields[name] = value;
  });
  return {
    task_id: fields['Task ID'] || null,
    job_id: fields['Job ID'] || null,
    title: fields['Job name'] || null,
    earned: fields['Earned'] || null,
    finished: fields['Finished'] || null,
    status_text: clean(document.querySelector('.notratedtaskbox')?.innerText),
  };
}
"""

# Validated against live jobs_details.php and hm_jobs_details.php detail pages
# on 2026-09-02 (authenticated session). Both worker job systems share this
# exact class structure.
DETAIL_JS = """
() => {
  const text = (sel) => {
    const el = document.querySelector(sel);
    return el ? el.innerText.trim() : null;
  };
  const left = document.querySelector('.jobdetailsnoteleft');
  const right = document.querySelector('.jobdetailsnoteright');
  const leftParas = left ? Array.from(left.querySelectorAll('p')).map(p => p.innerText.trim()) : [];
  const rightParas = right ? Array.from(right.querySelectorAll('p')).map(p => p.innerText.trim()) : [];
  const box = document.querySelector('.jobarealeft .jobdetailsbox');
  const boxParas = box ? Array.from(box.querySelectorAll('p')).map(p => p.innerText.trim()) : [];
  const countryBlock = document.querySelector('.countrychoise');
  const employerLink = right ? right.querySelector('a[href*="userinfo.php"]') : null;
  const form = document.querySelector('form[action*="_i_did_it.php"]');
  const fileInputs = form ? Array.from(form.querySelectorAll('input[type="file"]')).map(i => i.name) : [];
  const textFields = form ? Array.from(form.querySelectorAll('textarea')).map(t => t.name) : [];
  const hiddenId = form ? form.querySelector('input[name="Id"]') : null;
  return {
    title: text('.jobarealeft > h1'),
    work_summary: leftParas,
    employer: employerLink ? employerLink.innerText.trim() : null,
    employer_url: employerLink ? employerLink.href : null,
    employer_details: rightParas,
    country_notice: countryBlock ? countryBlock.innerText.trim() : null,
    instructions_and_proof: boxParas,
    apply_action: form ? new URL(form.getAttribute('action'), location.href).href : null,
    apply_id_field: hiddenId ? hiddenId.value : null,
    proof_file_fields: fileInputs,
    proof_text_fields: textFields,
  };
}
"""

# Validated against six live authenticated TTV task pages on 2026-09-06.
# This extractor reads the pre-accept page only. It never clicks or submits the
# allocation form and does not load the embedded interactive task preview.
TTV_DETAIL_JS = """
() => {
  const clean = (value) => value == null ? null : value.replace(/\\s+/g, ' ').trim() || null;
  const root = document.querySelector('.vn-bootstrap');
  const heading = root?.querySelector('h4 b');
  const summary = root?.querySelector('.col-sm-8 > .row > .col-sm-5');
  const employerBlock = root?.querySelector('.col-sm-8 > .row > .col-sm-7');
  const employerLink = employerBlock?.querySelector('a[href*="userinfo.php"]');
  const instructionPanel = root?.querySelector('.panel-body.ttv-task-data');
  let instruction = null;
  if (instructionPanel) {
    const copy = instructionPanel.cloneNode(true);
    copy.querySelectorAll('.panel').forEach(element => element.remove());
    instruction = clean(copy.innerText);
  }
  const important = Array.from(root?.querySelectorAll('.row') || [])
    .map(element => clean(element.innerText))
    .find(value => value?.startsWith('Important:')) || null;
  const country = root?.querySelector('.countrychoise, .countrychoice');
  const form = root?.querySelector('form[action="/dotask/allocateposition"]');
  const hiddenFields = form ? Array.from(form.querySelectorAll('input[type="hidden"]')).map(input => ({
    name: input.name || null,
    value: input.value || null,
  })) : [];
  const submit = form?.querySelector('button[type="submit"], input[type="submit"]');
  const employerDetails = employerBlock ? Array.from(employerBlock.children)
    .map(element => clean(element.innerText))
    .filter(value => value && (
      value.startsWith('Max positions per worker:') ||
      value.startsWith('You already submitted:') ||
      value.startsWith('Tasks will be rated within')
    )) : [];
  return {
    title: clean(heading?.innerText),
    work_summary: summary ? summary.innerText.split('\\n').map(clean).filter(Boolean) : [],
    employer: clean(employerLink?.innerText),
    employer_url: employerLink?.href || null,
    employer_details: employerDetails,
    country_notice: clean(country?.innerText),
    instructions_and_proof: [instruction, important].filter(Boolean),
    apply_action: form ? new URL(form.getAttribute('action'), location.href).href : null,
    apply_method: form ? (form.getAttribute('method') || 'get').toLowerCase() : null,
    apply_id_field: hiddenFields.find(field => field.name === 'CampaignId')?.value || null,
    apply_hidden_fields: hiddenFields,
    apply_submit_label: clean(submit?.innerText || submit?.value),
    proof_file_fields: [],
    proof_text_fields: [],
  };
}
"""

TTV_ALLOCATION_STATE_JS = """
(args) => {
  const allocationForms = Array.from(
    document.querySelectorAll('form[action="/dotask/allocateposition"]')
  );
  const taskForms = Array.from(document.querySelectorAll('form')).filter(form => {
    if (form.matches('form[action="/dotask/allocateposition"]')) return false;
    const ids = Array.from(form.querySelectorAll('input[type="hidden"][name="CampaignId"]'));
    return ids.length === 1 && ids[0].value === args.campaign_id;
  });
  return {
    url: location.href,
    allocation_form_count: allocationForms.length,
    task_form_count: taskForms.length,
    task_form_action: taskForms.length === 1
      ? new URL(taskForms[0].getAttribute('action'), location.href).href
      : null,
    instruction_panel_count: document.querySelectorAll('.ttv-task-data').length,
  };
}
"""

# Validated against live Basic and Hire Group task pages on 2026-09-05.
# Basic tasks already submitted redirect to jobs_user_already_took.php, whose
# live worker-page message is also captured below.
APPLY_STATE_JS = """
() => {
  const forms = Array.from(document.querySelectorAll('form[action*="_i_did_it.php"]'));
  const form = forms.length === 1 ? forms[0] : null;
  const hiddenIds = form ? Array.from(form.querySelectorAll('input[name="Id"]')) : [];
  const submits = form ? Array.from(form.querySelectorAll('input[type="submit"][name="B1"]')) : [];
  const bodyText = document.body.innerText.toLowerCase();
  return {
    url: location.href,
    form_count: forms.length,
    action: form ? new URL(form.getAttribute('action'), location.href).href : null,
    method: form ? (form.getAttribute('method') || 'get').toLowerCase() : null,
    hidden_id_count: hiddenIds.length,
    hidden_id: hiddenIds.length === 1 ? hiddenIds[0].value : null,
    submit_count: submits.length,
    already_submitted: [
      'worker already submitted this task.',
      'sorry but you already submitted this task.',
    ].some(marker => bodyText.includes(marker)),
  };
}
"""

ALREADY_SUBMITTED_REDIRECTS = {
    "microworkers": "https://www.microworkers.com/jobs_user_already_took.php",
}


def _is_authoritative_submitted_state(
    state: dict, requested_provider: str, requested_id: str
) -> bool:
    """Bind an already-submitted marker to the requested task navigation."""
    if not state.get("already_submitted"):
        return False
    try:
        current_provider, current_id, _ = parse_apply_target(state["url"])
    except (KeyError, TypeError, ValueError):
        return state.get("url") == ALREADY_SUBMITTED_REDIRECTS.get(requested_provider)
    return current_provider == requested_provider and current_id == requested_id


MAX_LIST_PAGES = 25  # /jobs.php shows 100 rows/page; matches the site's own page cap.

# Seconds to wait between consecutive /jobs.php page loads. Microworkers'
# bot detection watches listing cadence, not volume: fetching the full
# 2500-row queue back to back earned this account a 1-day
# "Auto-refresh / Bot" ban on both 2026-09-05 and 2026-09-06. Spacing the
# page loads keeps a full listing walk inside a human-looking rhythm.
LIST_PAGE_DELAY_SECONDS = 4.0


class MicroworkersClient:
    """Client that uses BrowserAutomation to drive Microworkers."""

    def __init__(self):
        self.config = get_config()
        self._browser: Optional[MicroworkersBrowser] = None
        self._refresh_checked = False

    def _get_browser(self) -> MicroworkersBrowser:
        if self._browser is None:
            self._browser = self.config.get_browser()
        return self._browser

    def _ensure_fresh_session(self, browser: MicroworkersBrowser) -> None:
        """Refresh the saved browser session once per client instance.

        Delegates to the shared engine's ``ensure_fresh_session()`` — headless
        (no visible browser), no stdin reads, throttled to one refresh attempt
        per ``AUTH_REFRESH_THROTTLE_SECONDS`` per process. A session that
        cannot be refreshed automatically fails the command with the
        structured reason instead of running against an expired session.
        """
        if self._refresh_checked:
            return
        self._refresh_checked = True
        result = browser.ensure_fresh_session()
        if result.authenticated:
            return
        if result.needs_human:
            raise ClientError(
                "Microworkers session refresh needs a human: "
                f"{result.reason or 'a CAPTCHA or challenge wall'}. Re-run "
                "'microworkers auth login' from an interactive terminal and "
                "complete the challenge in the CLI-owned browser profile."
            )
        raise ClientError(
            "Microworkers session is not authenticated and could not be refreshed "
            f"automatically: {result.reason or 'unknown reason'}. Re-run "
            "'microworkers auth login' to log in."
        )

    def close(self):
        if self._browser is not None:
            self._browser.close()
            self._browser = None

    @contextmanager
    def _page(self, url: str):
        """Open `url` on a fresh browser session, closing it on exit.

        Before the first page of this client, the shared engine's headless
        session refresh runs (see :meth:`_ensure_fresh_session`): a stale or
        expired saved session is re-authenticated automatically, and a refresh
        that needs a human fails here with the structured reason instead of
        running against a dead session or opening a visible browser.
        """
        browser = self._get_browser()
        try:
            self._ensure_fresh_session(browser)
            page = browser.get_page(url)
            page.wait_for_timeout(1500)
            yield page
        finally:
            browser.close()

    @cached
    def list_tasks(self, limit: int = 100) -> List[dict]:
        """List available worker jobs from /jobs.php (paginated, 100/page)."""
        base_url = self.config.base_url
        rows: List[dict] = []
        page_num = 1
        while len(rows) < limit and page_num <= MAX_LIST_PAGES:
            with self._page(f"{base_url}/jobs.php?page={page_num}") as page:
                page_rows = page.evaluate(LIST_JS)
            if not page_rows:
                break
            rows.extend(page_rows)
            page_num += 1
            if len(rows) < limit and page_num <= MAX_LIST_PAGES:
                time.sleep(LIST_PAGE_DELAY_SECONDS)
        # /jobs.php pages overlap at their boundaries -- campaigns posted
        # while the pages are fetched move the split point, so the same
        # campaign appears on two consecutive pages (verified live 2026-09-04:
        # 96 exact duplicates in a 2500-row listing). One row per campaign is
        # the site's own identity for a job, so exact duplicates (same url)
        # are dropped, first occurrence kept.
        unique: List[dict] = []
        seen: set = set()
        for row in rows[:limit]:
            key = row.get("url") or row.get("id")
            if key is not None and key in seen:
                continue
            if key is not None:
                seen.add(key)
            unique.append(row)
        return [normalize_task_row(r) for r in unique]

    def list_history(self, limit: int = 100) -> List[dict]:
        """List Basic-task submission history with authoritative row state."""
        next_url: Optional[str] = f"{self.config.base_url}/worker.php"
        rows: List[dict] = []
        pages = 0
        while next_url and len(rows) < limit and pages < MAX_LIST_PAGES:
            with self._page(next_url) as page:
                payload = page.evaluate(HISTORY_JS)
            if not isinstance(payload, dict) or not isinstance(payload.get("rows"), list):
                raise ClientError("Microworkers history page returned an unexpected DOM shape.")
            for raw in payload["rows"]:
                if len(rows) >= limit:
                    break
                detail = None
                task_id = raw.get("task_id")
                if task_id:
                    detail_url = (
                        f"{self.config.base_url}/worker_tasks_details.php?Id={task_id}"
                    )
                    with self._page(detail_url) as detail_page:
                        detail = detail_page.evaluate(HISTORY_DETAIL_JS)
                rows.append(normalize_history_row(raw, detail))
            next_url = payload.get("next_url")
            if next_url:
                try:
                    parsed = urlsplit(next_url)
                    port = parsed.port
                except ValueError as exc:
                    raise ClientError(
                        "Microworkers history pagination returned an unsafe URL."
                    ) from exc
                if (
                    parsed.scheme != "https"
                    or parsed.hostname != "www.microworkers.com"
                    or parsed.username is not None
                    or parsed.password is not None
                    or port is not None
                    or parsed.path != "/worker.php"
                    or parsed.fragment
                ):
                    raise ClientError("Microworkers history pagination returned an unsafe URL.")
            pages += 1
        return rows

    def get_task(self, task_id: str) -> dict:
        """Fetch full detail for one task.

        `task_id` is the task detail URL, as returned in the `id`/`url` field
        of `tasks list` output (see `tasks get`/`tasks apply` help text).
        """
        provider = provider_for_url(task_id)
        if provider == "ttv":
            try:
                requested_id = parse_ttv_detail_target(task_id)
            except ValueError as exc:
                raise ClientError(f"Invalid Microworkers TTV task URL: {exc}") from exc
            with self._page(task_id) as page:
                try:
                    current_id = parse_ttv_detail_target(page.url)
                except ValueError as exc:
                    raise ClientError(
                        "TTV task detail did not remain on an exact task-detail URL."
                    ) from exc
                if current_id != requested_id:
                    raise ClientError("TTV task detail identity does not match the requested task.")
                if not page.locator(".vn-bootstrap .ttv-task-data").first.is_visible(
                    timeout=3000
                ):
                    raise ClientError(f"Task not found or no longer available: {task_id}")
                detail = page.evaluate(TTV_DETAIL_JS)
                detail["url"] = page.url
            normalized = normalize_task_detail(detail)
            if (
                normalized["apply_action"]
                != "https://ttv.microworkers.com/dotask/allocateposition"
                or normalized["apply_method"] != "post"
                or normalized["apply_id_field"] != requested_id
            ):
                raise ClientError("TTV task detail returned unexpected apply form metadata.")
            return normalized
        if provider not in ("microworkers", "hire_group"):
            raise ClientError(f"Unrecognized task URL/provider: {task_id}")

        with self._page(task_id) as page:
            if not page.locator(".jobarealeft").first.is_visible(timeout=3000):
                raise ClientError(f"Task not found or no longer available: {task_id}")
            detail = page.evaluate(DETAIL_JS)
            detail["url"] = page.url
        return normalize_task_detail(detail)

    def apply_task(
        self,
        task_id: str,
        proof_text: Optional[str] = None,
        proof_file: Optional[str] = None,
        confirm: bool = False,
        log=None,
        debug_dir=None,
    ) -> dict:
        """Apply to (submit proof for) a task. Dry-run unless `confirm=True`.

        Microworkers' own UI does not separate "accept" from "submit proof" —
        accepting a job means submitting the required proof via the job's
        `_i_did_it.php` form. Dry-run mode fetches the live task detail (a
        read) to report exactly what would be submitted, and never posts.
        """
        if provider_for_url(task_id) == "ttv":
            return self._apply_ttv_task(
                task_id,
                proof_text=proof_text,
                proof_file=proof_file,
                confirm=confirm,
                debug_dir=debug_dir,
            )
        try:
            requested_provider, requested_id, expected_action = parse_apply_target(task_id)
        except ValueError as exc:
            raise ClientError(f"Invalid Microworkers task URL: {exc}") from exc

        mutation_attempted = False
        try:
            with self._page(task_id) as page:
                preflight = page.evaluate(APPLY_STATE_JS)
                if _is_authoritative_submitted_state(
                    preflight, requested_provider, requested_id
                ):
                    return {
                        "id": task_id,
                        "title": None,
                        "provider": requested_provider,
                        "apply_action": expected_action,
                        "proof_text_fields": [],
                        "proof_file_fields": [],
                        "proof_text_provided": bool(proof_text),
                        "proof_file_provided": bool(proof_file),
                        "confirmed": confirm,
                        "submitted": True,
                        "state": "already_submitted",
                        "mutation_attempted": False,
                        "post_verified": True,
                        "message": "Task was already submitted; no new submission was made.",
                    }
                try:
                    current_provider, current_id, _ = parse_apply_target(preflight["url"])
                except (KeyError, TypeError, ValueError) as exc:
                    raise ClientError(
                        "Apply preflight did not remain on the exact requested worker task; "
                        "no submission was made."
                    ) from exc
                if current_provider != requested_provider or current_id != requested_id:
                    raise ClientError(
                        "Apply preflight task identity does not match the requested task; "
                        "no submission was made."
                    )
                expected_preflight = {
                    "form_count": 1,
                    "action": expected_action,
                    "method": "post",
                    "hidden_id_count": 1,
                    "hidden_id": requested_id,
                    "submit_count": 1,
                }
                mismatches = [
                    key
                    for key, expected in expected_preflight.items()
                    if preflight.get(key) != expected
                ]
                if mismatches:
                    raise ClientError(
                        "Apply preflight failed for "
                        f"{', '.join(mismatches)}; no submission was made."
                    )

                detail_raw = page.evaluate(DETAIL_JS)
                detail_raw["url"] = preflight["url"]
                detail = normalize_task_detail(detail_raw)
                if detail["provider"] != requested_provider:
                    raise ClientError(
                        "Task detail provider does not match the requested task URL; "
                        "no submission was made."
                    )
                result = {
                    "id": task_id,
                    "title": detail["title"],
                    "provider": detail["provider"],
                    "apply_action": detail["apply_action"],
                    "proof_text_fields": detail["proof_text_fields"],
                    "proof_file_fields": detail["proof_file_fields"],
                    "proof_text_provided": bool(proof_text),
                    "proof_file_provided": bool(proof_file),
                    "confirmed": False,
                    "submitted": False,
                    "state": "ready",
                    "mutation_attempted": False,
                    "post_verified": False,
                    "message": "Dry run: no submission was made. Pass --confirm to submit.",
                }
                if not confirm:
                    return result
                if detail["proof_file_fields"] and not proof_file:
                    raise ClientError(
                        "This task requires uploading a proof file "
                        f"({', '.join(detail['proof_file_fields'])}), but no --proof-file "
                        "was provided."
                    )
                if proof_file and not Path(proof_file).expanduser().is_file():
                    raise ClientError(f"proof_file not found: {proof_file}")
                if log:
                    log(f"Submitting proof for task: {detail['title']}")

                page.evaluate("if (typeof show5 === 'function') { show5(); }")
                for field in detail["proof_text_fields"]:
                    page.fill(f'textarea[name="{field}"]', proof_text or "")
                for field in detail["proof_file_fields"]:
                    page.set_input_files(f'input[type="file"][name="{field}"]', proof_file)
                submit = page.locator('input[type="submit"][name="B1"]')
                if submit.count() != 1 or not submit.first.is_visible():
                    raise ClientError("Could not find the proof-submission button on the task page.")
                mutation_attempted = True
                submit.first.click()
                page.wait_for_timeout(500)
                if not page.wait_for_network_idle(timeout=15.0, idle_ms=500):
                    raise ClientError(
                        "Submission outcome is ambiguous: submit was clicked exactly once, "
                        "but the site did not become idle for verification. Do not retry "
                        "automatically; inspect the exact task on Microworkers first."
                    )
                page.goto(task_id)
                page.wait_for_timeout(1500)
                postflight = page.evaluate(APPLY_STATE_JS)
                if not _is_authoritative_submitted_state(
                    postflight, requested_provider, requested_id
                ):
                    raise ClientError(
                        "Submission outcome is ambiguous: submit was clicked exactly once, "
                        "but authoritative re-read did not show an already-submitted state. "
                        "Do not retry automatically; inspect the exact task on Microworkers "
                        "first."
                    )
        except Exception as exc:
            if debug_dir:
                import json

                debug_path = Path(debug_dir).expanduser()
                debug_path.mkdir(parents=True, exist_ok=True)
                debug_record = {
                    "id": task_id,
                    "provider": requested_provider,
                    "state": "unknown_after_submit" if mutation_attempted else "preflight_failed",
                    "mutation_attempted": mutation_attempted,
                    "post_verified": False,
                    "error": str(exc),
                }
                (debug_path / "apply_task_failure.json").write_text(
                    json.dumps(debug_record, indent=2)
                )
            if mutation_attempted and "Submission outcome is ambiguous" not in str(exc):
                raise ClientError(
                    "Submission outcome is ambiguous: submit was clicked exactly once, "
                    f"then verification failed ({exc}). Do not retry automatically; inspect "
                    "the exact task on Microworkers first."
                ) from exc
            raise

        result["confirmed"] = True
        result["submitted"] = True
        result["state"] = "submitted"
        result["mutation_attempted"] = True
        result["post_verified"] = True
        result["message"] = "Proof submitted and verified by authoritative task re-read."
        return result

    def _apply_ttv_task(
        self,
        task_id: str,
        *,
        proof_text: Optional[str],
        proof_file: Optional[str],
        confirm: bool,
        debug_dir=None,
    ) -> dict:
        """Preflight or allocate one exact TTV task; never submit task proof."""
        if proof_text or proof_file:
            raise ClientError(
                "TTV tasks apply only accepts/starts the task; --proof-text and "
                "--proof-file are unsupported and no action was performed."
            )
        try:
            requested_id = parse_ttv_detail_target(task_id)
        except ValueError as exc:
            raise ClientError(f"Invalid Microworkers TTV task URL: {exc}") from exc

        mutation_attempted = False
        try:
            with self._page(task_id) as page:
                try:
                    current_id = parse_ttv_detail_target(page.url)
                except ValueError as exc:
                    raise ClientError(
                        "TTV allocation preflight did not remain on the exact requested task."
                    ) from exc
                if current_id != requested_id:
                    raise ClientError(
                        "TTV allocation preflight identity does not match the requested task."
                    )
                detail_raw = page.evaluate(TTV_DETAIL_JS)
                detail_raw["url"] = page.url
                detail = normalize_task_detail(detail_raw)
                expected_fields = [{"name": "CampaignId", "value": requested_id}]
                if (
                    detail["apply_action"]
                    != "https://ttv.microworkers.com/dotask/allocateposition"
                    or detail["apply_method"] != "post"
                    or detail["apply_id_field"] != requested_id
                    or detail["apply_hidden_fields"] != expected_fields
                    or detail["apply_submit_label"] != "Accept and Start"
                ):
                    raise ClientError(
                        "TTV allocation preflight returned unexpected task/form identity; "
                        "no allocation was attempted."
                    )
                result = {
                    "id": task_id,
                    "title": detail["title"],
                    "provider": "ttv",
                    "apply_action": detail["apply_action"],
                    "apply_method": detail["apply_method"],
                    "apply_hidden_fields": detail["apply_hidden_fields"],
                    "apply_submit_label": detail["apply_submit_label"],
                    "proof_text_fields": [],
                    "proof_file_fields": [],
                    "proof_text_provided": False,
                    "proof_file_provided": False,
                    "confirmed": False,
                    "allocated": False,
                    "submitted": False,
                    "state": "ready_to_allocate",
                    "mutation_attempted": False,
                    "post_verified": False,
                    "message": (
                        "Dry run: TTV task is ready to allocate; no accept/start action "
                        "or proof submission was performed. Pass --confirm only after the "
                        "exact task is approved."
                    ),
                }
                if not confirm:
                    return result

                submit = page.locator(
                    'form[action="/dotask/allocateposition"] button[type="submit"]'
                )
                if submit.count() != 1 or not submit.first.is_visible():
                    raise ClientError(
                        "TTV allocation preflight did not find one visible Accept and Start "
                        "button; no allocation was attempted."
                    )
                mutation_attempted = True
                submit.first.click()
                page.wait_for_timeout(500)
                if not page.wait_for_network_idle(timeout=15.0, idle_ms=500):
                    raise ClientError(
                        "TTV allocation outcome is ambiguous: Accept and Start was clicked "
                        "exactly once, but the site did not become idle. Do not retry "
                        "automatically; inspect the exact TTV task first."
                    )
                postflight = page.evaluate(
                    TTV_ALLOCATION_STATE_JS, {"campaign_id": requested_id}
                )
                try:
                    parsed_post = urlsplit(postflight["url"])
                    port = parsed_post.port
                except (KeyError, TypeError, ValueError) as exc:
                    raise ClientError(
                        "TTV allocation outcome is ambiguous: post-click URL was unsafe. "
                        "Do not retry automatically."
                    ) from exc
                post_action = postflight.get("task_form_action")
                try:
                    parsed_action = urlsplit(post_action)
                    action_port = parsed_action.port
                except (TypeError, ValueError) as exc:
                    raise ClientError(
                        "TTV allocation outcome is ambiguous: post-click task form was unsafe. "
                        "Do not retry automatically."
                    ) from exc
                postflight_valid = (
                    parsed_post.scheme == "https"
                    and parsed_post.hostname == "ttv.microworkers.com"
                    and parsed_post.username is None
                    and parsed_post.password is None
                    and port is None
                    and parsed_action.scheme == "https"
                    and parsed_action.hostname == "ttv.microworkers.com"
                    and parsed_action.username is None
                    and parsed_action.password is None
                    and action_port is None
                    and postflight.get("allocation_form_count") == 0
                    and postflight.get("task_form_count") == 1
                    and postflight.get("instruction_panel_count") == 1
                )
                if not postflight_valid:
                    raise ClientError(
                        "TTV allocation outcome is ambiguous: authoritative post-click DOM "
                        "did not show one campaign-bound task form with the allocation form "
                        "gone. Do not retry automatically; inspect the exact TTV task first."
                    )
        except Exception as exc:
            if mutation_attempted and "outcome is ambiguous" not in str(exc):
                raise ClientError(
                    "TTV allocation outcome is ambiguous: Accept and Start was clicked "
                    f"exactly once, then verification failed ({exc}). Do not retry "
                    "automatically; inspect the exact TTV task first."
                ) from exc
            raise

        result.update(
            confirmed=True,
            allocated=True,
            state="allocated",
            mutation_attempted=True,
            post_verified=True,
            message=(
                "TTV task allocation was verified. Task proof has not been submitted; "
                "complete tasks work before any proof submission."
            ),
        )
        return result

    @task_work_timeout()
    def work_task(self, task_id: str, artifact_dir: str) -> dict:
        """Complete a supported task's read-only evidence workflow.

        This method never touches the Microworkers submission form. Pattern
        adapters visit only instruction-specified public pages, collect proof,
        and write evidence artifacts for later review/submission.
        """
        if provider_for_url(task_id) == "ttv":
            try:
                requested_id = parse_ttv_detail_target(task_id)
            except ValueError as exc:
                raise ClientError(f"Invalid Microworkers TTV task URL: {exc}") from exc
            artifacts = WorkArtifacts(Path(artifact_dir).expanduser() / requested_id)
            with self._page(task_id) as page:
                try:
                    current_id = parse_ttv_detail_target(page.url)
                except ValueError as exc:
                    raise ClientError(
                        "TTV task work did not remain on the exact requested task URL."
                    ) from exc
                if current_id != requested_id:
                    raise ClientError(
                        "TTV task work page identity does not match the requested task."
                    )
                detail_raw = page.evaluate(TTV_DETAIL_JS)
                detail_raw["url"] = page.url
                detail = normalize_task_detail(detail_raw)
                artifacts.json("task-detail", detail)
            if detail["apply_action"]:
                raise ClientError(
                    "TTV task work requires allocation first. This read-only run saved the "
                    "visible instructions but did not click Accept and Start. After the exact "
                    "task is approved, run 'microworkers tasks apply <TASK_URL> --confirm' "
                    "once, then rerun tasks work against the allocated task URL."
                )
            raise ClientError(
                "TTV post-allocation work DOM has not been validated for this task state; "
                "no task work or proof submission was attempted."
            )
        try:
            requested_provider, requested_id, _ = parse_apply_target(task_id)
        except ValueError as exc:
            raise ClientError(f"Invalid Microworkers task URL: {exc}") from exc
        artifact_slug = re.sub(r"[^A-Za-z0-9_-]", "_", requested_id)
        artifacts = WorkArtifacts(Path(artifact_dir).expanduser() / artifact_slug)

        with self._page(task_id) as page:
            try:
                current_provider, current_id, _ = parse_apply_target(page.url)
            except ValueError as exc:
                raise ClientError("Task work did not remain on the exact requested task URL.") from exc
            if current_provider != requested_provider or current_id != requested_id:
                raise ClientError("Task work page identity does not match the requested task.")
            if not page.locator(".jobarealeft").first.is_visible(timeout=3000):
                raise ClientError(f"Task not found or no longer available: {task_id}")
            detail_raw = page.evaluate(DETAIL_JS)
            detail_raw["url"] = page.url
            detail = normalize_task_detail(detail_raw)
            artifacts.json("task-detail", detail)
            adapter = select_work_adapter(detail)
            worked = adapter.run(page, detail, artifacts)

        result = {
            "id": task_id,
            "title": detail["title"],
            "provider": requested_provider,
            "status": "completed",
            "submitted": False,
            "task_mutation_attempted": False,
            **worked,
        }
        result_path = str(artifacts.directory / "result.json")
        result["artifacts"] = [*artifacts.paths, result_path]
        artifacts.json("result", result)
        return result


_client: Optional[MicroworkersClient] = None


def get_client() -> MicroworkersClient:
    """Get or create the global Microworkers client instance."""
    global _client
    if _client is None:
        _client = MicroworkersClient()
    return _client
