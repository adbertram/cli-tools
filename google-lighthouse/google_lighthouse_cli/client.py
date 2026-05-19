"""Google Lighthouse wrapper client."""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from cli_tools_shared.filters import apply_filters, validate_filters

from .config import get_config
from .models import AuditArtifacts, AuditMetrics, AuditScores, AuditSummary, create_audit_summary


class ClientError(Exception):
    """Raised when the Lighthouse wrapper cannot complete a command."""


def utc_timestamp() -> str:
    """Return the current UTC timestamp in ISO-8601 Zulu format."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def new_audit_id(url: str) -> str:
    """Create a deterministic-looking audit ID from current time and URL host."""

    parsed = urlparse(url)
    if parsed.netloc == "":
        raise ClientError(f"URL must include a host: {url}")

    host_slug = re.sub(r"[^a-z0-9]+", "-", parsed.netloc.lower()).strip("-")
    if host_slug == "":
        raise ClientError(f"URL host could not be converted to an audit ID: {url}")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}-{host_slug}"


def _require_mapping(data: dict, key: str) -> dict:
    if key not in data:
        raise ClientError(f"Lighthouse report missing '{key}'")
    value = data[key]
    if not isinstance(value, dict):
        raise ClientError(f"Lighthouse report field '{key}' must be an object")
    return value


def _require_string(data: dict, key: str) -> str:
    if key not in data:
        raise ClientError(f"Lighthouse report missing '{key}'")
    value = data[key]
    if not isinstance(value, str):
        raise ClientError(f"Lighthouse report field '{key}' must be a string")
    return value


def _category_score(categories: dict, key: str) -> int:
    if key not in categories:
        raise ClientError(f"Lighthouse report missing category '{key}'")
    category = categories[key]
    if not isinstance(category, dict):
        raise ClientError(f"Lighthouse category '{key}' must be an object")
    if "score" not in category:
        raise ClientError(f"Lighthouse category '{key}' missing score")
    return round(float(category["score"]) * 100)


def _optional_category_score(categories: dict, key: str) -> Optional[int]:
    if key not in categories:
        return None
    return _category_score(categories, key)


def _metric(audits: dict, key: str) -> float:
    if key not in audits:
        raise ClientError(f"Lighthouse report missing audit '{key}'")
    audit = audits[key]
    if not isinstance(audit, dict):
        raise ClientError(f"Lighthouse audit '{key}' must be an object")
    if "numericValue" not in audit:
        raise ClientError(f"Lighthouse audit '{key}' missing numericValue")
    return float(audit["numericValue"])


class GoogleLighthouseClient:
    """Wrapper client for the local Lighthouse CLI."""

    def __init__(self, data_dir: Optional[Path] = None):
        self.config = get_config()
        if not self.config.is_cli_available():
            raise ClientError(
                f"Underlying CLI '{self.config.cli_command}' not found. Install Lighthouse before running audits."
            )

        if data_dir is None:
            self.data_dir = self.config.data_dir
        else:
            self.data_dir = Path(data_dir)

    def run_audit(
        self,
        url: str,
        form_factor: str = "desktop",
        chrome_flags: str = "--headless=new",
        timeout_seconds: int = 180,
    ) -> AuditSummary:
        """Run Lighthouse against a URL and persist report artifacts."""

        if form_factor not in {"desktop", "mobile"}:
            raise ClientError("form_factor must be 'desktop' or 'mobile'")

        audit_id = new_audit_id(url)
        created_at = utc_timestamp()
        audit_dir = self.data_dir / audit_id
        audit_dir.mkdir(parents=True, exist_ok=False)

        output_base = audit_dir / audit_id
        command = self.config.get_cli_command() + [
            url,
            "--quiet",
            "--output=json",
            "--output=html",
            "--output-path",
            str(output_base),
            f"--chrome-flags={chrome_flags}",
            f"--form-factor={form_factor}",
        ]
        if form_factor == "desktop":
            command.append("--screenEmulation.disabled")

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            raise ClientError(f"Lighthouse timed out after {timeout_seconds} seconds") from error
        except FileNotFoundError as error:
            raise ClientError(f"Underlying CLI '{self.config.cli_command}' not found in PATH") from error

        if result.returncode != 0:
            message = result.stderr.strip()
            if message == "":
                message = result.stdout.strip()
            if message == "":
                message = f"Lighthouse exited with status {result.returncode}"
            raise ClientError(message)

        json_report = output_base.with_suffix(".report.json")
        html_report = output_base.with_suffix(".report.html")
        if not json_report.is_file():
            raise ClientError(f"Lighthouse did not create JSON report: {json_report}")
        if not html_report.is_file():
            raise ClientError(f"Lighthouse did not create HTML report: {html_report}")

        report = json.loads(json_report.read_text(encoding="utf-8"))
        summary = self._summary_from_report(
            report=report,
            audit_id=audit_id,
            created_at=created_at,
            form_factor=form_factor,
            json_report=json_report,
            html_report=html_report,
        )
        self._write_summary(audit_dir, summary)
        return summary

    def list_audits(self, limit: int = 100, filters: Optional[list[str]] = None) -> list[AuditSummary]:
        """List persisted Lighthouse audit summaries."""

        if limit < 1:
            raise ClientError("limit must be greater than 0")

        if filters is not None:
            validate_filters(filters)

        if not self.data_dir.exists():
            return []

        summaries = [self._read_summary(path) for path in self.data_dir.glob("*/summary.json")]
        summaries.sort(key=lambda summary: summary.created_at, reverse=True)

        if filters is not None:
            summary_dicts = [summary.model_dump(mode="json", by_alias=True) for summary in summaries]
            summaries = [create_audit_summary(data) for data in apply_filters(summary_dicts, filters)]

        return summaries[:limit]

    def get_audit(self, audit_id: str) -> AuditSummary:
        """Get a persisted Lighthouse audit summary by ID."""

        summary_path = self.data_dir / audit_id / "summary.json"
        if not summary_path.is_file():
            raise ClientError(f"Audit not found: {audit_id}")
        return self._read_summary(summary_path)

    def _summary_from_report(
        self,
        report: dict,
        audit_id: str,
        created_at: str,
        form_factor: str,
        json_report: Path,
        html_report: Path,
    ) -> AuditSummary:
        categories = _require_mapping(report, "categories")
        audits = _require_mapping(report, "audits")

        return AuditSummary(
            id=audit_id,
            url=_require_string(report, "requestedUrl"),
            final_url=_require_string(report, "finalDisplayedUrl"),
            created_at=created_at,
            form_factor=form_factor,
            scores=AuditScores(
                performance=_category_score(categories, "performance"),
                accessibility=_category_score(categories, "accessibility"),
                best_practices=_category_score(categories, "best-practices"),
                seo=_category_score(categories, "seo"),
                pwa=_optional_category_score(categories, "pwa"),
            ),
            metrics=AuditMetrics(
                first_contentful_paint_ms=_metric(audits, "first-contentful-paint"),
                largest_contentful_paint_ms=_metric(audits, "largest-contentful-paint"),
                total_blocking_time_ms=_metric(audits, "total-blocking-time"),
                cumulative_layout_shift=_metric(audits, "cumulative-layout-shift"),
                speed_index_ms=_metric(audits, "speed-index"),
                time_to_interactive_ms=_metric(audits, "interactive"),
            ),
            artifacts=AuditArtifacts(json=str(json_report), html=str(html_report)),
        )

    def _write_summary(self, audit_dir: Path, summary: AuditSummary) -> None:
        summary_path = audit_dir / "summary.json"
        summary_path.write_text(
            json.dumps(summary.model_dump(mode="json", by_alias=True), indent=2) + "\n",
            encoding="utf-8",
        )

    def _read_summary(self, summary_path: Path) -> AuditSummary:
        data = json.loads(summary_path.read_text(encoding="utf-8"))
        return create_audit_summary(data)


_client: Optional[GoogleLighthouseClient] = None


def get_client() -> GoogleLighthouseClient:
    """Get or create the global Google Lighthouse client instance."""

    global _client
    if _client is None:
        _client = GoogleLighthouseClient()
    return _client
