"""Cache management for site audit reports.

Site audit reports are cached to `site_audits/<project_id>.json` within the
CLI's storage directory. This provides fast access to previously fetched
reports without hitting the API.

Usage:
    from .cache import get_cached_report, save_cached_report, cache_exists

    # Check if report exists
    if cache_exists(project_id) and not refresh:
        return get_cached_report(project_id)

    # Fetch and cache
    report = fetch_from_api(project_id)
    save_cached_report(project_id, report)
"""
import json
from pathlib import Path
from typing import Optional

from .config import get_config
from .models import SiteAuditReport


def _get_cache_dir() -> Path:
    """Get the cache directory for site audits."""
    config = get_config()
    cache_dir = Path(config.storage_dir) / "site_audits"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _get_cache_path(project_id: int) -> Path:
    """Get the cache file path for a specific project."""
    return _get_cache_dir() / f"{project_id}.json"


def cache_exists(project_id: int) -> bool:
    """Check if a cached report exists for a project.

    Args:
        project_id: The Ahrefs project ID

    Returns:
        True if a cached report exists, False otherwise
    """
    return _get_cache_path(project_id).exists()


def get_cached_report(project_id: int) -> Optional[SiteAuditReport]:
    """Load a cached site audit report.

    Args:
        project_id: The Ahrefs project ID

    Returns:
        SiteAuditReport if cache exists and is valid, None otherwise
    """
    cache_path = _get_cache_path(project_id)
    if not cache_path.exists():
        return None

    try:
        with open(cache_path, "r") as f:
            data = json.load(f)
        return SiteAuditReport(**data)
    except (json.JSONDecodeError, ValueError):
        # Invalid cache, remove it
        cache_path.unlink(missing_ok=True)
        return None


def save_cached_report(project_id: int, report: SiteAuditReport) -> Path:
    """Save a site audit report to cache.

    Args:
        project_id: The Ahrefs project ID
        report: The SiteAuditReport to cache

    Returns:
        Path to the cache file
    """
    cache_path = _get_cache_path(project_id)
    with open(cache_path, "w") as f:
        json.dump(report.model_dump(), f, indent=2, default=str)
    return cache_path


def clear_cache(project_id: Optional[int] = None) -> int:
    """Clear cached reports.

    Args:
        project_id: If provided, clear only this project's cache.
                   If None, clear all cached reports.

    Returns:
        Number of cache files removed
    """
    if project_id is not None:
        cache_path = _get_cache_path(project_id)
        if cache_path.exists():
            cache_path.unlink()
            return 1
        return 0

    # Clear all
    cache_dir = _get_cache_dir()
    removed = 0
    for cache_file in cache_dir.glob("*.json"):
        cache_file.unlink()
        removed += 1
    return removed


def list_cached_projects() -> list[int]:
    """List all project IDs with cached reports.

    Returns:
        List of project IDs that have cached reports
    """
    cache_dir = _get_cache_dir()
    projects = []
    for cache_file in cache_dir.glob("*.json"):
        try:
            project_id = int(cache_file.stem)
            projects.append(project_id)
        except ValueError:
            continue
    return sorted(projects)
