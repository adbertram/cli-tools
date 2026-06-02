"""Flow models for Globiflow."""
from enum import Enum
from typing import Optional, List
from pydantic import SerializeAsAny
from .base import CLIModel
from .step import Step


class TriggerType(str, Enum):
    """Available flow trigger types in Globiflow."""
    EVERY_DAY = "T"
    ITEM_CREATED = "C"
    ITEM_UPDATED = "U"
    COMMENT_ADDED = "Q"
    MANUAL = "M"
    TASK_COMPLETED = "K"
    DATE_FIELD = "F"
    EMAIL_REPLY = "R"
    SMS_REPLY = "S"
    RIGHTSIGNATURE = "X"
    EXTERNAL_LINK = "L"
    WEBHOOK = "W"
    FILE_UPLOAD = "FU"


class Trigger(CLIModel):
    """A Globiflow trigger type.

    Represents an available trigger condition for flows.
    """
    code: str
    name: str
    description: str


class Flow(CLIModel):
    """A Globiflow flow summary.

    Represents a flow as shown in the flows list, with basic metadata
    about its location in the org/workspace/app hierarchy.
    """
    id: str
    name: str
    app_name: str
    workspace_name: str
    org_name: str
    enabled: bool = True


class FlowDetail(CLIModel):
    """Detailed flow information.

    Extended flow data including notes and configuration.
    Returned by the `flows get` command.

    Steps are excluded by default and only included when --include-steps flag is used.
    """
    id: str
    name: str
    enabled: bool = True
    time_savings: Optional[str] = None
    notes: Optional[str] = None
    has_logs: bool = False
    steps: Optional[List[SerializeAsAny[Step]]] = None


class FlowLog(CLIModel):
    """A single flow execution log entry.

    Represents a log line in Globiflow's log viewer with format:
    Date & Time : Item : Log Entry
    """
    timestamp: str  # e.g., "2025-12-29 11:00:59"
    item_id: str  # Podio item ID, e.g., "3223678304"
    message: str  # Log message, e.g., "Triggered FlowItem.create"
    log_level: str = "info"  # "info" or "error"
