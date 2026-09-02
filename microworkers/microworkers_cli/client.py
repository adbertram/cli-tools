"""Microworkers client using BrowserAutomation from cli_tools_shared."""

from contextlib import contextmanager
from pathlib import Path
from typing import List, Optional

from cli_tools_shared.data_cache import cached
from cli_tools_shared.exceptions import ClientError

from .browser import MicroworkersBrowser
from .config import get_config
from .parsers import normalize_task_detail, normalize_task_row, provider_for_url

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

MAX_LIST_PAGES = 25  # /jobs.php shows 100 rows/page; matches the site's own page cap.


class MicroworkersClient:
    """Client that uses BrowserAutomation to drive Microworkers."""

    def __init__(self):
        self.config = get_config()
        self._browser: Optional[MicroworkersBrowser] = None

    def _get_browser(self) -> MicroworkersBrowser:
        if self._browser is None:
            self._browser = self.config.get_browser()
        return self._browser

    def close(self):
        if self._browser is not None:
            self._browser.close()
            self._browser = None

    @contextmanager
    def _page(self, url: str):
        """Open `url` on a fresh browser session, closing it on exit."""
        browser = self._get_browser()
        try:
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
        return [normalize_task_row(r) for r in rows[:limit]]

    def get_task(self, task_id: str) -> dict:
        """Fetch full detail for one task.

        `task_id` is the task detail URL, as returned in the `id`/`url` field
        of `tasks list` output (see `tasks get`/`tasks apply` help text).
        """
        provider = provider_for_url(task_id)
        if provider == "ttv":
            # TTV-branded campaign jobs execute on the separate
            # ttv.microworkers.com subdomain (the employer/campaign-creation
            # tool), which is out of scope for this CLI. Report this as data
            # rather than an error — the request itself succeeded.
            detail = normalize_task_detail({"url": task_id})
            detail["note"] = (
                "TTV-branded campaign jobs are hosted on ttv.microworkers.com "
                "(the employer/campaign-creation tool), which is out of scope "
                "for this CLI. View and complete this task on the Microworkers "
                "site directly."
            )
            return detail
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
        detail = self.get_task(task_id)
        if detail["provider"] == "ttv":
            raise ClientError(
                "This task is a TTV-branded campaign job hosted on "
                "ttv.microworkers.com, which is out of scope for this CLI "
                "(that subdomain is the employer/campaign-creation tool). "
                "Apply to this task on the Microworkers site directly."
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

        try:
            with self._page(task_id) as page:
                page.evaluate("if (typeof show5 === 'function') { show5(); }")
                for field in detail["proof_text_fields"]:
                    page.fill(f'textarea[name="{field}"]', proof_text or "")
                for field in detail["proof_file_fields"]:
                    page.set_input_files(f'input[type="file"][name="{field}"]', proof_file)
                submit = page.locator('input[type="submit"][name="B1"]')
                if submit.count() != 1 or not submit.first.is_visible():
                    raise ClientError("Could not find the proof-submission button on the task page.")
                submit.first.click()
                page.wait_for_timeout(2000)
        except Exception:
            if debug_dir:
                import json

                debug_path = Path(debug_dir).expanduser()
                debug_path.mkdir(parents=True, exist_ok=True)
                (debug_path / "apply_task_failure.json").write_text(json.dumps(detail, indent=2))
            raise

        result["confirmed"] = True
        result["submitted"] = True
        result["message"] = "Proof submitted."
        return result


_client: Optional[MicroworkersClient] = None


def get_client() -> MicroworkersClient:
    """Get or create the global Microworkers client instance."""
    global _client
    if _client is None:
        _client = MicroworkersClient()
    return _client
