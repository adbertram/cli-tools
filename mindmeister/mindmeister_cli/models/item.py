"""MindMeister models for CLI.

Models represent the MindMeister API response structures.
Based on v1 API with OAuth2 authentication.
"""
from typing import Dict, List, Optional

from pydantic import Field

from .base import CLIModel


class Idea(CLIModel):
    """A node/idea within a mind map.

    Ideas are the building blocks of mind maps - they represent
    individual nodes in the map hierarchy.
    """
    id: str = Field(frozen=True)
    title: Optional[str] = None
    parent: Optional[str] = None
    rank: Optional[str] = None
    style: Optional[str] = None
    pos: Optional[Dict] = None
    floating: Optional[str] = None
    modifiedat: Optional[str] = None
    closed: Optional[str] = None
    modifiedby: Optional[str] = None


class Map(CLIModel):
    """A MindMeister mind map (list response).

    This is the basic map metadata returned by mm.maps.getList.
    """
    id: str = Field(frozen=True)
    title: str
    revision: Optional[str] = None
    description: Optional[str] = None
    created: Optional[str] = None
    modified: Optional[str] = None
    owner: Optional[str] = None
    sharedwith: Optional[str] = None
    share_link: Optional[str] = None
    tags: Optional[str] = None
    public: Optional[str] = None
    viewonly: Optional[str] = None
    default: Optional[str] = None
    subshare: Optional[str] = None
    layout: Optional[str] = None
    has_presentation: Optional[str] = None
    favourite: Optional[str] = None


class MapDetail(CLIModel):
    """A MindMeister mind map with full detail including ideas.

    This is the full map structure returned by mm.maps.getMap,
    including all ideas/nodes in the map.
    """
    id: str = Field(frozen=True)
    title: str
    revision: Optional[str] = None
    description: Optional[str] = None
    created: Optional[str] = None
    modified: Optional[str] = None
    owner: Optional[str] = None
    sharedwith: Optional[str] = None
    share_link: Optional[str] = None
    tags: Optional[str] = None
    public: Optional[str] = None
    viewonly: Optional[str] = None
    default: Optional[str] = None
    subshare: Optional[str] = None
    layout: Optional[str] = None
    has_presentation: Optional[str] = None
    favourite: Optional[str] = None
    # Full structure fields
    ideas: List[Idea] = []
    connections: Optional[Dict] = None
    timestamp: Optional[str] = None
    node_count: int = 0  # Computed field


class ExportUrls(CLIModel):
    """Export URLs returned by mm.maps.export."""
    pdf: Optional[str] = None
    png: Optional[str] = None
    mm: Optional[str] = None
    freemind: Optional[str] = None
    mindmanager: Optional[str] = None
    word: Optional[str] = None
    powerpoint: Optional[str] = None


def create_map(data: dict) -> Map:
    """Create a Map model from API response data."""
    return Map(**data)


def create_map_detail(data: dict) -> MapDetail:
    """Create a MapDetail model from API response data.

    Handles the nested structure where ideas come as a dict with 'idea' key.
    """
    # Extract map metadata
    map_data = data.get("map", {})

    # Extract ideas from nested structure
    ideas_data = data.get("ideas", {})
    raw_ideas = ideas_data.get("idea", [])

    # Handle single idea (comes as dict) vs multiple (comes as list)
    if isinstance(raw_ideas, dict):
        raw_ideas = [raw_ideas]

    ideas = [Idea(**idea) for idea in raw_ideas]

    # Build the full model
    result = MapDetail(
        id=map_data.get("id", data.get("id", "")),
        title=map_data.get("title", data.get("title", "")),
        revision=map_data.get("revision") or data.get("revision"),
        description=map_data.get("description") or data.get("description"),
        created=map_data.get("created") or data.get("created"),
        modified=map_data.get("modified") or data.get("modified"),
        owner=map_data.get("owner") or data.get("owner"),
        sharedwith=map_data.get("sharedwith") or data.get("sharedwith"),
        share_link=map_data.get("share_link") or data.get("share_link"),
        tags=map_data.get("tags") or data.get("tags"),
        public=map_data.get("public") or data.get("public"),
        viewonly=map_data.get("viewonly") or data.get("viewonly"),
        default=map_data.get("default") or data.get("default"),
        subshare=map_data.get("subshare") or data.get("subshare"),
        layout=map_data.get("layout") or data.get("layout"),
        has_presentation=map_data.get("has_presentation") or data.get("has_presentation"),
        favourite=map_data.get("favourite") or data.get("favourite"),
        ideas=ideas,
        connections=data.get("connections"),
        timestamp=data.get("timestamp"),
        node_count=len(ideas),
    )

    return result


def create_export_urls(data: dict) -> ExportUrls:
    """Create ExportUrls model from API response."""
    return ExportUrls(**data)
