"""Filename parsing → FileMetadata."""
from __future__ import annotations

import re

from ..models import ContainerType, Entity
from .types import FileMetadata

# Matches: YYYY_MM_DD_<instance>_[default_][scm_]docker[.N].log
_DOCKER_LOG_RE = re.compile(
    r"^(\d{4}_\d{2}_\d{2})_([A-Za-z0-9]+)_((?:default_scm_|default_)?docker)(?:\.(\d+))?\.log$"
)


def container_type_from_filename(docker_part: str) -> ContainerType:
    """Determine container type from the docker portion of the filename."""
    if docker_part == "default_scm_docker":
        return ContainerType.SCM
    if docker_part == "default_docker":
        return ContainerType.APP
    return ContainerType.PLATFORM


def entity_for_container_type(ct: ContainerType) -> Entity:
    """Map ContainerType → Entity enum."""
    if ct is ContainerType.PLATFORM:
        return Entity.PLATFORM_ORCHESTRATOR
    if ct is ContainerType.APP:
        return Entity.APP_CONTAINER
    return Entity.SCM_SIDECAR


def parse_docker_log_filename(name: str) -> FileMetadata | None:
    """Parse a Docker log filename into FileMetadata, or None if no match."""
    m = _DOCKER_LOG_RE.match(name)
    if not m:
        return None
    date, instance, docker_part, rotation = m.groups()
    ct = container_type_from_filename(docker_part)
    return FileMetadata(
        date=date,
        instance=instance,
        container_type=ct,
        rotation=int(rotation) if rotation else None,
    )
