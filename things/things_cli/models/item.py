"""Things 3 data models.

Models match the Things SQLite database schema:
- TMTask: Tasks, Projects, Headings (type field distinguishes)
- TMArea: Areas/categories
- TMTag: Tags with hierarchy
- TMChecklistItem: Checklist items within tasks
"""
from datetime import datetime
from enum import IntEnum
from typing import List, Optional

from pydantic import Field

from .base import CLIModel


# ==================== Enums ====================
# Match Things database integer values


class TaskType(IntEnum):
    """TMTask.type values."""
    TODO = 0
    PROJECT = 1
    HEADING = 2


class TaskStatus(IntEnum):
    """TMTask.status values."""
    INCOMPLETE = 0
    COMPLETED = 3


class StartType(IntEnum):
    """TMTask.start values (the 'when' field)."""
    NOT_SET = 0   # Inbox
    ANYTIME = 1   # Anytime (or scheduled if startDate is set)
    SOMEDAY = 2   # Someday


# ==================== Models ====================


class ChecklistItem(CLIModel):
    """A checklist item within a task.

    Maps to TMChecklistItem table.
    """
    uuid: str = Field(frozen=True)
    title: str
    status: TaskStatus = TaskStatus.INCOMPLETE
    index: int = 0


class Task(CLIModel):
    """A to-do item from Things.

    Maps to TMTask table where type=0.
    """
    uuid: str = Field(frozen=True)
    title: str
    type: TaskType = TaskType.TODO
    status: TaskStatus = TaskStatus.INCOMPLETE
    start: StartType = StartType.ANYTIME
    notes: Optional[str] = None
    start_date: Optional[str] = None  # ISO date string
    deadline: Optional[str] = None    # ISO date string
    trashed: bool = False
    area_uuid: Optional[str] = None
    area: Optional[str] = None  # Area title (from todo or project's area)
    project_uuid: Optional[str] = None
    project: Optional[str] = None  # Project title
    heading_uuid: Optional[str] = None
    checklist_items: List[ChecklistItem] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)  # Tag titles
    creation_date: Optional[str] = Field(default=None, frozen=True)
    modification_date: Optional[str] = Field(default=None, frozen=True)


class Project(CLIModel):
    """A project from Things.

    Maps to TMTask table where type=1.
    """
    uuid: str = Field(frozen=True)
    title: str
    status: TaskStatus = TaskStatus.INCOMPLETE
    start: StartType = StartType.ANYTIME
    notes: Optional[str] = None
    start_date: Optional[str] = None
    deadline: Optional[str] = None
    trashed: bool = False
    area_uuid: Optional[str] = None
    area: Optional[str] = None  # Area title
    tags: List[str] = Field(default_factory=list)
    creation_date: Optional[str] = Field(default=None, frozen=True)
    modification_date: Optional[str] = Field(default=None, frozen=True)


class Area(CLIModel):
    """An area/category from Things.

    Maps to TMArea table.
    """
    uuid: str = Field(frozen=True)
    title: str
    visible: bool = True
    index: int = 0


class Tag(CLIModel):
    """A tag from Things.

    Maps to TMTag table.
    """
    uuid: str = Field(frozen=True)
    title: str
    shortcut: Optional[str] = None
    parent_uuid: Optional[str] = None
    index: int = 0


class AuthStatus(CLIModel):
    """Authentication status for the Things CLI.

    For Things, we don't use traditional auth - we just check
    if the database is accessible and the app isn't running.
    """
    authenticated: bool
    database_path: Optional[str] = None
    app_running: bool = False
    message: Optional[str] = None


# ==================== Factory Functions ====================


def create_task(data: dict) -> Task:
    """Create a Task model from database row."""
    return Task(**data)


def create_project(data: dict) -> Project:
    """Create a Project model from database row."""
    return Project(**data)


def create_area(data: dict) -> Area:
    """Create an Area model from database row."""
    return Area(**data)


def create_tag(data: dict) -> Tag:
    """Create a Tag model from database row."""
    return Tag(**data)


# Legacy aliases for template compatibility
Item = Task
ItemDetail = Task
ItemStatus = TaskStatus
ItemType = TaskType
create_item = create_task
create_item_detail = create_task


class ItemCreate(CLIModel):
    """Model for creating tasks (template compatibility)."""
    title: str
    notes: Optional[str] = None
    when: Optional[str] = None  # 'inbox', 'anytime', 'someday'
    deadline: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    project: Optional[str] = None


class ItemUpdate(CLIModel):
    """Model for updating tasks (template compatibility)."""
    title: Optional[str] = None
    notes: Optional[str] = None
    when: Optional[str] = None
    deadline: Optional[str] = None
    tags: Optional[List[str]] = None
    completed: Optional[bool] = None
