"""Ticket models for Progress ServiceNow CLI."""
from enum import Enum
from typing import Optional, List

from .base import CLIModel


class TicketState(str, Enum):
    """State values for ServiceNow tickets."""

    OPEN = "Open"
    WORK_IN_PROGRESS = "Work in Progress"
    CLOSED_COMPLETE = "Closed Complete"
    CLOSED_INCOMPLETE = "Closed Incomplete"
    CLOSED_SKIPPED = "Closed Skipped"


class TicketPriority(str, Enum):
    """Priority levels for ServiceNow tickets."""

    CRITICAL = "1 - Critical"
    HIGH = "2 - High"
    MODERATE = "3 - Moderate"
    LOW = "4 - Low"


class TicketView(str, Enum):
    """View options on the My Requests page."""

    OPEN = "My Open Tasks"
    CLOSED = "My Closed Tasks"
    WATCHLIST_OPEN = "My Watchlist Open Tasks"
    WATCHLIST_CLOSED = "My Watchlist Closed Tasks"


class Ticket(CLIModel):
    """Ticket summary model returned by list commands."""

    number: str
    description: str
    state: Optional[str] = None
    updated: Optional[str] = None
    requested_for: Optional[str] = None
    sys_id: Optional[str] = None


class TicketDetail(Ticket):
    """Detailed ticket model returned by get commands."""

    created: Optional[str] = None
    assignment_group: Optional[str] = None
    assigned_to: Optional[str] = None
    priority: Optional[str] = None
    approval_status: Optional[str] = None
    contacts: Optional[List[str]] = None
    comments: Optional[List["Comment"]] = None


class Comment(CLIModel):
    """A comment/activity entry on a ticket."""

    author: str
    timestamp: str
    type: Optional[str] = None  # "Additional comments", etc.
    text: str


class CatalogItem(CLIModel):
    """A catalog item (request form or article)."""

    name: str
    description: Optional[str] = None
    type: Optional[str] = None  # "Request", "Article"
    url: Optional[str] = None
    sys_id: Optional[str] = None
