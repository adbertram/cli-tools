"""Azlogs client — orchestrates download, parse, validate, and query operations.

Unlike typical API CLIs, this client:
1. Downloads logs via Kudu REST API (using az CLI credentials)
2. Stores logs locally as packages (directories with merged JSONL)
3. Queries against local data (client-side filtering on JSONL)
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from .config import get_config
from .core.discovery import discover_log_files
from .core.downloader import download_all
from .core.merger import create_log_package as _create_log_package
from .core.validator import validate_jsonl
from .filters import validate_filters, apply_filters, apply_properties_filter, apply_limit, FilterValidationError
from .models import (
    Entity, LogLevel, LogEntry, LogFile, LogPackage, LogPackageDetail,
    OutputFormat, ValidationResult, ContainerType,
)


class ClientError(Exception):
    """Custom exception for azlogs client errors."""
    pass


class AzlogsClient:
    """Client for Azure Web App log operations."""

    def __init__(self):
        self.config = get_config()
        self.data_dir = self.config.data_dir
        # Ensure data dir exists
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _require_config(self):
        """Raise if app name / resource group not provided via CLI flags."""
        missing = []
        if not self.config.app_name:
            missing.append("--app")
        if not self.config.resource_group:
            missing.append("--resource-group")
        if missing:
            raise ClientError(
                f"Missing required flags: {', '.join(missing)}. "
                "Example: azlogs --app myapp --resource-group myrg packages download"
            )

    def _get_package_dir(self, name: str) -> Path:
        """Resolve package directory by name, raise if not found."""
        pkg_dir = self.data_dir / name
        if not pkg_dir.is_dir():
            raise ClientError(f"Package '{name}' not found in {self.data_dir}")
        return pkg_dir

    # ==================== Package Operations ====================

    def download_package(
        self, include_kudu_trace: bool = False, since: str = "24h",
    ) -> LogPackage:
        """Download fresh logs from Azure → parse → return package info."""
        from .core.timeutil import cutoff_from_since

        self._require_config()

        # Create timestamped output directory
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_dir = self.data_dir / timestamp

        # Download from Azure via Kudu API
        download_all(
            self.config.app_name, self.config.resource_group, output_dir,
            include_kudu_trace=include_kudu_trace,
        )

        # Parse + merge into JSONL + generate report
        cutoff = cutoff_from_since(since)
        _create_log_package(output_dir, fmt=OutputFormat.JSONL, generate_html=True, cutoff=cutoff)

        # Return package summary
        return self._build_package_summary(output_dir)

    def list_packages(self, limit: int = 100, filters: Optional[List[str]] = None) -> List[LogPackage]:
        """List all downloaded log packages."""
        packages = []
        if not self.data_dir.exists():
            return packages

        for d in sorted(self.data_dir.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            # Skip hidden dirs
            if d.name.startswith("."):
                continue
            packages.append(self._build_package_summary(d))

        # Client-side filtering — packages are local data
        if filters:
            try:
                validate_filters(filters)
            except FilterValidationError as e:
                raise ClientError(f"Invalid filter: {e}")
            dicts = [p.to_dict() for p in packages]
            dicts = apply_filters(dicts, filters)
            packages = [LogPackage(**d) for d in dicts]

        # Apply limit
        packages = packages[:limit]

        return packages

    def get_package(self, name: str) -> LogPackageDetail:
        """Get detailed info about a specific package."""
        pkg_dir = self._get_package_dir(name)
        summary = self._build_package_summary(pkg_dir)

        # Discover files for detail view
        files = discover_log_files(pkg_dir)
        log_files = []
        for f in files:
            size = f.path.stat().st_size if f.path.exists() else 0
            log_files.append(LogFile(
                path=f.relative_path,
                entity=f.entity,
                size_bytes=size,
                container_type=f.metadata.container_type if f.metadata else None,
                date=f.metadata.date if f.metadata else None,
                instance=f.metadata.instance if f.metadata else None,
            ))

        # Count entities and levels from merged JSONL
        entity_counts = {}
        level_counts = {}
        jsonl_path = pkg_dir / "merged.jsonl"
        if jsonl_path.exists():
            for line in jsonl_path.read_text().splitlines():
                if not line.strip():
                    continue
                try:
                    d = json.loads(line)
                    entity = d.get("entity", "unknown")
                    level = d.get("level", "UNKNOWN")
                    entity_counts[entity] = entity_counts.get(entity, 0) + 1
                    level_counts[level] = level_counts.get(level, 0) + 1
                except json.JSONDecodeError:
                    continue

        return LogPackageDetail(
            name=summary.name,
            path=summary.path,
            created=summary.created,
            file_count=summary.file_count,
            entry_count=summary.entry_count,
            has_merged=summary.has_merged,
            has_report=summary.has_report,
            is_valid=summary.is_valid,
            earliest_entry=summary.earliest_entry,
            latest_entry=summary.latest_entry,
            files=log_files,
            entity_counts=entity_counts if entity_counts else None,
            level_counts=level_counts if level_counts else None,
        )

    def parse_package(
        self, name: str, fmt: OutputFormat = OutputFormat.JSONL, since: str = "all",
    ) -> LogPackage:
        """Re-parse an existing package (regenerate merged output + report)."""
        from .core.timeutil import cutoff_from_since

        pkg_dir = self._get_package_dir(name)
        cutoff = cutoff_from_since(since)
        _create_log_package(pkg_dir, fmt=fmt, generate_html=True, cutoff=cutoff)
        return self._build_package_summary(pkg_dir)

    def validate_package(self, name: str) -> ValidationResult:
        """Validate merged.jsonl covers every raw line in the package."""
        pkg_dir = self._get_package_dir(name)
        jsonl_path = pkg_dir / "merged.jsonl"
        if not jsonl_path.exists():
            raise ClientError(f"merged.jsonl not found in package '{name}'. Run parse first.")

        result = validate_jsonl(pkg_dir, jsonl_path)
        return ValidationResult(
            is_valid=result.is_valid,
            total_raw_lines=result.total_raw_lines,
            total_covered_lines=result.total_covered_lines,
            missing_count=len(result.missing_lines),
            missing_lines=[{"file": f, "line_number": ln} for f, ln in result.missing_lines[:100]],
        )

    def delete_package(self, name: str) -> bool:
        """Delete a log package directory."""
        pkg_dir = self._get_package_dir(name)
        shutil.rmtree(pkg_dir)
        return True

    # ==================== Entry Operations ====================

    def list_entries(
        self,
        package: str,
        limit: int = 100,
        filters: Optional[List[str]] = None,
    ) -> List[LogEntry]:
        """List log entries from a package's merged.jsonl.

        All filtering is client-side since data is local JSONL.
        """
        pkg_dir = self._get_package_dir(package)
        jsonl_path = pkg_dir / "merged.jsonl"
        if not jsonl_path.exists():
            raise ClientError(f"merged.jsonl not found in package '{package}'. Run parse first.")

        # Validate filters upfront
        if filters:
            try:
                validate_filters(filters)
            except FilterValidationError as e:
                raise ClientError(f"Invalid filter: {e}")

        # Read JSONL and convert to dicts
        entries_dicts = []
        with jsonl_path.open(encoding="utf-8") as f:
            for raw_line in f:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    entries_dicts.append(json.loads(raw_line))
                except json.JSONDecodeError:
                    continue

        # Client-side filtering
        if filters:
            entries_dicts = apply_filters(entries_dicts, filters)

        # Apply limit
        entries_dicts = apply_limit(entries_dicts, limit)

        # Convert to Pydantic models
        return [LogEntry(**d) for d in entries_dicts]

    def get_entry(self, package: str, source_file: str, line_number: int) -> LogEntry:
        """Get a specific entry by source_file and line_number."""
        pkg_dir = self._get_package_dir(package)
        jsonl_path = pkg_dir / "merged.jsonl"
        if not jsonl_path.exists():
            raise ClientError(f"merged.jsonl not found in package '{package}'.")

        with jsonl_path.open(encoding="utf-8") as f:
            for raw_line in f:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    d = json.loads(raw_line)
                    if d.get("source_file") == source_file and d.get("line_number") == line_number:
                        return LogEntry(**d)
                except json.JSONDecodeError:
                    continue

        raise ClientError(f"Entry not found: {source_file}:{line_number}")

    # ==================== Report Operations ====================

    def generate_report(self, name: str) -> str:
        """Generate/regenerate HTML report for a package. Returns path to report."""
        from .core.report import generate_report as _generate_report
        from .core.types import InternalLogEntry

        pkg_dir = self._get_package_dir(name)
        jsonl_path = pkg_dir / "merged.jsonl"
        if not jsonl_path.exists():
            raise ClientError(f"merged.jsonl not found in package '{name}'. Run parse first.")

        # Read entries from JSONL
        entries = []
        with jsonl_path.open(encoding="utf-8") as f:
            for raw_line in f:
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    d = json.loads(raw_line)
                    entries.append(InternalLogEntry(
                        timestamp=datetime.fromisoformat(d["timestamp"].rstrip("Z")),
                        entity=Entity(d["entity"]),
                        service=d["service"],
                        instance=d.get("instance"),
                        container=d.get("container"),
                        level=LogLevel(d["level"]),
                        message=d["message"],
                        source_file=d["source_file"],
                        line_number=d["line_number"],
                    ))
                except (json.JSONDecodeError, KeyError):
                    continue

        # Detect sessions so the report includes the Sessions section
        from .core.sessions import detect_sessions, assign_entries_to_sessions
        sessions = detect_sessions(entries)
        assign_entries_to_sessions(entries, sessions)

        report_path = pkg_dir / "report.html"
        _generate_report(entries, report_path, sessions=sessions)
        return str(report_path)

    # ==================== Helpers ====================

    def _build_package_summary(self, pkg_dir: Path) -> LogPackage:
        """Build a LogPackage summary from a package directory."""
        jsonl_path = pkg_dir / "merged.jsonl"
        report_path = pkg_dir / "report.html"

        entry_count = 0
        earliest = None
        latest = None

        if jsonl_path.exists():
            with jsonl_path.open(encoding="utf-8") as f:
                for raw_line in f:
                    raw_line = raw_line.strip()
                    if not raw_line:
                        continue
                    entry_count += 1
                    try:
                        d = json.loads(raw_line)
                        ts = d.get("timestamp")
                        if ts:
                            if earliest is None or ts < earliest:
                                earliest = ts
                            if latest is None or ts > latest:
                                latest = ts
                    except json.JSONDecodeError:
                        continue

        # Count log files (not all files)
        file_count = 0
        if pkg_dir.exists():
            for p in pkg_dir.rglob("*"):
                if p.is_file() and p.suffix in (".log", ".txt"):
                    file_count += 1

        # Get creation time from directory name or stat
        try:
            created = datetime.strptime(pkg_dir.name, "%Y-%m-%d_%H-%M-%S").isoformat() + "Z"
        except ValueError:
            created = datetime.fromtimestamp(pkg_dir.stat().st_ctime).isoformat() + "Z"

        return LogPackage(
            name=pkg_dir.name,
            path=str(pkg_dir),
            created=created,
            file_count=file_count,
            entry_count=entry_count,
            has_merged=jsonl_path.exists(),
            has_report=report_path.exists(),
            earliest_entry=earliest,
            latest_entry=latest,
        )


# Module-level client instance — singleton pattern
_client: Optional[AzlogsClient] = None


def get_client() -> AzlogsClient:
    """Get or create the global Azlogs client instance."""
    global _client
    if _client is None:
        _client = AzlogsClient()
    return _client
