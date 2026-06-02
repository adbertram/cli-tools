"""Audit models for Google Lighthouse CLI output."""

from __future__ import annotations

from typing import Optional

from pydantic import Field

from .base import CLIModel


class AuditScores(CLIModel):
    """Normalized Lighthouse category scores."""

    performance: int
    accessibility: int
    best_practices: int
    seo: int
    pwa: Optional[int] = None


class AuditMetrics(CLIModel):
    """Normalized Lighthouse timing and layout metrics."""

    first_contentful_paint_ms: float
    largest_contentful_paint_ms: float
    total_blocking_time_ms: float
    cumulative_layout_shift: float
    speed_index_ms: float
    time_to_interactive_ms: float


class AuditArtifacts(CLIModel):
    """Paths to saved Lighthouse report artifacts."""

    json_report: str = Field(alias="json")
    html_report: str = Field(alias="html")


class AuditSummary(CLIModel):
    """Summary persisted for each Lighthouse audit."""

    id: str
    url: str
    final_url: str
    created_at: str
    form_factor: str
    scores: AuditScores
    metrics: AuditMetrics
    artifacts: AuditArtifacts


def create_audit_summary(data: dict) -> AuditSummary:
    """Create an AuditSummary model from normalized audit data."""

    return AuditSummary(**data)
