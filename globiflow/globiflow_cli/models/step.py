"""Step models for Globiflow flows.

This module defines a hierarchy of step models:
- Step: Base model with core fields
- Category models: FilterStep, CollectorStep, LogicStep, ActionStep
- Type-specific models: VariableCalcStep, HttpCallStep, SendEmailStep, etc.
"""
from enum import Enum
from typing import Annotated, Optional, List, Union
from pydantic import BeforeValidator
from .base import CLIModel


def _normalize_auth_mode(value: object) -> object:
    """Normalize authentication mode strings from Globiflow's UI to enum values.

    The UI may display variations like 'The App Itself (recommended)' for 'App',
    so we normalize these before enum validation.
    """
    if not isinstance(value, str):
        return value
    normalized = value.strip().lower()
    if "app" in normalized and "admin" not in normalized:
        return "App"
    if "admin" in normalized:
        return "Admin Member"
    return value


# ==================== Enums ====================


class StepCategory(str, Enum):
    """Categories of flow steps."""
    FILTER = "filter"
    COLLECTOR = "collector"
    LOGIC = "logic"
    ACTION = "action"


class HttpMethod(str, Enum):
    """HTTP methods for remote calls."""
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


class ComparisonOperator(str, Enum):
    """Comparison operators for filters and searches."""
    EQUALS = "="
    NOT_EQUALS = "!="
    CONTAINS = "contains"
    NOT_CONTAINS = "does not contain"
    STARTS_WITH = "starts with"
    ENDS_WITH = "ends with"
    GREATER_THAN = ">"
    LESS_THAN = "<"
    GREATER_OR_EQUAL = ">="
    LESS_OR_EQUAL = "<="
    IS_EMPTY = "is empty"
    IS_NOT_EMPTY = "is not empty"
    CHANGED = "changed"
    NOT_CHANGED = "not changed"


class RelationshipDirection(str, Enum):
    """Direction for relationship traversal in collectors."""
    FORWARD = "FORWARD"
    REVERSE = "REVERSE"
    BOTH = "BOTH"


class SortDirection(str, Enum):
    """Sort direction for collected items."""
    ASCENDING = "Ascending"
    DESCENDING = "Descending"


class AttachmentOption(str, Enum):
    """Options for file attachments."""
    NONE = "None"
    MOST_RECENT = "Most Recent One"
    ALL_FILES = "All Files"


class ReplyHandling(str, Enum):
    """How to handle email replies."""
    RECEIVE_AT_EMAIL = "Receive at Email Address"
    TRIGGER_FLOW = "Trigger another Flow"


class AuthenticationMode(str, Enum):
    """Authentication mode for item operations."""
    APP = "App"
    ADMIN_MEMBER = "Admin Member"


# Annotated type that normalizes raw UI strings before enum validation
NormalizedAuthMode = Annotated[AuthenticationMode, BeforeValidator(_normalize_auth_mode)]


class IterateOver(str, Enum):
    """What to iterate over in For Each loops."""
    COLLECTED_ITEMS = "Collected Items"
    CATEGORIES = "Categories"
    CONTACTS = "Contacts"
    TAGS = "Tags"


class PageSize(str, Enum):
    """Page sizes for PDF generation."""
    LETTER = "Letter"
    A4 = "A4"
    LEGAL = "Legal"


class PageOrientation(str, Enum):
    """Page orientation for PDF generation."""
    PORTRAIT = "Portrait"
    LANDSCAPE = "Landscape"


class DateMatchType(str, Enum):
    """Types of date matching for filters."""
    SPECIFIC_DATE = "Specific Date"
    DAY_OF_WEEK = "Day of Week"
    DAY_OF_MONTH = "Day of Month"


class CreatorEditorCheckType(str, Enum):
    """Types of creator/editor checks."""
    CREATOR = "Creator"
    EDITOR = "Editor"
    CREATED_BY_APP = "Created By App"
    EDITED_BY_APP = "Edited By App"


class FileSelection(str, Enum):
    """Options for selecting files."""
    ALL_FILES = "All Files"
    MOST_RECENT = "Most Recent"
    PATTERN_MATCH = "Pattern Match"


class TaskSelection(str, Enum):
    """Options for selecting tasks."""
    ALL = "All"
    SPECIFIC_PATTERN = "Specific task pattern"


# ==================== Base Step Model ====================


class Step(CLIModel):
    """Base step model with core fields common to all step types.

    Attributes:
        step_number: Position in the flow (1-based)
        action_type: The action name from Globiflow (e.g., "Create a new Variable")
        category: The step category (filter, collector, logic, action)
        action_cost: Number of actions consumed (0 for logic, 1+ for actions)
        parameters: Catch-all for fields not mapped to specific model attributes
        flow_id: Optional flow ID when step is retrieved in detail context
    """
    step_number: int
    action_type: str
    category: Optional[StepCategory] = None
    action_cost: Optional[int] = None
    parameters: Optional[dict] = None
    flow_id: Optional[str] = None


# ==================== Filter Steps ====================


class FilterStep(Step):
    """Base model for filter steps."""
    category: StepCategory = StepCategory.FILTER


class FieldChangedFilter(FilterStep):
    """Filter: Check if a field was changed."""
    field: Optional[str] = None


class FieldValueMatchFilter(FilterStep):
    """Filter: Match a field to a specific value."""
    field: Optional[str] = None
    operator: Optional[str] = None
    value: Optional[str] = None


class CreatorEditorFilter(FilterStep):
    """Filter: Check who created/edited the item."""
    check_type: Optional[CreatorEditorCheckType] = None
    user: Optional[str] = None


class CustomCalcFilter(FilterStep):
    """Filter: Custom PHP expression that evaluates to true/false."""
    code: Optional[str] = None  # PHP expression


class DateMatchFilter(FilterStep):
    """Filter: Match a specific date, day of week, or day of month."""
    match_type: Optional[DateMatchType] = None
    value: Optional[str] = None


class CommentMatchFilter(FilterStep):
    """Filter: Check contents of a triggering comment."""
    operator: Optional[str] = None
    value: Optional[str] = None


# ==================== Collector Steps ====================


class CollectorStep(Step):
    """Base model for collector steps."""
    category: StepCategory = StepCategory.COLLECTOR


class GetReferencedItemsCollector(CollectorStep):
    """Collector: Get referenced items from another app."""
    app: Optional[str] = None
    direction: RelationshipDirection = RelationshipDirection.FORWARD
    using_field: Optional[str] = None


class SearchForItemsCollector(CollectorStep):
    """Collector: Search for items in an app."""
    app: Optional[str] = None
    search_field: Optional[str] = None
    operator: Optional[str] = None
    search_value: Optional[str] = None
    limit: Optional[int] = None


class GetPodioViewCollector(CollectorStep):
    """Collector: Get items from a Podio view."""
    app: Optional[str] = None
    view: Optional[str] = None
    limit: Optional[int] = None


# ==================== Logic Steps ====================


class LogicStep(Step):
    """Base model for logic steps."""
    category: StepCategory = StepCategory.LOGIC


class VariableCalcStep(LogicStep):
    """Logic: Create a custom variable using PHP expression."""
    variable_name: Optional[str] = None
    code: Optional[str] = None  # PHP expression


class IfSanityCheckStep(LogicStep):
    """Logic: Conditional IF statement using PHP expression."""
    code: Optional[str] = None  # PHP expression that evaluates to true/false


class SortCollectedStep(LogicStep):
    """Logic: Sort collected items."""
    sort_by: Optional[str] = None
    sort_direction: SortDirection = SortDirection.ASCENDING


class ForEachStep(LogicStep):
    """Logic: Iterate over collected items or other collections."""
    iterate_over: Optional[IterateOver] = None


class DetailTableStep(LogicStep):
    """Logic: Create an HTML table from collected items."""
    variable_name: Optional[str] = None
    columns: Optional[List[str]] = None
    include_header: bool = True


# ==================== Action Steps ====================


class ActionStep(Step):
    """Base model for action steps."""
    category: StepCategory = StepCategory.ACTION


class HttpCallStep(ActionStep):
    """Action: Make a remote HTTP call."""
    url: Optional[str] = None
    method: HttpMethod = HttpMethod.GET
    headers: Optional[str] = None
    get_params: Optional[str] = None
    post_params: Optional[str] = None
    follow_redirect: bool = True
    variable_name: Optional[str] = None  # Store response in variable


class SendEmailStep(ActionStep):
    """Action: Send an email."""
    to: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    from_name: Optional[str] = None
    reply_to: Optional[str] = None
    cc: Optional[str] = None
    bcc: Optional[str] = None
    reply_handling: ReplyHandling = ReplyHandling.RECEIVE_AT_EMAIL
    attach_files: AttachmentOption = AttachmentOption.NONE
    file_pattern: Optional[str] = None


class SendSmsStep(ActionStep):
    """Action: Send an SMS text message."""
    to: Optional[str] = None
    message: Optional[str] = None


class SendMessageStep(ActionStep):
    """Action: Send a Podio chat message."""
    to: Optional[str] = None
    message: Optional[str] = None


class AddCommentStep(ActionStep):
    """Action: Add a comment to the current item."""
    comment_body: Optional[str] = None
    silent: bool = False


class AssignTaskStep(ActionStep):
    """Action: Assign a task to a user."""
    assignee: Optional[str] = None
    task_text: Optional[str] = None
    due_date: Optional[str] = None
    reminder: Optional[str] = None


class UpdateItemStep(ActionStep):
    """Action: Update fields on the current item."""
    fields: Optional[dict] = None
    silent: bool = False
    authentication: NormalizedAuthMode = AuthenticationMode.APP
    hook_event: bool = False


class CreateItemStep(ActionStep):
    """Action: Create a new item in an app."""
    app: Optional[str] = None
    fields: Optional[dict] = None
    silent: bool = False
    authentication: NormalizedAuthMode = AuthenticationMode.APP
    hook_event: bool = False


class MakePdfStep(ActionStep):
    """Action: Create a PDF file."""
    template: Optional[str] = None
    filename: Optional[str] = None
    page_size: PageSize = PageSize.LETTER
    orientation: PageOrientation = PageOrientation.PORTRAIT


class BuildExcelStep(ActionStep):
    """Action: Build an Excel file from collected items."""
    filename: Optional[str] = None
    columns: Optional[List[str]] = None
    include_header: bool = True


class TriggerFlowStep(ActionStep):
    """Action: Trigger another flow."""
    flow: Optional[str] = None


class TriggerFlowOnRelatedStep(ActionStep):
    """Action: Trigger a flow on related items."""
    app: Optional[str] = None
    flow: Optional[str] = None
    relationship_field: Optional[str] = None


class UpdateWidgetStep(ActionStep):
    """Action: Update a workspace widget."""
    workspace: Optional[str] = None
    widget: Optional[str] = None
    content: Optional[str] = None


class DisplayPageStep(ActionStep):
    """Action: Display a web page to user (for special link flows)."""
    title: Optional[str] = None
    content: Optional[str] = None


# Type alias for any step type
AnyStep = Union[
    Step,
    # Filters
    FilterStep, FieldChangedFilter, FieldValueMatchFilter, CreatorEditorFilter,
    CustomCalcFilter, DateMatchFilter, CommentMatchFilter,
    # Collectors
    CollectorStep, GetReferencedItemsCollector, SearchForItemsCollector, GetPodioViewCollector,
    # Logic
    LogicStep, VariableCalcStep, IfSanityCheckStep, SortCollectedStep, ForEachStep, DetailTableStep,
    # Actions
    ActionStep, HttpCallStep, SendEmailStep, SendSmsStep, SendMessageStep, AddCommentStep,
    AssignTaskStep, UpdateItemStep, CreateItemStep, MakePdfStep, BuildExcelStep,
    TriggerFlowStep, TriggerFlowOnRelatedStep, UpdateWidgetStep, DisplayPageStep,
]


# ==================== Step Factory ====================


# Mapping of action_type patterns to (StepClass, category)
# More specific patterns should come before general ones
_STEP_TYPE_MAPPINGS: List[tuple] = [
    # Filters
    ("Field Changed", FieldChangedFilter, StepCategory.FILTER),
    ("Field Value Match", FieldValueMatchFilter, StepCategory.FILTER),
    ("Field Previous Value Match", FieldValueMatchFilter, StepCategory.FILTER),
    ("Creator / Editor", CreatorEditorFilter, StepCategory.FILTER),
    ("Custom (Calc)", CustomCalcFilter, StepCategory.FILTER),
    ("Date Match", DateMatchFilter, StepCategory.FILTER),
    ("Comment Match", CommentMatchFilter, StepCategory.FILTER),
    ("Email Subject Match", CommentMatchFilter, StepCategory.FILTER),

    # Collectors
    ("Get Previous Revision", CollectorStep, StepCategory.COLLECTOR),
    ("Get Item Task", CollectorStep, StepCategory.COLLECTOR),
    ("Get Referenced Item", GetReferencedItemsCollector, StepCategory.COLLECTOR),
    ("Search for Item", SearchForItemsCollector, StepCategory.COLLECTOR),
    ("Get Podio View", GetPodioViewCollector, StepCategory.COLLECTOR),

    # Logic
    ("Sort Collected", SortCollectedStep, StepCategory.LOGIC),
    ("Clear Collected", LogicStep, StepCategory.LOGIC),
    ("Custom Variable", VariableCalcStep, StepCategory.LOGIC),
    ("Create a new Variable", VariableCalcStep, StepCategory.LOGIC),
    ("If (Sanity Check)", IfSanityCheckStep, StepCategory.LOGIC),
    ("End If", LogicStep, StepCategory.LOGIC),
    ("Detail Table", DetailTableStep, StepCategory.LOGIC),
    ("For Each", ForEachStep, StepCategory.LOGIC),
    ("Continue", LogicStep, StepCategory.LOGIC),
    ("Wait", LogicStep, StepCategory.LOGIC),

    # Actions
    ("Remote HTTP Call", HttpCallStep, StepCategory.ACTION),
    ("Capture Result of a Remote HTTP Call", HttpCallStep, StepCategory.ACTION),
    ("Send Email", SendEmailStep, StepCategory.ACTION),
    ("Send SMS", SendSmsStep, StepCategory.ACTION),
    ("Send Message", SendMessageStep, StepCategory.ACTION),
    ("Add Comment", AddCommentStep, StepCategory.ACTION),
    ("Add a Comment", AddCommentStep, StepCategory.ACTION),
    ("Comment on Collected", AddCommentStep, StepCategory.ACTION),
    ("Assign Task", AssignTaskStep, StepCategory.ACTION),
    ("Update This", UpdateItemStep, StepCategory.ACTION),  # "Update This <AppName> Item"
    ("Update Item", UpdateItemStep, StepCategory.ACTION),
    ("Update Collected", UpdateItemStep, StepCategory.ACTION),
    ("Update All Referenced", UpdateItemStep, StepCategory.ACTION),
    ("Create Item", CreateItemStep, StepCategory.ACTION),
    ("Make a PDF", MakePdfStep, StepCategory.ACTION),
    ("Build Excel", BuildExcelStep, StepCategory.ACTION),
    ("Trigger Flow on Related", TriggerFlowOnRelatedStep, StepCategory.ACTION),
    ("Trigger Flow on Collected", TriggerFlowStep, StepCategory.ACTION),
    ("Trigger Flow", TriggerFlowStep, StepCategory.ACTION),
    ("Update Widget", UpdateWidgetStep, StepCategory.ACTION),
    ("Display Page", DisplayPageStep, StepCategory.ACTION),
    ("Delete Item", ActionStep, StepCategory.ACTION),
    ("Delete Comment", ActionStep, StepCategory.ACTION),
    ("Delete File", ActionStep, StepCategory.ACTION),
    ("Complete Item Task", ActionStep, StepCategory.ACTION),
    ("Delete Item Task", ActionStep, StepCategory.ACTION),
    ("Share Item", ActionStep, StepCategory.ACTION),
    ("Attach File", ActionStep, StepCategory.ACTION),
]


def create_step(
    step_number: int,
    action_type: str,
    parameters: Optional[dict] = None,
    flow_id: Optional[str] = None,
) -> AnyStep:
    """Factory function to create the appropriate step model based on action_type.

    Creates the specific step model that matches the action_type.
    Always returns the specific step type (e.g., HttpCallStep, VariableCalcStep).

    Args:
        step_number: The step number (1-based)
        action_type: The action type string from Globiflow
        parameters: Dict of parameter values extracted from the step
        flow_id: Optional flow ID to include in the step

    Returns:
        The specific step model for the action_type

    Raises:
        ValidationError: If required fields for the step type are missing
        ValueError: If action_type doesn't match any known step type
    """
    params = parameters or {}

    # Find matching step class and category
    step_class = None
    category = None

    for pattern, cls, cat in _STEP_TYPE_MAPPINGS:
        if pattern.lower() in action_type.lower():
            step_class = cls
            category = cat
            break

    if step_class is None:
        raise ValueError(f"Unknown action type: {action_type}")

    # Build data for the step
    step_data = {
        "step_number": step_number,
        "action_type": action_type,
        "category": category,
        **params,
    }

    # Add flow_id if provided
    if flow_id is not None:
        step_data["flow_id"] = flow_id

    # Create the specific step class - will raise ValidationError if required fields missing
    return step_class(**step_data)
